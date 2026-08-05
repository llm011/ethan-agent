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

# ── fetch_doc.py 模块懒加载（用户安装目录优先，仓库内 fallback）──────────────
# 用户安装路径：~/.ethan/skills/lark-doc/scripts/fetch_doc.py（可被 skill update 更新）
# 仓库内路径：ethan/defaults/skills/lark-doc/scripts/fetch_doc.py（feishu_doc.py 在
#   ethan/interface/routers/，parents[2] 才是 ethan/ 包根，旧代码误用 parents[3]
#   导致路径算到仓库根，脚本永远找不到）
_FETCH_DOC_MOD = None


def _load_fetch_doc_module():
    """懒加载 lark-doc skill 的 fetch_doc.py。

    优先用户安装目录（与 skill loader 同源，能拿到 update 后的版本），
    fallback 仓库内 defaults/skills/lark-doc/scripts/fetch_doc.py。
    目录名含连字符不符合 Python 包命名规范，故用 importlib 按文件路径加载。
    """
    global _FETCH_DOC_MOD
    if _FETCH_DOC_MOD is not None:
        return _FETCH_DOC_MOD

    import importlib.util
    from pathlib import Path

    from ethan.core.paths import user_skills_dir

    candidates = [
        user_skills_dir() / "lark-doc" / "scripts" / "fetch_doc.py",
        Path(__file__).resolve().parents[2] / "defaults" / "skills" / "lark-doc" / "scripts" / "fetch_doc.py",
    ]
    script_path = next((p for p in candidates if p.is_file()), None)
    if script_path is None:
        raise RuntimeError(f"fetch_doc.py not found; tried: {[str(c) for c in candidates]}")

    spec = importlib.util.spec_from_file_location("_ethan_fetch_doc_mod", str(script_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to build spec for {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _FETCH_DOC_MOD = mod
    log.info("feishu-doc: loaded fetch_doc.py from %s", script_path)
    return mod


_FEISHU_HOST_SUFFIXES = ("feishu.cn", "larksuite.com", "feishu.net", "larkoffice.com")


def _is_feishu_doc_url(url: str) -> bool:
    if not url:
        return False
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return False
        host = p.netloc.lower()
        if not any(host.endswith(s) for s in _FEISHU_HOST_SUFFIXES):
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

    _mod = _load_fetch_doc_module()
    fetch_doc_to_markdown = getattr(_mod, "fetch_doc_to_markdown")
    _doc_token_from_input = getattr(_mod, "_doc_token_from_input", lambda s: s)

    # fetch_doc_to_markdown 内部已经有自己的缓存；这里再套一层内存级缓存。
    try:
        md, meta, _out = fetch_doc_to_markdown(url, use_cache=not nocache)
    except Exception as e:
        log.exception("feishu-doc fetch failed for %s", url)
        return FetchDocResponse(ok=False, error=f"{type(e).__name__}: {e}"[:500], url=url)

    title = (meta.get("title") if isinstance(meta, dict) else "") or _extract_title(md) or _doc_token_from_input(url)
    # 清理过期条目，防止 _CACHE 无限增长
    expired = [k for k, v in _CACHE.items() if now - v[3] > _CACHE_MAX_AGE]
    for k in expired:
        del _CACHE[k]
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
