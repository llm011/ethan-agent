"""flomo 浮墨笔记工具 — 读取/搜索/写入/编辑。

代码来源（非原创，借鉴自以下开源项目）：

- 私有 API（读取/创建/编辑）：Undertone0809/flomo-skills
  https://github.com/Undertone0809/flomo-skills
  借鉴内容：API base/参数、MD5 签名算法、Bearer token 鉴权、端点设计、
  access_token 提取思路、HTML→Markdown 转换、标签提取等数据处理逻辑。
- Webhook 写入：直接 POST {"content": "..."} 到 https://flomoapp.com/iwh/{key}/，
  未参考具体外部仓库（接口简单，flomo 官方文档即可说明）。

跨平台适配（macOS 非沙盒版 / Windows / secrets 注入）为本项目扩展，原项目仅支持 macOS 沙盒版。

前置条件：
- 写入（webhook）：需先 set_secret(name="flomo_webhook_key", value="<key>")
- 读取/编辑（API）：需本机已安装并登录 flomo 客户端（macOS / Windows 均可），
  或在容器/无客户端环境用 set_secret(name="flomo-access-token", value="<id|token>") 配置

跨平台支持：
- macOS 沙盒版（App Store）：~/Library/Containers/com.flomoapp.m/.../flomo/
- macOS 非沙盒版（官网下载）：~/Library/Application Support/flomo/
- Windows：%APPDATA%/flomo/（即 C:\\Users\\<user>\\AppData\\Roaming\\flomo\\）

token 提取优先级：
1. secrets（set_secret 存的 flomo-access-token，经 load_secret_env() 读取，与 shell 注入同源）
2. config.json 的 user.access_token（格式 id|token，最稳定）
3. LevelDB 本地存储搜索 access_token":"..."（兜底，兼容旧版客户端）

CLI 用法：
  python flomo.py query [--keyword K] [--tag T] [--days N] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--limit N]
  python flomo.py tags [--prefix P] [--days N] [--limit N]
  python flomo.py create --content "笔记内容 #标签"
  python flomo.py edit --slug <slug|URL> --content "新内容 #标签"
  python flomo.py write --content "笔记内容 #标签"   # Webhook
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# ── flomo API 常量（逆向自 flomo 客户端）──
_BASE_URL = "https://flomoapp.com/api/v1"
_API_SECRET = "dbbc3dd73364b4084c3a69346e0ce2b2"
_APP_VERSION = "5.26.12"
_PLATFORM = "mac"
_TZ = "8:0"
_TOKEN_RE = re.compile(r'access_token":"([^"]+)')
_TAG_RE = re.compile(r"(?<!\w)#([^\s#]+)")
_MEMO_URL_ID_RE = re.compile(r"[?&]memo_id=([A-Za-z0-9_-]+)")
_TRAILING_TAG_PUNCT = ".,;:!?，。！？；：、）)]】》」』"
_WEBHOOK_BASE = "https://flomoapp.com/iwh"


# ── 跨平台路径 / Token 提取 ──

def _flomo_data_dirs() -> list[Path]:
    """返回所有可能的 flomo 数据目录（按优先级排序，跨平台）。

    macOS:
      - 非沙盒版（官网下载）：~/Library/Application Support/flomo/
      - 沙盒版（App Store）：~/Library/Containers/com.flomoapp.m/Data/Library/Application Support/flomo/
    Windows:
      - %APPDATA%/flomo/（即 C:\\Users\\<user>\\AppData\\Roaming\\flomo\\）
    """
    candidates: list[Path] = []
    home = Path.home()
    if sys.platform == "darwin":
        # 非沙盒版优先（更常见，token 在 config.json）
        candidates.append(home / "Library/Application Support/flomo")
        # 沙盒版（App Store 安装）
        candidates.append(
            home / "Library/Containers/com.flomoapp.m/Data/Library/Application Support/flomo"
        )
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "flomo")
        # 兜底：手动拼路径
        candidates.append(home / "AppData/Roaming/flomo")
    else:
        # Linux / 其他：尝试标准 XDG 路径
        candidates.append(home / ".config/flomo")
    return [d for d in candidates if d.exists()]


def _find_access_token() -> str:
    """提取 access_token，优先级：secrets → 客户端本地存储。

    secrets 通过 core 的 load_secret_env() 读取（与 shell 注入同源，不直接碰文件）。
    容器/无客户端环境把 token 存进 secrets；本机用客户端本地存储。
    """
    # 方式 0：secrets（与 shell 子进程注入同源的 load_secret_env，不直接读文件）
    try:
        from ethan.core.secrets_store import load_secret_env
        token = load_secret_env().get("FLOMO_ACCESS_TOKEN")
        if token:
            return token
    except Exception:
        pass

    dirs = _flomo_data_dirs()
    if not dirs:
        raise RuntimeError(
            "未找到 flomo 客户端数据目录，且 secrets 未配置 token。\n"
            "  方案1: set_secret(name=\"flomo-access-token\", value=\"<id|token>\")\n"
            "  方案2: 安装并登录 flomo 客户端（macOS/Windows）"
        )

    # 方式 1：从 config.json 读取（优先，最稳定）
    for d in dirs:
        cfg = d / "config.json"
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                token = data.get("user", {}).get("access_token", "")
                if token:
                    return token
            except (json.JSONDecodeError, OSError):
                continue

    # 方式 2：从 LevelDB 搜索（兜底，兼容旧版客户端）
    for d in dirs:
        leveldb = d / "Local Storage/leveldb"
        if not leveldb.is_dir():
            continue
        for path in sorted(leveldb.iterdir()):
            if path.suffix not in {".ldb", ".log"} or not path.is_file():
                continue
            text = path.read_bytes().decode("latin1", errors="ignore")
            match = _TOKEN_RE.search(text)
            if match:
                return match.group(1)

    raise RuntimeError(
        "未能从 flomo 客户端提取 access_token，请确保 flomo 已安装并登录。\n"
        "  已检查目录: " + ", ".join(str(d) for d in dirs)
    )


def _find_webhook_key() -> str:
    """从 secrets 读 webhook key（与 shell 注入同源）。"""
    try:
        from ethan.core.secrets_store import load_secret_env
        return load_secret_env().get("FLOMO_WEBHOOK_KEY", "")
    except Exception:
        return ""


# ── API 请求签名（MD5）──

def _sign_params(params: dict[str, object]) -> str:
    pieces: list[str] = []
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        if value == "" and value != 0:
            continue
        if isinstance(value, list):
            for item in sorted(value, key=lambda item: str(item)):
                pieces.append(f"{key}[]={item}")
            continue
        pieces.append(f"{key}={value}")
    payload = "&".join(pieces) + _API_SECRET
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _api_request(method: str, path: str, extra_params: dict[str, object] | None = None) -> dict:
    token = _find_access_token()
    params: dict[str, object] = {
        "timestamp": int(datetime.now().timestamp()),
        "api_key": "flomo_web",
        "app_version": _APP_VERSION,
        "platform": _PLATFORM,
        "webp": "1",
    }
    if extra_params:
        params.update(extra_params)
    params["sign"] = _sign_params(params)

    upper = method.upper()
    body: bytes | None = None
    url = f"{_BASE_URL}{path}"
    if upper == "GET":
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    else:
        body = json.dumps(params).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method=upper,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "platform": "Mac",
            "device-model": "Mac",
            "device-id": "ethan-flomo",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code") != 0:
        raise RuntimeError(f"flomo API error: {data}")
    return data["data"]


def _api_get(path: str, extra_params: dict[str, object] | None = None) -> dict | list:
    return _api_request("GET", path, extra_params)


def _api_put(path: str, extra_params: dict[str, object] | None = None) -> dict:
    return _api_request("PUT", path, extra_params)


# ── 数据获取 ──

def _fetch_all_memos() -> list[dict]:
    """分页拉取全部 memos（按 updated_at + slug 游标翻页）。"""
    limit = 200
    latest_updated_at = 0
    latest_slug = ""
    all_memos: list[dict] = []

    for _ in range(50):
        params: dict[str, object] = {
            "limit": limit,
            "latest_updated_at": latest_updated_at,
            "tz": _TZ,
        }
        if latest_slug:
            params["latest_slug"] = latest_slug
        chunk = _api_get("/memo/updated/", params)
        all_memos.extend(chunk)
        if len(chunk) < limit:
            break
        last = chunk[-1]
        latest_updated_at = int(
            datetime.strptime(last["updated_at"], "%Y-%m-%d %H:%M:%S").timestamp()
        )
        latest_slug = last["slug"]

    unique = {memo["slug"]: memo for memo in all_memos}
    return sorted(
        [memo for memo in unique.values() if not memo.get("deleted_at")],
        key=lambda memo: memo["created_at"],
    )


def _fetch_memo_by_slug(slug: str) -> dict:
    """通过 slug 查找单条 memo（遍历分页直到命中）。"""
    limit = 200
    latest_updated_at = 0
    latest_slug = ""

    for _ in range(50):
        params: dict[str, object] = {
            "limit": limit,
            "latest_updated_at": latest_updated_at,
            "tz": _TZ,
        }
        if latest_slug:
            params["latest_slug"] = latest_slug
        chunk = _api_get("/memo/updated/", params)
        for memo in chunk:
            if memo.get("slug") == slug:
                if memo.get("deleted_at"):
                    raise RuntimeError(f"Memo 已删除: {slug}")
                return memo
        if len(chunk) < limit:
            break
        last = chunk[-1]
        latest_updated_at = int(
            datetime.strptime(last["updated_at"], "%Y-%m-%d %H:%M:%S").timestamp()
        )
        latest_slug = last["slug"]

    raise RuntimeError(f"未找到 memo: {slug}")


# ── 格式转换 ──

def _html_to_markdown(html: str) -> str:
    replacements = [
        (r"<br\s*/?>", "\n"),
        (r"<hr\s*/?>", "\n\n---\n\n"),
        (r"</p>\s*<p>", "\n\n"),
        (r"<p>", ""),
        (r"</p>", ""),
        (r"<li>\s*<p>", "- "),
        (r"</p>\s*</li>", "\n"),
        (r"<li>", "- "),
        (r"</li>", "\n"),
        (r"<ul>|</ul>|<ol>|</ol>", "\n"),
        (r"<strong>(.*?)</strong>", r"**\1**"),
        (r"<em>(.*?)</em>", r"*\1*"),
        (r"<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"[\2](\1)"),
        (r"<[^>]+>", ""),
    ]
    out = html
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE | re.DOTALL)
    out = (
        out.replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("\r", "")
    )
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _extract_tags(text: str) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for raw in _TAG_RE.findall(text):
        tag = raw.strip().rstrip(_TRAILING_TAG_PUNCT).strip("/")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _add_derived_fields(memo: dict) -> dict:
    markdown = _html_to_markdown(memo.get("content", ""))
    return {**memo, "markdown": markdown, "tags": _extract_tags(markdown)}


def _plain_text_to_html(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise RuntimeError("Memo 内容不能为空")
    blocks = re.split(r"\n{2,}", text)
    paragraphs = []
    for block in blocks:
        escaped = html_mod.escape(block, quote=False).replace("\n", "<br/>")
        paragraphs.append(f"<p>{escaped}</p>")
    return "".join(paragraphs)


def _memo_web_url(slug: str) -> str:
    return f"https://v.flomoapp.com/mine/?memo_id={slug}"


def _extract_memo_slug(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise RuntimeError("Memo slug 或 URL 不能为空")
    match = _MEMO_URL_ID_RE.search(value)
    if match:
        return match.group(1)
    return value


def _snippet(text: str, max_len: int = 120) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= max_len else collapsed[: max_len - 1] + "…"


def _filter_memos(
    memos: list[dict],
    keyword: str | None,
    tag: str | None,
    start_date: str | None,
    end_date: str | None,
) -> list[dict]:
    keyword_lower = keyword.lower() if keyword else None
    filtered = []
    for memo in memos:
        created = memo["created_at"][:10]
        if start_date and created < start_date:
            continue
        if end_date and created > end_date:
            continue
        if tag and tag not in memo["tags"]:
            continue
        if keyword_lower:
            haystack = f"{memo['markdown']}\n{' '.join(memo['tags'])}".lower()
            if keyword_lower not in haystack:
                continue
        filtered.append(memo)
    return filtered


# ── 命令实现 ──

def cmd_query(
    keyword: str = "",
    tag: str = "",
    days: int = 0,
    start_date: str = "",
    end_date: str = "",
    limit: int = 20,
) -> str:
    """搜索/查询 flomo 笔记。"""
    try:
        memos = [_add_derived_fields(m) for m in _fetch_all_memos()]
    except RuntimeError as e:
        return f"✗ 无法读取 flomo: {e}\n  （读取需本机已安装并登录 flomo 客户端）"

    if days:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

    hits = _filter_memos(memos, keyword or None, tag or None, start_date or None, end_date or None)
    hits = hits[:limit]

    if not hits:
        return "没有找到匹配的笔记。"

    lines = [f"找到 {len(hits)} 条笔记：", ""]
    for memo in hits:
        tags_str = ", ".join("#" + t for t in memo["tags"]) if memo["tags"] else "(无标签)"
        lines.extend([
            f"## {memo['created_at']}",
            "",
            _snippet(memo["markdown"], 300),
            "",
            f"- slug: {memo['slug']}",
            f"- url: {_memo_web_url(memo['slug'])}",
            f"- tags: {tags_str}",
            "",
        ])
    return "\n".join(lines)


def cmd_tags(prefix: str = "", days: int = 0, limit: int = 50) -> str:
    """列出 flomo 标签及频率。"""
    try:
        memos = [_add_derived_fields(m) for m in _fetch_all_memos()]
    except RuntimeError as e:
        return f"✗ 无法读取 flomo: {e}\n  （读取需本机已安装并登录 flomo 客户端）"

    if days:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        memos = _filter_memos(memos, None, None, start_date, None)

    tag_counter: Counter[str] = Counter()
    for memo in memos:
        for tag in memo["tags"]:
            tag_counter[tag] += 1

    rows = [(tag, count) for tag, count in tag_counter.most_common()]
    if prefix:
        prefix = prefix.strip().strip("/")
        rows = [(tag, count) for tag, count in rows if tag.startswith(prefix)]
    rows = rows[:limit]

    if not rows:
        return "没有找到匹配的标签。"

    lines = [f"标签统计（共 {len(rows)} 个）：", ""]
    for tag, count in rows:
        lines.append(f"- #{tag}: {count}")
    return "\n".join(lines)


def cmd_create(content: str) -> str:
    """通过 API 创建 flomo 笔记（返回完整 memo 对象）。"""
    if not content.strip():
        return "✗ 内容不能为空。"
    try:
        html_content = _plain_text_to_html(content)
        created = _api_put("/memo", {
            "content": html_content,
            "created_at": int(datetime.now().timestamp()),
            "source": "web",
            "file_ids": [],
            "tz": _TZ,
        })
        memo = _add_derived_fields(created)
        tags_str = ", ".join("#" + t for t in memo["tags"]) if memo["tags"] else "(无标签)"
        return (
            f"✓ 创建成功\n"
            f"  slug: {memo['slug']}\n"
            f"  url: {_memo_web_url(memo['slug'])}\n"
            f"  tags: {tags_str}\n"
            f"  created_at: {memo.get('created_at', '?')}"
        )
    except RuntimeError as e:
        return f"✗ 创建失败: {e}\n  （创建需本机已安装并登录 flomo 客户端，或用 write 走 webhook）"


def cmd_edit(slug: str, content: str) -> str:
    """编辑已有 flomo 笔记。"""
    if not content.strip():
        return "✗ 内容不能为空。"
    try:
        memo_slug = _extract_memo_slug(slug)
        existing = _fetch_memo_by_slug(memo_slug)
        html_content = _plain_text_to_html(content)
        file_ids = [f["id"] for f in existing.get("files", []) if "id" in f]
        updated = _api_put(f"/memo/{memo_slug}", {
            "content": html_content,
            "local_updated_at": int(datetime.now().timestamp()),
            "source": existing.get("source", "web"),
            "file_ids": file_ids,
            "tz": _TZ,
            "pin": existing.get("pin", 0),
        })
        memo = _add_derived_fields(updated)
        tags_str = ", ".join("#" + t for t in memo["tags"]) if memo["tags"] else "(无标签)"
        return (
            f"✓ 编辑成功\n"
            f"  slug: {memo['slug']}\n"
            f"  url: {_memo_web_url(memo['slug'])}\n"
            f"  tags: {tags_str}\n"
            f"  updated_at: {memo.get('updated_at', '?')}"
        )
    except RuntimeError as e:
        return f"✗ 编辑失败: {e}\n  （编辑需本机已安装并登录 flomo 客户端）"


def cmd_write(content: str) -> str:
    """通过 Webhook 写入笔记。"""
    webhook_key = _find_webhook_key()
    if not webhook_key:
        return (
            "✗ 未配置 flomo_webhook_key。\n"
            "请先获取 webhook key（flomo → 设置 → API 及第三方工具 → Webhook URL），\n"
            "然后用 set_secret(name='flomo_webhook_key', value='<key>') 保存。"
        )

    url = f"{_WEBHOOK_BASE}/{webhook_key}/"
    body = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"✗ 写入失败: {e}"

    if data.get("code") == 0:
        memo = data.get("memo", {})
        slug = memo.get("slug", "")
        tags = _extract_tags(content)
        url_str = _memo_web_url(slug) if slug else ""
        lines = ["✓ 写入成功"]
        if slug:
            lines.append(f"  slug: {slug}")
            lines.append(f"  url: {url_str}")
        if tags:
            lines.append(f"  tags: {', '.join('#' + t for t in tags)}")
        lines.append(f"  created_at: {memo.get('created_at', '?')}")
        return "\n".join(lines)
    elif data.get("code") == -1:
        return (
            "✗ 写入失败: webhook key 失效或频率限制。\n"
            "  请引导用户重新获取 key（flomo → 设置 → API 及第三方工具 → Webhook URL）。"
        )
    return f"✗ 写入失败: {json.dumps(data, ensure_ascii=False)}"


# ── CLI 入口 ──

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flomo",
        description="flomo 浮墨笔记 CLI — 读取/搜索/写入/编辑",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # query
    p_query = sub.add_parser("query", help="搜索/查询笔记（私有 API）")
    p_query.add_argument("--keyword", default="", help="搜索关键词（不区分大小写）")
    p_query.add_argument("--tag", default="", help="按标签过滤（如 '闪念/思考'）")
    p_query.add_argument("--days", type=int, default=0, help="仅显示最近 N 天的笔记")
    p_query.add_argument("--start", dest="start_date", default="", help="起始日期 YYYY-MM-DD")
    p_query.add_argument("--end", dest="end_date", default="", help="结束日期 YYYY-MM-DD")
    p_query.add_argument("--limit", type=int, default=20, help="最多返回条数（默认 20）")

    # tags
    p_tags = sub.add_parser("tags", help="列出标签及频率（私有 API）")
    p_tags.add_argument("--prefix", default="", help="按前缀过滤（如 '闪念'）")
    p_tags.add_argument("--days", type=int, default=0, help="仅统计最近 N 天的笔记")
    p_tags.add_argument("--limit", type=int, default=50, help="最多返回标签数（默认 50）")

    # create
    p_create = sub.add_parser("create", help="创建笔记（私有 API，支持 HTML 富文本）")
    p_create.add_argument("--content", required=True, help="笔记内容，末尾可加 #标签")

    # edit
    p_edit = sub.add_parser("edit", help="编辑已有笔记（私有 API）")
    p_edit.add_argument("--slug", required=True, help="笔记 slug 或 flomo URL")
    p_edit.add_argument("--content", required=True, help="新内容，末尾可加 #标签")

    # write
    p_write = sub.add_parser("write", help="写入笔记（Webhook，仅需 webhook key）")
    p_write.add_argument("--content", required=True, help="笔记内容，末尾可加 #标签")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "query":
        print(cmd_query(
            keyword=args.keyword, tag=args.tag, days=args.days,
            start_date=args.start_date, end_date=args.end_date, limit=args.limit,
        ))
    elif args.command == "tags":
        print(cmd_tags(prefix=args.prefix, days=args.days, limit=args.limit))
    elif args.command == "create":
        print(cmd_create(content=args.content))
    elif args.command == "edit":
        print(cmd_edit(slug=args.slug, content=args.content))
    elif args.command == "write":
        print(cmd_write(content=args.content))
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
