"""sessions 路由：Session CRUD + /auth + /models。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ethan.core.config import get_config
from ethan.memory.session import SessionStore
from .deps import verify_token

router = APIRouter()


class AuthRequest(BaseModel):
    token: str


@router.post("/auth")
async def auth(req: AuthRequest):
    from ethan.core.users import get_user_store
    user_store = get_user_store()
    user_id = user_store.resolve_web_token(req.token)

    if user_id is None:
        # 兼容旧 auth_token → admin
        config = get_config()
        if not config.network.auth_token:
            return {"ok": True, "user_id": user_store.get_admin_user_id(), "user_name": "", "is_admin": True}
        if req.token == config.network.auth_token:
            user_id = user_store.get_admin_user_id()
        else:
            raise HTTPException(status_code=401, detail="Invalid token")

    user = user_store.get_user(user_id)
    return {
        "ok": True,
        "user_id": user_id,
        "user_name": user.name if user else "",
        "is_admin": user.is_admin if user else False,
    }


@router.get("/models", dependencies=[Depends(verify_token)])
async def list_models():
    config = get_config()
    return {"models": [m.model_dump() for m in config.models]}


@router.get("/sessions")
async def list_sessions(limit: int = 50, offset: int = 0, q: str | None = None, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    if q:
        sessions = await store.search(q, limit, offset)
    else:
        sessions = await store.list_recent(limit, offset)
    await store.close()
    return {"sessions": [
        {
            "id": s.id,
            "title": s.title,
            "model": s.model,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "snippet": getattr(s, "snippet", None),
            "source": getattr(s, "source", "web"),
        }
        for s in sessions
    ]}


@router.post("/sessions")
async def create_session(model: str | None = None, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    config = get_config()
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    session = await store.create(model or config.defaults.model)
    await store.close()
    return {"id": session.id, "title": session.title, "model": session.model}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    session = await store.load(session_id)
    await store.close()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "title": session.title,
        "model": session.model,
        "source": getattr(session, "source", "web"),
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": getattr(m, "created_at", None),
                "usage": getattr(m, "usage", None),
                "tool_steps": getattr(m, "tool_steps", None) or [],
            }
            for m in session.messages if m.role in ("user", "assistant")
        ],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    ok = await store.delete(session_id)
    await store.close()
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


class RenameSessionRequest(BaseModel):
    title: str


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, req: RenameSessionRequest, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    await store.update_title(session_id, title)
    await store.close()
    return {"ok": True}
