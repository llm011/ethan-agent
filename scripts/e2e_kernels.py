#!/usr/bin/env python3
"""多内核端到端验证脚本。

比跑单测更接近真实：它打真实 HTTP、走真实 SSE、真的起外部 CLI 子进程。
单测能验证「代码逻辑对」，但验证不了「用户点一下之后到底发生了什么」——
比如服务进程的 PATH 里没有 CLI、SSE 事件字段写错、落库的 model 不对，
这些都只有端到端才暴露（本次三个 bug 全是这样发现的）。

用法：

    python scripts/e2e_kernels.py                    # 全量检查
    python scripts/e2e_kernels.py --quick            # 只查列表，不发对话
    python scripts/e2e_kernels.py --kernel pi        # 只测某个内核
    python scripts/e2e_kernels.py --restore          # 跑完恢复原内核

前置：ethan serve 在跑（默认 8900），配置里有 network.auth_token。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _read_token() -> str:
    """从 ~/.ethan/config.yaml 读 auth_token（不引入 yaml 依赖，手工找）。"""
    cfg = Path.home() / ".ethan" / "config.yaml"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("auth_token:"):
                return s.split(":", 1)[1].strip().strip("\"'")
    return ""


class Client:
    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def _req(self, path: str, *, method="GET", body=None, timeout=30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        return urllib.request.urlopen(req, timeout=timeout)

    def json(self, path: str, **kw):
        with self._req(path, **kw) as r:
            return json.loads(r.read())

    def delete_session(self, session_id: str) -> bool:
        """删掉测试会话，避免污染用户的会话列表。"""
        try:
            with self._req(f"/api/sessions/{session_id}", method="DELETE", timeout=15):
                return True
        except Exception:
            return False

    def chat(self, prompt: str, timeout: int = 200, session_id: str = "") -> list[dict]:
        """发一条消息，返回解析后的 SSE 事件列表。

        session_id 必须显式传：不传的话每次调用都会在用户会话列表里新建一条
        「1+1 等于几」的垃圾对话，污染真实历史。（第一次跑这个脚本时忘了，
        给用户留了 7 个测试会话，已清理并加了这个参数。）
        """
        body = {
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "channel": "web",
        }
        if session_id:
            body["session_id"] = session_id
        events: list[dict] = []
        with self._req("/api/chat", method="POST", body=body, timeout=timeout) as r:
            for raw in r:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
        return events


ANSIC = {
    "ok": "\033[32m",
    "warn": "\033[33m",
    "err": "\033[31m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "end": "\033[0m",
}


def c(text: str, kind: str) -> str:
    return f"{ANSIC.get(kind, '')}{text}{ANSIC['end']}"


def check_health(cli: Client) -> bool:
    try:
        h = cli.json("/api/health")
        print(f"  服务在线  version={h.get('version')}  agent={h.get('agent_name')}")
        return True
    except Exception as e:
        print(c(f"  服务不可达: {e}", "err"))
        return False


def list_kernels(cli: Client) -> dict:
    data = cli.json("/api/kernels")
    print(f"\n{c('内核列表', 'bold')}  当前默认: {data['default']}")
    print(f"  {'':2s} {'kind':13s} {'name':15s} {'安装命令'}")
    print("  " + "-" * 74)
    for k in data["kernels"]:
        mark = c("✓", "ok") if k["available"] else c("✗", "err")
        cmd = k["install_command"] or "-"
        print(f"  {mark}  {k['kind']:13s} {k['name']:15s} {c(cmd[:40], 'dim')}")
        if not k["available"] and k["reason"]:
            print(f"       {c(k['reason'][:70], 'warn')}")
    return data


def select_kernel(cli: Client, kind: str) -> bool:
    try:
        out = cli.json(
            "/api/kernels/select", method="POST", body={"kind": kind, "auto_install": True}
        )
        print(f"  切换成功 → {out.get('default')}")
        return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        print(c(f"  切换失败 (HTTP {e.code}): {detail[:300]}", "err"))
        return False


def run_chat(cli: Client, kind: str, prompt: str, session_id: str = "") -> dict:
    """发一条真实消息，检查 SSE 事件是否体现了正确的内核。"""
    print(f"\n{c(f'对话测试 [{kind}]', 'bold')}")
    t0 = time.time()
    try:
        events = cli.chat(prompt, session_id=session_id)
    except Exception as e:
        print(c(f"  请求失败: {e}", "err"))
        return {"ok": False}

    elapsed = time.time() - t0
    kernel_evt = next((e for e in events if "kernel" in e), None)
    model_evt = next((e for e in events if "model" in e and "kernel" not in e), None)
    content = "".join(e.get("content", "") for e in events if "content" in e)
    done = next((e for e in events if e.get("done")), None)

    expected_kernel = kind
    actual = (kernel_evt or {}).get("kernel", "ethan")
    ok = actual == expected_kernel

    print(f"  kernel 事件: {actual:13s} {'✓' if ok else c('✗ 期望 ' + expected_kernel, 'err')}")
    if model_evt:
        print(f"  model 事件:  {model_evt.get('model', '')}")
    print(f"  正文: {c(content[:80] or '(空)', 'dim')}")
    if done:
        print(
            f"  耗时: ttfb={done.get('ttfb_ms')}ms total={done.get('total_ms')}ms"
            f"  usage={done.get('usage')}"
        )
        # 落库的 model 必须反映真实执行者，否则会话历史会撒谎
        db_model = done.get("model", "")
        model_ok = (kind == "ethan") or (db_model != "")
        if not model_ok:
            print(c(f"  ⚠ done.model 异常: {db_model!r}", "warn"))
    print(f"  墙钟 {elapsed:.1f}s")
    return {"ok": ok, "content": content, "done": done}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8900")
    ap.add_argument("--token", default="")
    ap.add_argument("--kernel", default="", help="只测某个内核")
    ap.add_argument("--quick", action="store_true", help="只查列表，不发对话")
    ap.add_argument("--restore", action="store_true", help="跑完恢复原内核")
    args = ap.parse_args()

    token = args.token or _read_token()
    if not token:
        print(c("找不到 auth_token（~/.ethan/config.yaml 的 network.auth_token）", "err"))
        return 2

    cli = Client(args.base, token)

    print(c("=" * 76, "bold"))
    print(c("多内核端到端验证", "bold"))
    print(c("=" * 76, "bold"))

    if not check_health(cli):
        return 2

    data = list_kernels(cli)
    original = data["default"]

    if args.quick:
        print()
        return 0

    # 要测哪些内核：默认测所有可用的
    targets = (
        [args.kernel]
        if args.kernel
        else [k["kind"] for k in data["kernels"] if k["available"]]
    )

    results: dict[str, dict] = {}
    prompt = "用一句话回答：1+1 等于几"
    # 所有内核共用一个专用测试会话，跑完删掉——绝不在用户的会话列表里留垃圾。
    # session_id 用固定前缀，便于万一异常中断时人工定位。
    test_sid = f"s_e2e_kernels_{int(time.time())}"
    print(f"\n{c('测试会话', 'dim')} {test_sid}（跑完自动删除）")
    try:
        for kind in targets:
            if not select_kernel(cli, kind):
                results[kind] = {"ok": False}
                continue
            results[kind] = run_chat(cli, kind, prompt, session_id=test_sid)
    finally:
        # 无论成功失败/异常中断，都清理；失败也不该让用户的会话列表被污染
        if cli.delete_session(test_sid):
            print(c("\n已删除测试会话", "dim"))
        else:
            print(c(f"\n⚠ 测试会话删除失败，请手动清理: {test_sid}", "warn"))

    if args.restore:
        # 固定恢复到 ethan，而不是「脚本启动时的值」——脚本自己会切换内核，
        # 启动值可能是上一次异常中断留下的中间态（实测踩到：恢复成了 pi）。
        print(f"\n{c('恢复默认内核 → ethan', 'bold')}")
        if original not in ("", "ethan"):
            print(c(f"  （启动时是 {original}，为安全起见统一回到 ethan）", "dim"))
        select_kernel(cli, "ethan")

    print(f"\n{c('汇总', 'bold')}")
    print("  " + "-" * 40)
    failed = 0
    for kind, r in results.items():
        if r.get("ok"):
            print(f"  {c('✓', 'ok')} {kind}")
        else:
            print(f"  {c('✗', 'err')} {kind}")
            failed += 1

    print()
    if failed:
        print(c(f"{failed} 个内核未通过", "err"))
        return 1
    print(c("全部通过", "ok"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
