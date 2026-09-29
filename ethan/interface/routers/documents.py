"""documents 路由：文档库的文件树、内容读取、收藏/置顶、来源对话定位。

与 /docs（项目自身文档站）区分：本路由管理的是用户/Agent 产出的文档，
存储在 ~/.ethan/documents/。
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ethan.documents.library import (
    DOC_EXTS,
    Library,
    build_file_tree,
    count_documents,
    ensure_root,
    list_flat,
    resolve_in_root,
)

from .deps import verify_token

router = APIRouter(prefix="/documents")


@router.get("/tree")
async def get_tree(user_id: str = Depends(verify_token)):
    """文档库文件树。前端据此渲染层级列表 + 顶部文件数。"""
    ensure_root()
    nodes = build_file_tree()
    return {"tree": [n.to_dict() for n in nodes], "total": count_documents(nodes)}


@router.get("/recent")
async def get_recent(limit: int = 20, user_id: str = Depends(verify_token)):
    """最近修改的文档，平铺（供「最近」视图）。"""
    ensure_root()
    return {"items": [n.to_dict() for n in list_flat(limit=limit)]}


@router.get("")
async def get_document(path: str, user_id: str = Depends(verify_token)):
    """读取单个文档的正文。

    与 /files/download 的差异：那条通道依赖「该 session 交付过此文件」的授权，
    文档库里的文件不属于任何单个会话，故走独立的根目录 jail 校验。
    """
    target = resolve_in_root(path)
    if target is None or not target.is_file():
        raise HTTPException(404, "Document not found")
    if target.suffix.lower() not in DOC_EXTS:
        raise HTTPException(400, "Unsupported document type")
    rel = path.replace("\\", "/")
    meta = Library().get(rel)
    try:
        content = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # 二进制类文档（pdf/docx）不做文本读取，交给前端走下载
        raise HTTPException(415, "Document is not text-readable")
    return {
        "path": rel,
        "title": meta.title or target.name,
        "content": content,
        "favorite": meta.favorite,
        "pinned": meta.pinned,
        "session_id": meta.session_id,
        "message_id": meta.message_id,
        "size_kb": round(target.stat().st_size / 1024, 1),
    }


@router.get("/download")
async def download_document(path: str, user_id: str = Depends(verify_token)):
    """下载文档（二进制类型如 pdf/docx 的唯一出口）。"""
    target = resolve_in_root(path)
    if target is None or not target.is_file():
        raise HTTPException(404, "Document not found")
    return FileResponse(target, filename=target.name)


class MetaUpdate(BaseModel):
    favorite: bool | None = None
    pinned: bool | None = None
    title: str | None = None
    session_id: str | None = None
    message_id: int | None = None


@router.patch("")
async def update_meta(path: str, req: MetaUpdate, user_id: str = Depends(verify_token)):
    """更新文档元数据（收藏 / 置顶 / 关联对话）。"""
    target = resolve_in_root(path)
    if target is None or not target.is_file():
        raise HTTPException(404, "Document not found")
    rel = path.replace("\\", "/")
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    meta = Library().update(rel, **fields)
    return {"ok": True, "meta": meta.to_dict()}


class MoveRequest(BaseModel):
    path: str
    new_path: str


@router.post("/move")
async def move_document(req: MoveRequest, user_id: str = Depends(verify_token)):
    """移动/重命名文档，并跟随迁移元数据（收藏不丢）。"""
    src = resolve_in_root(req.path)
    dst = resolve_in_root(req.new_path)
    if src is None or dst is None:
        raise HTTPException(400, "Invalid path")
    if not src.is_file():
        raise HTTPException(404, "Document not found")
    if dst.exists():
        raise HTTPException(409, "Target already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    old_rel = req.path.replace("\\", "/")
    new_rel = req.new_path.replace("\\", "/")
    Library().rename(old_rel, new_rel)
    return {"ok": True, "path": new_rel}


@router.delete("")
async def delete_document(path: str, user_id: str = Depends(verify_token)):
    target = resolve_in_root(path)
    if target is None or not target.is_file():
        raise HTTPException(404, "Document not found")
    target.unlink()
    Library().remove(path.replace("\\", "/"))
    return {"ok": True}


@router.get("/root")
async def get_root_info(user_id: str = Depends(verify_token)):
    """文档库根目录信息（设置页展示用）。"""
    root = ensure_root()
    return {"root": str(root), "exists": root.is_dir()}
