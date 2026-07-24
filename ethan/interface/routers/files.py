"""Files 路由 — 本地生成文件（pptx 等）的下载与 deck 预览数据。

deliver_file 工具把文件路径写进消息卡片，前端点击卡片后通过本路由：
  /api/files/download?path=...  → 直接下载文件（Content-Disposition: attachment）
  /api/files/deck?path=...      → pptx 项目目录的 deck.json + pages/*.json（预览页数据源）
  /api/files/asset?path=...     → 项目 assets/ 里的图片（<img> 标签用）

安全：所有 path 经 resolve 后必须落在 home 或 /tmp 下（与 deliver_file 工具同一 jail）。
鉴权：download/asset 走 cookie 双通道（浏览器直链无法带 header），deck 走 Bearer。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ethan.interface.routers.deps import verify_token, verify_token_or_cookie

router = APIRouter(prefix="/files")

_DOWNLOAD_EXTS = {".pptx", ".pdf", ".docx", ".xlsx", ".csv", ".zip", ".md", ".html"}
_ASSET_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


def _resolve_jailed(path: str) -> Path:
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    home = Path.home().resolve()
    tmp = Path("/tmp").resolve()  # macOS 上 /tmp 是 /private/tmp 的软链，resolve 后再比
    if not (p.is_relative_to(home) or p.is_relative_to(tmp)):
        raise HTTPException(status_code=403, detail="path outside allowed roots")
    return p


def _project_dir_of(p: Path) -> Path:
    """传 pptx 取其父目录，传目录直接用；必须含 deck.json + pages/。"""
    d = p.parent if p.is_file() else p
    if not (d / "deck.json").is_file() or not (d / "pages").is_dir():
        raise HTTPException(status_code=404, detail="not a deck project (need deck.json + pages/)")
    return d


@router.get("/download", dependencies=[Depends(verify_token_or_cookie)])
async def download_file(path: str):
    p = _resolve_jailed(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if p.suffix.lower() not in _DOWNLOAD_EXTS:
        raise HTTPException(status_code=400, detail="unsupported file type")
    return FileResponse(p, filename=p.name, content_disposition_type="attachment")


@router.get("/deck", dependencies=[Depends(verify_token)])
async def get_deck(path: str):
    """返回 deck 项目的全部页面 JSON，供 /ppt-preview 前端渲染。"""
    d = _project_dir_of(_resolve_jailed(path))
    try:
        deck = json.loads((d / "deck.json").read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"bad deck.json: {e}")
    pages = []
    for f in sorted((d / "pages").glob("*.json")):
        try:
            pages.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue  # 单页损坏不阻塞整个预览
    pptx = d / f"{d.name}.pptx"
    return {
        "name": d.name,
        "dir": str(d),
        "deck": deck,
        "pages": pages,
        "page_count": len(pages),
        "pptx_path": str(pptx) if pptx.is_file() else None,
    }


@router.get("/asset", dependencies=[Depends(verify_token_or_cookie)])
async def get_asset(path: str):
    """项目 assets/ 下的图片，<img src> 直链（cookie 鉴权）。"""
    p = _resolve_jailed(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    if p.suffix.lower() not in _ASSET_EXTS:
        raise HTTPException(status_code=400, detail="unsupported asset type")
    if p.parent.name != "assets":
        raise HTTPException(status_code=403, detail="only files under assets/ are served")
    return FileResponse(p)
