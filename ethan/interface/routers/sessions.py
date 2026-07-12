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


@router.get("/modes")
async def list_modes(user_id: str = Depends(verify_token)):
    """返回可用对话模式表，供前端渲染切换 UI（数据驱动，不在前端硬编码人格）。"""
    from ethan.core.modes import DEFAULT_MODE, MODES
    return {"modes": [
        {"key": m.key, "label": m.label, "icon": m.icon, "accent": m.accent, "blurb": m.blurb}
        for m in (DEFAULT_MODE, *MODES)
    ]}


@router.get("/sessions")
async def list_sessions(limit: int = 50, offset: int = 0, q: str | None = None,
                        source: str | None = None, mode: str | None = None,
                        hide_heartbeat: bool = False, hide_scheduled: bool = False,
                        user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    if q:
        sessions = await store.search(q, limit)
    else:
        exclude_prefixes = []
        if hide_heartbeat:
            exclude_prefixes.append("[心跳]")
        if hide_scheduled:
            exclude_prefixes.append("[定时]")
        sessions = await store.list_recent(limit, offset, source=source or "", mode=mode,
                                           exclude_title_prefixes=exclude_prefixes or None)
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
            "mode": getattr(s, "mode", "") or "",
        }
        for s in sessions
    ]}


@router.post("/sessions")
async def create_session(model: str | None = None, mode: str | None = None, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    config = get_config()
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    session = await store.create(model or config.defaults.model, mode=mode or "")
    await store.close()
    return {"id": session.id, "title": session.title, "model": session.model, "mode": session.mode}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    session = await store.load(session_id)
    await store.close()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    from ethan.core.run_manager import RunManager
    return {
        "id": session.id,
        "title": session.title,
        "model": session.model,
        "source": getattr(session, "source", "web"),
        "mode": getattr(session, "mode", "") or "",
        # 该会话是否有正在进行的生成（producer 未结束）。前端据此决定刷新后重连流。
        # 此处 session 已从当前用户的 store 取到（归属已确认），仍传 user_id 做纵深防御。
        "active_run": RunManager.instance().has_active(session_id, user_id=user_id),
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": getattr(m, "created_at", None),
                "usage": getattr(m, "usage", None),
                "tool_steps": getattr(m, "tool_steps", None) or [],
                "quote": getattr(m, "quote", None),
                "a2ui": getattr(m, "a2ui", None),
                "images": getattr(m, "images", None) or [],
                "matched_skills": getattr(m, "matched_skills", None),
                "ttfb_ms": getattr(m, "ttfb_ms", None),
                "total_ms": getattr(m, "total_ms", None),
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
    # 会话删除时清除其授权记忆，避免内存泄漏 + 同 id 复用时残留旧授权
    from ethan.core.consent import clear_session_grants
    clear_session_grants(session_id)
    return {"ok": True}


class RenameSessionRequest(BaseModel):
    title: str | None = None
    mode: str | None = None


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, req: RenameSessionRequest, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    try:
        if req.title is not None:
            title = req.title.strip()
            if not title:
                raise HTTPException(status_code=400, detail="Title cannot be empty")
            await store.update_title(session_id, title)
        # mode 可为空字符串（切回默认模式），故用 is not None 判断
        if req.mode is not None:
            await store.update_mode(session_id, req.mode)
    finally:
        await store.close()
    return {"ok": True}


@router.post("/sessions/{session_id}/compact")
async def compact_session(session_id: str, user_id: str = Depends(verify_token)):
    """压缩会话历史：用廉价模型把旧对话压成摘要替换存储，保留最近一轮，释放上下文。

    供 Web 的 /compact 命令调用。返回 {ok, summary}，前端拿 summary 回显并刷新会话。
    """
    from ethan.core.paths import user_sessions_db_path
    from ethan.core.session_ops import compact_session as _compact
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    try:
        summary = await _compact(store, session_id, get_config().defaults.model)
    finally:
        await store.close()
    return {"ok": True, "summary": summary}
