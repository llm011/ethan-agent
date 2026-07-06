"""knowledge 路由：知识库 CRUD（per-user 隔离）。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import verify_token

router = APIRouter(prefix="/knowledge")

# per-user 知识库管理器缓存（user_id → FilesystemKnowledgeBase）
_knowledge_managers: dict[str, "object"] = {}


def get_knowledge_manager(user_id: str):
    from ethan.core.paths import user_knowledge_dir
    from ethan.knowledge.base import FilesystemKnowledgeBase
    if user_id not in _knowledge_managers:
        _knowledge_managers[user_id] = FilesystemKnowledgeBase(user_knowledge_dir())
    return _knowledge_managers[user_id]


@router.get("")
async def get_knowledge(q: str = None, mode: str = "keyword", user_id: str = Depends(verify_token)):
    manager = get_knowledge_manager(user_id)
    if q:
        items = await manager.semantic_search(q) if mode == "semantic" else manager.search(q)
    else:
        items = manager.list_all()
    # 返回完整 content（含换行）。web 详情面板按 markdown 渲染需要原始换行；
    # 用 snippet() 会被 \s+→空格 压成一行，导致前端看不到任何换行。侧边栏只显示标题/标签，
    # 不展示正文，故返回全文无副作用。
    return {"items": [{"title": i.title, "content": i.content, "source": i.source, "tags": i.tags} for i in items]}


@router.get("/search")
async def search_knowledge(q: str, limit: int = 10, semantic: bool = True, user_id: str = Depends(verify_token)):
    manager = get_knowledge_manager(user_id)
    results = await manager.semantic_search(q, limit=limit) if semantic else manager.search(q, limit=limit)
    return {"results": [{"source": r.source, "title": r.title, "content": r.content[:500], "tags": r.tags, "score": None} for r in results]}


class KnowledgeAddRequest(BaseModel):
    title: str
    content: str
    tags: list[str] | None = None


@router.post("")
async def add_knowledge(req: KnowledgeAddRequest, user_id: str = Depends(verify_token)):
    manager = get_knowledge_manager(user_id)
    source = manager.add(title=req.title, content=req.content, tags=req.tags)
    return {"ok": True, "source": source}


class KnowledgeUpdateRequest(BaseModel):
    title: str
    content: str
    tags: list[str] | None = None


@router.put("/{source:path}")
async def update_knowledge(source: str, req: KnowledgeUpdateRequest, user_id: str = Depends(verify_token)):
    manager = get_knowledge_manager(user_id)
    if not manager.get(source):
        raise HTTPException(404, "Knowledge item not found")
    manager.update(source, title=req.title, content=req.content, tags=req.tags)
    return {"ok": True}


@router.delete("/{source:path}")
async def delete_knowledge(source: str, user_id: str = Depends(verify_token)):
    manager = get_knowledge_manager(user_id)
    item = manager.get(source)
    if not item:
        raise HTTPException(404, "Knowledge item not found")
    try:
        Path(item.source).unlink()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Failed to delete: {e}")
