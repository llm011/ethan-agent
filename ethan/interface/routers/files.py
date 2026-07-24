"""Files 路由 — 本地生成文件（pptx 等）的下载与 deck 预览数据。

deliver_file 工具把文件路径写进消息卡片，前端点击卡片后通过本路由：
  /api/files/download?path=...  → 直接下载文件（Content-Disposition: attachment）
  /api/files/deck?path=...      → pptx 项目目录的 deck.json + pages/*.json（预览页数据源）
  /api/files/asset?path=...     → 项目 assets/ 里的图片（<img> 标签用）

安全（双层）：
  1. path 经 resolve 后必须落在 home 或 /tmp 下（与 deliver_file 工具同一 jail）；
  2. session 隔离——必须带 session_id，且该 session 的消息卡片里确实交付过这个文件
     （授权派生自已持久化的 cards 列，无额外状态，重启不丢）。
鉴权：download/asset 走 cookie/签名 URL 双通道（浏览器直链无法带 header，签名由
  POST /files/sign 用 Bearer 换发，10 分钟有效，见 ethan.core.signed_url），deck 走 Bearer。
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ethan.core.file_jail import ASSET_EXTS, DELIVER_EXTS, is_project_dir, resolve_jailed
from ethan.core.signed_url import sign_path
from ethan.interface.routers.deps import verify_token, verify_token_or_cookie

router = APIRouter(prefix="/files")


class SignRequest(BaseModel):
    paths: list[str] = Field(max_length=100)


@router.post("/sign")
async def sign_files(req: SignRequest, user_id: str = Depends(verify_token)):
    """把 path 批量换成短期签名（浏览器直链用），返回 {path: "exp.sig"}。

    只签 jail 内的路径；签名只替代认证，session 交付授权仍在下载时独立校验。
    """
    signatures = {}
    for path in req.paths:
        if resolve_jailed(path) is not None:
            signatures[path] = sign_path(user_id, path)
    return {"user": user_id, "signatures": signatures}


def _resolve_jailed(path: str) -> Path:
    """共享 jail（ethan.core.file_jail.resolve_jailed），不合法时按 HTTP 语义报错。"""
    p = resolve_jailed(path)
    if p is not None:
        return p
    # 区分 400（路径解析失败）与 403（合法路径但在 jail 外）
    try:
        Path(path).expanduser().resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    raise HTTPException(status_code=403, detail="path outside allowed roots")


async def _session_grants(session_id: str) -> tuple[set[str], set[str]]:
    """该 session 交付过的 (文件 resolved path 集合, 项目目录 resolved path 集合)。

    数据源是 messages 表持久化的 file 卡片——只有 deliver_file 工具能写这种卡片，
    所以"卡片在"="这个对话框交付过"，天然按 session（且按 user，库是 per-user 的）隔离。
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    from ethan.memory.session import get_session_store

    store = await get_session_store()
    cards = await store.load_session_cards(session_id)  # 只取 cards 列，不全量 load 会话
    if cards is None:
        raise HTTPException(status_code=403, detail="file not delivered in this session")
    files: set[str] = set()
    dirs: set[str] = set()
    for c in cards:
        if c.get("type") != "file":
            continue
        try:
            if c.get("path"):
                files.add(str(Path(c["path"]).expanduser().resolve()))
            if c.get("project_dir"):
                dirs.add(str(Path(c["project_dir"]).expanduser().resolve()))
        except Exception:
            continue
    return files, dirs


def _project_dir_of(p: Path) -> Path:
    """传 pptx 取其父目录，传目录直接用；必须满足 deck 项目布局（共享 is_project_dir）。"""
    d = p.parent if p.is_file() else p
    if not is_project_dir(d):
        raise HTTPException(status_code=404, detail="not a deck project (need deck.json + pages/)")
    return d


@router.get("/download", dependencies=[Depends(verify_token_or_cookie)])
async def download_file(path: str, session_id: str = ""):
    p = _resolve_jailed(path)
    granted_files, _ = await _session_grants(session_id)
    if str(p) not in granted_files:
        raise HTTPException(status_code=403, detail="file not delivered in this session")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if p.suffix.lower() not in DELIVER_EXTS:
        raise HTTPException(status_code=400, detail="unsupported file type")
    return FileResponse(p, filename=p.name, content_disposition_type="attachment")


def _page_sort_key(f: Path) -> tuple[int, int, str]:
    """页面文件排序：按文件名前导数字排（容忍未补零的 1_, 10_），无前导数字的排最后。"""
    m = re.match(r"(\d+)", f.name)
    return (0, int(m.group(1)), f.name) if m else (1, 0, f.name)


def _read_deck_files(d: Path) -> tuple[dict, list[dict]]:
    """同步读 deck.json + pages/*.json（在 worker 线程里跑，不阻塞事件循环）。"""
    deck = json.loads((d / "deck.json").read_text(encoding="utf-8"))
    pages = []
    for f in sorted((d / "pages").glob("*.json"), key=_page_sort_key):
        try:
            pages.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue  # 单页损坏不阻塞整个预览
    return deck, pages


@router.get("/deck", dependencies=[Depends(verify_token)])
async def get_deck(path: str, session_id: str = ""):
    """返回 deck 项目的全部页面 JSON，供 /ppt-preview 前端渲染。"""
    p = _resolve_jailed(path)
    # 先授权后探测文件系统——与 download/asset 一致，未授权一律 403，不暴露目录存在性
    _, granted_dirs = await _session_grants(session_id)
    d = p.parent if p.is_file() else p
    if str(d.resolve()) not in granted_dirs:
        raise HTTPException(status_code=403, detail="deck not delivered in this session")
    d = _project_dir_of(p)
    try:
        deck, pages = await asyncio.to_thread(_read_deck_files, d)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"bad deck.json: {e}")
    # pptx_path 用实际交付（且已授权）的那个文件，而不是按目录名猜——
    # 猜出来的 <dirname>.pptx 可能不在 granted_files 里，下载必 403
    pptx_path = str(p) if p.suffix.lower() == ".pptx" and p.is_file() else None
    return {
        "name": d.name,
        "dir": str(d),
        "deck": deck,
        "pages": pages,
        "page_count": len(pages),
        "pptx_path": pptx_path,
    }


@router.get("/asset", dependencies=[Depends(verify_token_or_cookie)])
async def get_asset(path: str, session_id: str = ""):
    """项目 assets/ 下的图片，<img src> 直链（cookie 鉴权）。"""
    p = _resolve_jailed(path)
    _, granted_dirs = await _session_grants(session_id)
    if p.parent.name != "assets" or str(p.parent.parent) not in granted_dirs:
        raise HTTPException(status_code=403, detail="asset not delivered in this session")
    if not p.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    if p.suffix.lower() not in ASSET_EXTS:
        raise HTTPException(status_code=400, detail="unsupported asset type")
    return FileResponse(p)
