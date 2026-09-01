#!/usr/bin/env python3
"""企查查智能体数据平台（agent.qcc.com）MCP 直连客户端。

零第三方依赖（仅 python 标准库），通过 MCP streamable HTTP 端点调用
企查查的 9 个 server / 200+ 工具。自带本地文件缓存：

- 缓存目录：~/.ethan/data/qcc/<公司名>/<server>.<tool>_<YYYY-MM-DD>.md
- 查询前先翻缓存：30 天内的结果直接返回，不再调接口（接口按积分计费，
  且同一被查主体每个自然月有积分消耗上限）
- 超过 30 天的缓存视为过期，自动重新调接口，并把新结果按当天日期落盘
  （旧文件保留，作为历史存档，通过文件名即可看出查询日期）

鉴权：
- 环境变量 QCC_AUTHORIZATION（形如 "Bearer xxx"）
- 或 secrets 文件 ~/.ethan/.secrets/qcc-api-key（内容形如
  QCC_AUTHORIZATION=Bearer xxx，或直接写 "Bearer xxx" / 裸 token）

用法：
  python3 qcc.py servers                       # 列出全部 server
  python3 qcc.py tools <server> [--full]       # 列出某 server 的工具
  python3 qcc.py call <server> <tool> --args '{"searchKey": "小米科技有限责任公司"}'
  python3 qcc.py call risk get_serious_violation --args '{"searchKey": "某公司"}' --no-cache
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

MCP_BASE_URL = "https://agent.qcc.com/mcp"
SERVERS = {
    "company": "企业信息（工商登记、股东、实控人、受益所有人、财务等 16 工具）",
    "risk": "风险信息（失信、被执行、限高、严重违法、裁判文书等 38 工具）",
    "operation": "经营信息（招投标、资质荣誉、新闻舆情、纳税等 35 工具）",
    "ipr": "知识产权（商标、专利、软著、数字资产等 18 工具）",
    "history": "历史信息（历史股东/法代/失信/投资等，需企业认证，34 工具）",
    "executive": "董监高（以人查风险：董监高司法风险、关联企业、UBO，44 工具）",
    "regulation": "法律法规（法规检索、法条正文、时效标注）",
    "case": "司法案例（类案检索、权威案例）",
    "tender": "标讯数据（招投标搜索、拟建项目、企业中标查询）",
    "document": "智能文档解析（在线 URL 文档解析）",
}
DEFAULT_TTL_DAYS = 30


# ---------- 鉴权 ----------

def load_authorization():
    auth = os.environ.get("QCC_AUTHORIZATION", "").strip()
    if auth:
        return normalize_auth(auth)
    for path in (
        os.path.expanduser("~/.ethan/.secrets/qcc-api-key"),
        os.path.expanduser("~/.qcc/api-key"),
    ):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line and line.split("=", 1)[0].strip() == "QCC_AUTHORIZATION":
                line = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line:
                return normalize_auth(line)
    raise SystemExit(
        "错误：未找到企查查 API key。\n"
        "请将 key 写入 ~/.ethan/.secrets/qcc-api-key（内容形如 "
        "QCC_AUTHORIZATION=Bearer <token>），或设置环境变量 QCC_AUTHORIZATION。"
    )


def normalize_auth(value):
    value = value.strip()
    if not value:
        raise SystemExit("错误：QCC_AUTHORIZATION 为空。")
    if not value.lower().startswith("bearer "):
        value = "Bearer " + value
    return value


# ---------- MCP 调用 ----------

def mcp_post(server, payload, timeout):
    url = f"{MCP_BASE_URL}/{server}/stream"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": load_authorization(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        if e.code == 401:
            raise SystemExit(
                f"错误：HTTP 401 身份凭证无效（invalid_token）。{body}\n"
                "请到 agent.qcc.com 个人中心确认 key 状态，并更新 "
                "~/.ethan/.secrets/qcc-api-key（内容形如 QCC_AUTHORIZATION=Bearer <token>）。"
            )
        raise SystemExit(f"错误：HTTP {e.code} 调用 {url} 失败：{body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"错误：网络请求失败（{e.reason}），请检查网络连接。")


def parse_mcp_body(body):
    """解析 MCP 响应：兼容 SSE（event/data 行）与纯 JSON 两种格式。"""
    messages = []
    if "data:" in body:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if data_str and data_str != "[DONE]":
                    try:
                        messages.append(json.loads(data_str))
                    except json.JSONDecodeError:
                        pass
    else:
        try:
            messages.append(json.loads(body))
        except json.JSONDecodeError:
            raise SystemExit(f"错误：无法解析响应：\n{body[:800]}")

    for msg in messages:
        if isinstance(msg, dict) and msg.get("error"):
            err = msg["error"]
            code = err.get("code", "")
            text = err.get("message", str(err))
            if "token" in str(text).lower() or code in (401, -32001):
                raise SystemExit(
                    f"错误：身份凭证校验失败（{code}）：{text}\n"
                    "请检查 ~/.ethan/.secrets/qcc-api-key 中的 key 是否有效（过期请在 "
                    "agent.qcc.com 个人中心重新生成并更新 secrets 文件）。"
                )
            raise SystemExit(f"错误：MCP 返回错误（{code}）：{text}")

    for msg in messages:
        result = msg.get("result") if isinstance(msg, dict) else None
        if result is None:
            continue
        if result.get("isError"):
            parts = [
                c.get("text", "")
                for c in result.get("content", [])
                if isinstance(c, dict)
            ]
            raise SystemExit("错误：工具执行失败：\n" + "\n".join(parts)[:800])
        parts = [
            c.get("text", "")
            for c in result.get("content", [])
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        return "\n".join(parts)
    raise SystemExit(f"错误：响应中未找到 result：\n{body[:800]}")


def pretty(text):
    """text 内容若是 JSON 字符串则格式化，否则原样返回。"""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return text


# ---------- 缓存 ----------

def sanitize(name):
    name = re.sub(r'[/\\:*?"<>|\s]+', "_", str(name)).strip("_")
    return name[:120] or "unknown"


def cache_dir_for(search_key):
    base = os.environ.get("QCC_CACHE_DIR", os.path.expanduser("~/.ethan/data/qcc"))
    return os.path.join(base, sanitize(search_key))


def cache_find(cache_dir, server, tool):
    """返回 (path, query_date) 中最新的一份缓存；无则 (None, None)。"""
    pattern = os.path.join(cache_dir, f"{sanitize(server)}.{sanitize(tool)}_*.md")
    best = (None, None)
    for path in glob.glob(pattern):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})\.md$", path)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if best[1] is None or d > best[1]:
            best = (path, d)
    return best


def cache_read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def cache_write(cache_dir, server, tool, search_key, args, text):
    os.makedirs(cache_dir, exist_ok=True)
    today = date.today().isoformat()
    path = os.path.join(cache_dir, f"{sanitize(server)}.{sanitize(tool)}_{today}.md")
    header = (
        f"---\n"
        f"source: 企查查 agent.qcc.com MCP\n"
        f"server: {server}\n"
        f"tool: {tool}\n"
        f"query_date: {today}\n"
        f"args: {json.dumps(args, ensure_ascii=False)}\n"
        f"---\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + text + "\n")
    return path


def cache_age_days(d):
    return (date.today() - d).days


# ---------- 主流程 ----------

def extract_search_key(args):
    """从工具参数里提取主体名（缓存键）。取不到则不做缓存。"""
    if not isinstance(args, dict):
        return None
    for key in ("searchKey", "search_key", "companyName", "company_name", "name"):
        v = args.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def cmd_call(server, tool, args, use_cache=True, ttl_days=DEFAULT_TTL_DAYS, timeout=60):
    if server not in SERVERS:
        raise SystemExit(
            f"错误：未知 server「{server}」，可用：{', '.join(SERVERS)}"
        )
    search_key = extract_search_key(args)
    cache_dir = cache_dir_for(search_key) if search_key else None

    if use_cache and cache_dir:
        path, d = cache_find(cache_dir, server, tool)
        if path and cache_age_days(d) < ttl_days:
            age = cache_age_days(d)
            print(f"# [qcc 缓存命中] {path}（{d} 查询，{age} 天前，未调接口）\n")
            print(pretty(strip_cache_header(cache_read(path))))
            return

    payload = {
        "jsonrpc": "2.0",
        "id": int(datetime.now().timestamp() * 1000) % 100000000,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args, "_meta": {"progressToken": 1}},
    }
    text = parse_mcp_body(mcp_post(server, payload, timeout))

    if cache_dir and search_key:
        try:
            path = cache_write(cache_dir, server, tool, search_key, args, text)
            print(f"# [qcc 已缓存] {path}（本次为实时接口调用，按积分计费）\n")
        except OSError as e:
            print(f"# [qcc 警告] 缓存写入失败：{e}\n", file=sys.stderr)
    print(pretty(text))


def strip_cache_header(text):
    """去掉缓存文件头，返回原始正文。"""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def cmd_tools(server, full=False, timeout=30):
    if server not in SERVERS:
        raise SystemExit(f"错误：未知 server「{server}」，可用：{', '.join(SERVERS)}")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    body = mcp_post(server, payload, timeout)
    messages = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                messages.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                pass
    if not messages:
        try:
            messages.append(json.loads(body))
        except json.JSONDecodeError:
            raise SystemExit("错误：无法解析 tools/list 响应。")
    tools = None
    for msg in messages:
        tools = (msg.get("result") or {}).get("tools")
        if tools:
            break
    if not tools:
        raise SystemExit("错误：响应中未找到工具列表。")
    print(f"# server「{server}」共 {len(tools)} 个工具\n")
    for t in tools:
        desc = t.get("description", "").strip()
        if not full:
            desc = re.sub(r"\s+", " ", desc)[:160]
        schema = t.get("inputSchema", {}).get("properties", {})
        required = t.get("inputSchema", {}).get("required", [])
        params = ", ".join(
            f"{k}*".replace("*", "") + ("*" if k in required else "")
            for k in schema
        )
        print(f"## {t.get('name')}")
        print(f"参数: {params or '（无）'}")
        print(f"说明: {desc}\n")


def main():
    parser = argparse.ArgumentParser(description="企查查智能体数据平台 MCP 客户端（带本地缓存）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("servers", help="列出全部 server")
    p_tools = sub.add_parser("tools", help="列出某 server 的工具")
    p_tools.add_argument("server", choices=sorted(SERVERS))
    p_tools.add_argument("--full", action="store_true", help="输出完整工具说明（不截断）")

    p_call = sub.add_parser("call", help="调用工具")
    p_call.add_argument("server", choices=sorted(SERVERS))
    p_call.add_argument("tool")
    p_call.add_argument("--args", default="{}", help="工具参数，JSON 字符串")
    p_call.add_argument("--no-cache", action="store_true", help="跳过缓存，强制实时调用")
    p_call.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS,
                        help=f"缓存有效期天数（默认 {DEFAULT_TTL_DAYS}）")
    p_call.add_argument("--timeout", type=int, default=60, help="请求超时秒数（默认 60）")

    ns = parser.parse_args()
    if ns.command == "servers":
        for k, v in SERVERS.items():
            print(f"{k}: {v}")
    elif ns.command == "tools":
        cmd_tools(ns.server, full=ns.full)
    elif ns.command == "call":
        try:
            args = json.loads(ns.args)
        except json.JSONDecodeError as e:
            raise SystemExit(f"错误：--args 不是合法 JSON：{e}")
        cmd_call(ns.server, ns.tool, args,
                 use_cache=not ns.no_cache, ttl_days=ns.ttl_days, timeout=ns.timeout)


if __name__ == "__main__":
    main()
