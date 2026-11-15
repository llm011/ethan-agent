r"""README 的准确性测试 —— 防止文档与实现漂移。

## 为什么需要它

用户反馈：「ethan serve restart 文档里写了但命令不存在，我感觉 readme 里还有很多
错误」。逐条核对后确实发现了这些问题：

  · `ethan serve restart` —— 不存在，正确是 `ethan server restart`
    （`serve` 在前台跑 API，只有 stop 子命令；`server` 才管 launchd）
  · `GET /sessions/{id}` —— 实际参数名是 `{session_id}`
  · `GET /memory/records/{id}` —— 该端点根本不存在
  · README.md 整体是 #443 那批**已回退功能**的宣传稿
    （Core Bundle、场景感知、`kernel.type` 配置……全都不存在）

文档漂移不会让测试变红，所以一直没人发现。这个文件把「README 里写的」和
「代码里真有的」绑在一起，写错就红。

## 覆盖范围

1. 命令行：README 提到的每个 `ethan xxx` 子命令必须存在
2. API 端点：每个 METHOD /path 必须在路由表里（README 省略 /api 前缀）
3. 文档链接：每个 `](docs/*.md)` 必须存在
4. 关键事实：版本号、内核数量等不能明显过期
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


# ── 文档链接 ─────────────────────────────────────────────────


def test_all_doc_links_exist():
    """README 里链到的每个 docs/*.md 都要真实存在。

    曾经链了 `kernel-switching.md` / `api-reference.md` / `best-practices.md`，
    三个都不存在。
    """
    src = _readme()
    links = re.findall(r"\]\((docs/[\w./-]+\.md)\)", src)
    assert links, "README 里一个文档链接都没有，格式可能变了"
    missing = [lnk for lnk in links if not (ROOT / lnk).exists()]
    assert not missing, f"README 链接到不存在的文档: {missing}"


# ── 命令 ─────────────────────────────────────────────────────


def _ethan_subcommands(top: str) -> set[str]:
    """列出某个顶层命令的子命令。"""
    r = subprocess.run(
        [str(ROOT / ".venv/bin/ethan"), top, "--help"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return set()
    subs = set()
    in_commands = False
    for line in r.stdout.splitlines():
        if "Commands" in line:
            in_commands = True
            continue
        if in_commands:
            m = re.match(r"│\s+([a-z][a-z-]*)\s{2,}", line)
            if m:
                subs.add(m.group(1))
    return subs


def test_ethan_commands_in_readme_exist():
    """README 里 `ethan xxx` 形式的命令必须真实存在。

    这条就是为了抓 `ethan serve restart` 那种情况——写了但命令不存在，
    用户照着敲一遍才发现。
    """
    src = _readme()
    # 只取代码块里的 ethan 命令，避免正文散文里的误判
    in_block = False
    cmds = []
    for line in src.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        m = re.match(r"\s*ethan ([a-z]+)(?: ([a-z]+))?", line)
        if m:
            cmds.append((m.group(1), m.group(2) or ""))

    assert cmds, "README 代码块里没找到 ethan 命令，格式可能变了"

    bad = []
    for top, sub in set(cmds):
        subs = _ethan_subcommands(top)
        if not subs and sub:
            # 顶层命令本身不可用时才报错；无子命令是正常的（如 `ethan` 裸命令）
            r = subprocess.run(
                [str(ROOT / ".venv/bin/ethan"), top, "--help"],
                capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                bad.append(f"ethan {top}")
                continue
        if sub and subs and sub not in subs:
            bad.append(f"ethan {top} {sub}")

    assert not bad, f"README 里写了不存在的命令: {bad}"


def test_serve_and_server_are_distinguished():
    """`ethan serve` 与 `ethan server` 的职责不能混。

    serve  = 前台跑 API 服务，子命令只有 stop
    server = 管理 macOS launchd 后台服务（install/uninstall/restart/status）

    曾经 README 写了 `ethan serve restart`（不存在），用户照敲会报错。
    """
    serve_subs = _ethan_subcommands("serve")
    server_subs = _ethan_subcommands("server")

    assert "restart" not in serve_subs, "serve 不该有 restart（那是 server 的职责）"
    assert "restart" in server_subs, "server 应该有 restart"
    assert serve_subs, "serve 应该有子命令（至少 stop）"

    # README 里不能出现 ethan serve restart
    src = _readme()
    assert not re.search(r"ethan serve restart(?!\w)", src), (
        "README 写了不存在的 `ethan serve restart`，应为 `ethan server restart`"
    )


# ── API 端点 ─────────────────────────────────────────────────


def test_api_endpoints_in_readme_exist():
    """README 的 API 表里每个端点都要在路由表里。

    README 省略 `/api` 前缀，所以两种写法都试。
    曾经写了 `GET /memory/records/{id}`，这个端点根本不存在。
    """
    src = _readme()
    endpoints = [
        (m.group(1), m.group(2).split("?")[0])
        for m in re.finditer(r"^(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", src, re.M)
    ]
    assert endpoints, "README 里没找到 API 端点表，格式可能变了"

    from ethan.interface.api import app

    routes = set()
    for r in app.routes:
        path = getattr(r, "path", "")
        for method in (getattr(r, "methods", set()) or set()):
            if method not in ("HEAD", "OPTIONS"):
                routes.add((method, path))

    bad = []
    for method, path in endpoints:
        if (method, "/api" + path) in routes or (method, path) in routes:
            continue
        bad.append(f"{method} {path}")

    assert not bad, f"README 里写了不存在的 API: {bad}"


# ── 关键事实 ─────────────────────────────────────────────────


def test_readme_has_no_removed_features():
    """README 不能宣传已被移除/从未实现的功能。

    README.md 一度是 #443 那批功能的宣传稿：Core Bundle、场景感知、
    `kernel.type` 配置——全都在后续回退中删掉了。
    """
    src = _readme()
    removed = {
        "scene_detector": "场景检测器已删除",
        "Core Bundle": "core bundle 概念已移除",
        "kernel.type": "配置字段是 kernel.default，不是 kernel.type",
        "claude_config": "无此配置段",
    }
    hits = [f"{k}（{why}）" for k, why in removed.items() if k in src]
    assert not hits, f"README 提到已不存在的功能: {hits}"


def test_version_not_obviously_stale():
    """README 里的版本号不能落后太多。

    曾经写着 v0.5.395，而当时已经是 0.5.403+。
    """
    src = _readme()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    cur = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)

    # 从版本号里取主版本+次版本做粗比（README 允许写 1.0.0b6 这种具体值）
    m = re.search(r"版本\*\*:\s*([\w.]+)", src)
    if not m:
        pytest.skip("README 没有版本行")

    stated = m.group(1)
    assert stated.split("b")[0].split("a")[0].split("rc")[0][:3] == cur.split("b")[0][:3], (
        f"README 版本 {stated} 与 pyproject {cur} 主次版本不一致"
    )
