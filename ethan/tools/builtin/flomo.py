"""flomo 浮墨笔记工具 — 读取/搜索/写入/编辑。

写入走 Webhook API（仅需 webhook key，兼容性最好，来自 xianminx/mcp-server-flomo
和 chatmcp/flomo-mcp 的实现思路）。
读取/创建/编辑走 flomo 私有 API（从客户端本地存储提取 access_token，
来自 Undertone0809/flomo-local-api-skill 的实现思路）。

前置条件：
- 写入（webhook）：需先 set_secret(name="flomo_webhook_key", value="<key>")
- 读取/编辑（API）：需本机已安装并登录 flomo 客户端（macOS / Windows 均可）

跨平台支持：
- macOS 沙盒版（App Store）：~/Library/Containers/com.flomoapp.m/.../flomo/
- macOS 非沙盒版（官网下载）：~/Library/Application Support/flomo/
- Windows：%APPDATA%/flomo/（即 C:\\Users\\<user>\\AppData\\Roaming\\flomo\\）

token 提取优先级：
1. config.json 的 user.access_token（格式 id|token，最稳定）
2. LevelDB 本地存储搜索 access_token":"..."（兜底，兼容旧版客户端）
"""
from __future__ import annotations

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

from ethan.tools.base import BaseTool

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
    """从 flomo 客户端本地存储中提取 access_token。

    优先从 config.json 的 user.access_token 读取（格式 id|token，最稳定），
    兜底从 LevelDB 搜索 access_token":"..."（兼容旧版客户端）。
    """
    dirs = _flomo_data_dirs()
    if not dirs:
        raise RuntimeError(
            "未找到 flomo 客户端数据目录。请先安装并登录 flomo 客户端。\n"
            "  macOS: ~/Library/Application Support/flomo/\n"
            "  Windows: %APPDATA%/flomo/"
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


# ── Webhook 写入 ──

async def _webhook_write(content: str, webhook_key: str) -> str:
    """通过 Webhook API 写入笔记（来自 xianminx/mcp-server-flomo & chatmcp/flomo-mcp）。"""
    url = f"{_WEBHOOK_BASE}/{webhook_key}/"
    body = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

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


# ── 工具类 ──


class FlomoWriteTool(BaseTool):
    """通过 Webhook 写入 flomo 笔记。"""

    cacheable = False
    side_effect = True

    name = "flomo_write"
    description = (
        "Write a note to flomo via Webhook API. Requires flomo_webhook_key secret "
        "(get it from flomo → 设置 → API 及第三方工具 → Webhook URL, then "
        "set_secret(name='flomo_webhook_key', value='<key>')). "
        "Content supports plain text with #tags at the end. "
        "Rate limit: ~10 notes/min."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Note content in plain text. Tags at the end with # prefix (e.g. '想法 #闪念/思考').",
            },
        },
        "required": ["content"],
    }

    async def run(self, content: str) -> str:
        from ethan.tools.builtin.secrets import _secrets_dir, _slugify

        # 从 secrets 读取 webhook key
        slug = _slugify("flomo_webhook_key")
        path = _secrets_dir() / slug
        if not path.is_file():
            return (
                "✗ 未配置 flomo_webhook_key。\n"
                "请先获取 webhook key（flomo → 设置 → API 及第三方工具 → Webhook URL），\n"
                "然后用 set_secret(name='flomo_webhook_key', value='<key>') 保存。"
            )
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        prefix = "FLOMO_WEBHOOK_KEY="
        if raw.startswith(prefix):
            webhook_key = raw[len(prefix):].strip()
        else:
            webhook_key = raw

        if not webhook_key:
            return "✗ flomo_webhook_key 为空，请重新配置。"

        try:
            return await _webhook_write(content, webhook_key)
        except Exception as e:
            return f"✗ 写入失败: {e}"


class FlomoQueryTool(BaseTool):
    """搜索/查询 flomo 笔记（通过本地 API）。"""

    cacheable = False
    side_effect = False

    name = "flomo_query"
    description = (
        "Query/search flomo memos by keyword, tag, or date range. "
        "Requires flomo desktop app installed and logged in (macOS / Windows). "
        "Returns matching memos with slug, URL, tags, and content snippet."
    )
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "Search keyword (case-insensitive)."},
            "tag": {"type": "string", "description": "Filter by tag (e.g. '闪念/思考')."},
            "days": {"type": "integer", "description": "Only show memos from last N days."},
            "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
            "end_date": {"type": "string", "description": "End date YYYY-MM-DD."},
            "limit": {"type": "integer", "description": "Max results.", "default": 20},
        },
        "required": [],
    }

    async def run(
        self,
        keyword: str = "",
        tag: str = "",
        days: int = 0,
        start_date: str = "",
        end_date: str = "",
        limit: int = 20,
    ) -> str:
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


class FlomoTagsTool(BaseTool):
    """列出 flomo 标签及频率。"""

    cacheable = False
    side_effect = False

    name = "flomo_tags"
    description = (
        "List flomo tags with usage counts. Useful before creating/editing memos "
        "to reuse existing tags. Requires flomo desktop app installed and logged in (macOS / Windows)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prefix": {"type": "string", "description": "Filter tags by prefix (e.g. '闪念')."},
            "days": {"type": "integer", "description": "Only count tags from last N days."},
            "limit": {"type": "integer", "description": "Max tags to return.", "default": 50},
        },
        "required": [],
    }

    async def run(self, prefix: str = "", days: int = 0, limit: int = 50) -> str:
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


class FlomoCreateTool(BaseTool):
    """通过 API 创建 flomo 笔记（返回完整 memo 对象）。"""

    cacheable = False
    side_effect = True

    name = "flomo_create"
    description = (
        "Create a flomo memo via local API (requires flomo desktop app logged in, macOS / Windows). "
        "Returns the full memo object including slug and URL. "
        "Prefer flomo_tags first to reuse existing tags. "
        "Use plain text — flomo does not render Markdown."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Memo content in plain text. Tags at the end with # prefix.",
            },
        },
        "required": ["content"],
    }

    async def run(self, content: str) -> str:
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
            return f"✗ 创建失败: {e}\n  （创建需本机已安装并登录 flomo 客户端，或用 flomo_write 走 webhook）"


class FlomoEditTool(BaseTool):
    """编辑已有 flomo 笔记。"""

    cacheable = False
    side_effect = True

    name = "flomo_edit"
    description = (
        "Edit an existing flomo memo by slug or memo URL. "
        "Requires flomo desktop app installed and logged in (macOS / Windows). "
        "Preserves the original memo's files and pin state, only updates text content."
    )
    parameters = {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "Memo slug or flomo memo URL (https://v.flomoapp.com/mine/?memo_id=...).",
            },
            "content": {
                "type": "string",
                "description": "Updated memo content in plain text. Tags at the end with # prefix.",
            },
        },
        "required": ["slug", "content"],
    }

    async def run(self, slug: str, content: str) -> str:
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
