"""knowledge 路由：知识库 CRUD。"""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .deps import verify_token

router = APIRouter(prefix="/knowledge")

_knowledge_manager = None


def get_knowledge_manager():
    global _knowledge_manager
    if _knowledge_manager is None:
        from ethan.core.config import CONFIG_DIR
        from ethan.knowledge.base import FilesystemKnowledgeBase
        _knowledge_manager = FilesystemKnowledgeBase(CONFIG_DIR / "knowledge")
    return _knowledge_manager


@router.get("", dependencies=[Depends(verify_token)])
async def get_knowledge(q: str = None, mode: str = "keyword"):
    manager = get_knowledge_manager()
    if q:
        items = await manager.semantic_search(q) if mode == "semantic" else manager.search(q)
    else:
        items = manager.list_all()
    return {"items": [{"title": i.title, "content": i.snippet(), "source": i.source, "tags": i.tags} for i in items]}


@router.get("/search", dependencies=[Depends(verify_token)])
async def search_knowledge(q: str, limit: int = 10, semantic: bool = True):
    manager = get_knowledge_manager()
    results = await manager.semantic_search(q, limit=limit) if semantic else manager.search(q, limit=limit)
    return {"results": [{"source": r.source, "title": r.title, "content": r.content[:500], "tags": r.tags, "score": None} for r in results]}


class KnowledgeAddRequest(BaseModel):
    title: str
    content: str
    tags: list[str] | None = None


@router.post("", dependencies=[Depends(verify_token)])
async def add_knowledge(req: KnowledgeAddRequest):
    manager = get_knowledge_manager()
    source = manager.add(title=req.title, content=req.content, tags=req.tags)
    return {"ok": True, "source": source}


class KnowledgeUpdateRequest(BaseModel):
    title: str
    content: str
    tags: list[str] | None = None


@router.put("/{source:path}", dependencies=[Depends(verify_token)])
async def update_knowledge(source: str, req: KnowledgeUpdateRequest):
    manager = get_knowledge_manager()
    if not manager.get(source):
        raise HTTPException(404, "Knowledge item not found")
    manager.update(source, title=req.title, content=req.content, tags=req.tags)
    return {"ok": True}


@router.delete("/{source:path}", dependencies=[Depends(verify_token)])
async def delete_knowledge(source: str):
    manager = get_knowledge_manager()
    item = manager.get(source)
    if not item:
        raise HTTPException(404, "Knowledge item not found")
    try:
        Path(item.source).unlink()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Failed to delete: {e}")
