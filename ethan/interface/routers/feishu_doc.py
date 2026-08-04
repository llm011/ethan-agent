"""浏览器扩展调用：读取飞书文档完整内容（绕开网页虚拟滚动）。"""
from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .deps import verify_token_or_cookie

log = logging.getLogger(__name__)
router = APIRouter(prefix="/feishu-doc")


# ── 输入输出 schema ────────────────────────────────────────────────────

class FetchDocRequest(BaseModel):
    url: str
    nocache: bool = False


class FetchDocResponse(BaseModel):
    ok: bool
    markdown: str = ""
    title: str = ""
    url: str = ""
    length: int = 0
    cached: bool = False
    age_seconds: float = 0.0
    error: str | None = None


# ── server 端内存级缓存（与 skill 里的 /tmp 缓存并行，减少重复子进程开销）─
_CACHE: dict[str, tuple[str, str, str, float]] = {}  # key -> (markdown, title, url, mtime)
_CACHE_MAX_AGE = 24 * 3600


def _is_feishu_doc_url(url: str) -> bool:
    if not url:
        return False
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return False
        host = p.netloc.lower()
        if not (host.endswith("feishu.cn") or host.endswith("larksuite.com") or host.endswith("feishu.net")):
            return False
        # 只处理云文档路径：/docx/xxx, /wiki/xxx, /doc/xxx, /base/xxx 不处理
        path = p.path or ""
        parts = [s for s in path.split("/") if s]
        if not parts:
            return False
        doc_prefixes = {"docx", "wiki", "doc", "docs"}
        # 允许 /docs/xxx，也允许 /docx/xxx，/wiki/xxx
        # URL 像 "https://xxx.feishu.cn/docx/TOKEN" parts=[docx, TOKEN]
        # URL 像 "https://xxx.feishu.cn/wiki/TOKEN" parts=[wiki, TOKEN]
        return parts[0] in doc_prefixes
    except Exception:
        return False


def _fetch_feishu_doc_impl(url: str, nocache: bool) -> FetchDocResponse:
    """同步实现（lark-cli 是 subprocess 阻塞调用，因此用 to_thread 外包 async）。"""
    if not _is_feishu_doc_url(url):
        raise HTTPException(status_code=400, detail="not a feishu doc url")

    now = time.time()
    cache_key = url
    if not nocache:
        cached = _CACHE.get(cache_key)
        if cached and (now - cached[3]) < _CACHE_MAX_AGE:
            md, title, _u, mtime = cached
            return FetchDocResponse(
                ok=True,
                markdown=md,
                title=title,
                url=_u,
                length=len(md),
                cached=True,
                age_seconds=now - mtime,
            )

    # 调用 skill：ethan/defaults/skills/lark-doc/scripts/fetch_doc.py 内 fetch_doc_to_markdown
    # 注意目录名「lark-doc」含连字符，不符合 Python 包命名规范，改用 importlib 从文件路径加载。
    import importlib.util
    from pathlib import Path
    _root = Path(__file__).resolve().parents[3]
    _script_path = _root / "defaults" / "skills" / "lark-doc" / "scripts" / "fetch_doc.py"
    if not _script_path.exists():
        raise RuntimeError(f"fetch_doc.py not found at {_script_path}")
    _spec = importlib.util.spec_from_file_location("_ethan_fetch_doc_mod", str(_script_path))
    if _spec is None or _spec.loader is None:
        raise RuntimeError(f"failed to build spec for {_script_path}")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    fetch_doc_to_markdown = getattr(_mod, "fetch_doc_to_markdown")
    _doc_token_from_input = getattr(_mod, "_doc_token_from_input", lambda s: s)

    # fetch_doc_to_markdown 内部已经有自己的缓存；这里再套一层内存级缓存。
    try:
        md, meta, _out = fetch_doc_to_markdown(url, use_cache=not nocache)
    except Exception as e:
        log.exception("feishu-doc fetch failed for %s", url)
        return FetchDocResponse(ok=False, error=f"{type(e).__name__}: {e}"[:500], url=url)

    title = (meta.get("title") if isinstance(meta, dict) else "") or _extract_title(md) or _doc_token_from_input(url)
    _CACHE[cache_key] = (md, title, url, now)
    return FetchDocResponse(
        ok=True,
        markdown=md,
        title=title,
        url=url,
        length=len(md),
        cached=False,
        age_seconds=0.0,
    )


def _extract_title(md: str) -> str:
    if not md:
        return ""
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
        if s:
            break
    return ""


@router.post("/fetch", response_model=FetchDocResponse)
async def fetch_doc_api(
    req: FetchDocRequest,
    request: Request,
    _user: str = Depends(verify_token_or_cookie),
) -> FetchDocResponse:
    """浏览器扩展对当前飞书文档页调用，一次性拿到全文 Markdown。

    - 优先走内存缓存（24h），其次走 skill 自带的磁盘缓存；
    - ?nocache=true 重抓；
    - 非飞书云文档 URL 直接 400。
    """
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="missing url")
    try:
        return await asyncio.to_thread(_fetch_feishu_doc_impl, url, bool(req.nocache))
    except HTTPException:
        raise
    except Exception as e:
        log.exception("feishu-doc fetch failed for %s", url)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}"[:500]) from e


__all__ = ["router"]
