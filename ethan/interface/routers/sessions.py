"""sessions 路由：Session CRUD + /auth + /models。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ethan.core.config import get_config
from ethan.memory.session import get_session_store

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
                        title_prefixes: str | None = None,
                        has_images: bool = False,
                        user_id: str = Depends(verify_token)):
    store = await get_session_store()
    if q:
        sessions = await store.search(q, limit)
        total = await store.count_search(q)
    else:
        exclude_prefixes = []
        if hide_heartbeat:
            exclude_prefixes.append("[心跳]")
        if hide_scheduled:
            exclude_prefixes.append("[定时]")
        include_prefixes = [p for p in (title_prefixes or "").split(",") if p] or None
        sessions = await store.list_recent(limit, offset, source=source or "", mode=mode,
                                           exclude_title_prefixes=exclude_prefixes or None,
                                           include_title_prefixes=include_prefixes,
                                           has_images=has_images)
        total = getattr(sessions, "total", len(sessions))
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
            "pinned_at": getattr(s, "pinned_at", 0) or 0,
            "last_read_at": getattr(s, "last_read_at", 0) or 0,
        }
        for s in sessions
    ], "total": total}


@router.post("/sessions")
async def create_session(model: str | None = None, mode: str | None = None, source: str | None = None, user_id: str = Depends(verify_token)):
    config = get_config()
    store = await get_session_store()
    session = await store.create(model or config.defaults.model, source=source or "web", mode=mode or "")
    return {"id": session.id, "title": session.title, "model": session.model, "mode": session.mode, "source": session.source}


@router.get("/sessions/pinned")
async def list_pinned(user_id: str = Depends(verify_token)):
    store = await get_session_store()
    sessions = await store.list_pinned()
    return {"sessions": [
        {
            "id": s.id,
            "title": s.title,
            "model": s.model,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "source": getattr(s, "source", "web"),
            "mode": getattr(s, "mode", "") or "",
            "pinned_at": s.pinned_at,
            "last_read_at": getattr(s, "last_read_at", 0) or 0,
        }
        for s in sessions
    ]}


@router.post("/sessions/{session_id}/read")
async def mark_session_read(session_id: str, user_id: str = Depends(verify_token)):
    """标记会话已读：未读水位（last_read_at）推进到 updated_at，消除侧边栏红点。

    幂等；返回 advanced 表示本次是否有实际推进（False = 本来就已读）。
    """
    store = await get_session_store()
    advanced = await store.mark_read(session_id)
    return {"ok": True, "advanced": advanced}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user_id: str = Depends(verify_token)):
    store = await get_session_store()
    session = await store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    from ethan.core.run_manager import RunManager
    return {
        "id": session.id,
        "title": session.title,
        "model": session.model,
        "source": getattr(session, "source", "web"),
        "mode": getattr(session, "mode", "") or "",
        "pinned_at": getattr(session, "pinned_at", 0) or 0,
        # 该会话是否有正在进行的生成（producer 未结束）。前端据此决定刷新后重连流。
        # 此处 session 已从当前用户的 store 取到（归属已确认），仍传 user_id 做纵深防御。
        "active_run": RunManager.instance().has_active(session_id, user_id=user_id),
        # 运行中「补充信息」待消费队列（DB 镜像，run 结束时清空）：
        # 前端刷新后在「调用可视化」区域上方重新展示，可删除。
        "pending_injected": getattr(session, "pending_injected", None) or [],
        "messages": [
            {
                "id": getattr(m, "id", None),
                "role": m.role,
                "content": m.content,
                "created_at": getattr(m, "created_at", None),
                "usage": getattr(m, "usage", None),
                "tool_steps": getattr(m, "tool_steps", None) or [],
                "intermediate_blob_id": getattr(m, "intermediate_blob_id", 0) or 0,
                "quote": getattr(m, "quote", None),
                "a2ui": getattr(m, "a2ui", None),
                "mcp_apps": getattr(m, "mcp_apps", None),
                "cards": getattr(m, "cards", None),
                "images": [
                    {"url": f"assets/images/{img['path']}", "media_type": img.get("media_type", "image/png")}
                    if "path" in img
                    else img
                    for img in (getattr(m, "images", None) or [])
                ],
                "matched_skills": getattr(m, "matched_skills", None),
                "ttfb_ms": getattr(m, "ttfb_ms", None),
                "total_ms": getattr(m, "total_ms", None),
                "model": getattr(m, "model", None),
                "status": getattr(m, "status", "completed"),
                "error": getattr(m, "error", None) or "",
            }
            for m in session.messages if m.role in ("user", "assistant")
        ],
    }


@router.get("/sessions/{session_id}/messages/{message_id}/intermediate")
async def get_message_intermediate(session_id: str, message_id: int, user_id: str = Depends(verify_token)):
    store = await get_session_store()
    session = await store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    belongs = any(getattr(m, "id", None) == message_id for m in session.messages)
    if not belongs:
        raise HTTPException(status_code=404, detail="Message not found in this session")
    blob = await store.load_intermediate_blob(message_id)
    if not blob:
        raise HTTPException(status_code=404, detail="Intermediate blob not found")
    if blob.get("missing"):
        raise HTTPException(status_code=410, detail="Intermediate blob file missing")
    return PlainTextResponse(blob["content"], media_type="text/markdown; charset=utf-8")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str = Depends(verify_token)):
    store = await get_session_store()
    ok = await store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    # 会话删除时清除其授权记忆，避免内存泄漏 + 同 id 复用时残留旧授权
    from ethan.core.consent import clear_session_grants
    clear_session_grants(session_id)
    return {"ok": True}


@router.delete("/sessions/{session_id}/messages/{message_id}")
async def delete_message(session_id: str, message_id: int, user_id: str = Depends(verify_token)):
    """删除会话中的单条消息（从存储中物理删除，后续对话不再带上其上下文）。"""
    store = await get_session_store()
    session = await store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # 确认消息归属该会话
    belongs = any(getattr(m, "id", None) == message_id for m in session.messages)
    if not belongs:
        raise HTTPException(status_code=404, detail="Message not found in this session")
    await store.delete_message_by_id(message_id)
    await store.touch(session_id)
    return {"ok": True}


class UpdateMessageRequest(BaseModel):
    content: str


@router.patch("/sessions/{session_id}/messages/{message_id}")
async def update_message(session_id: str, message_id: int, req: UpdateMessageRequest, user_id: str = Depends(verify_token)):
    """编辑消息正文（阅读模式编辑）。后续对话上下文使用编辑后的版本。"""
    store = await get_session_store()
    session = await store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    belongs = any(getattr(m, "id", None) == message_id for m in session.messages)
    if not belongs:
        raise HTTPException(status_code=404, detail="Message not found in this session")
    ok = await store.update_message_content(message_id, req.content)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")
    await store.touch(session_id)
    return {"ok": True}


class RenameSessionRequest(BaseModel):
    title: str | None = None
    mode: str | None = None
    model: str | None = None


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, req: RenameSessionRequest, user_id: str = Depends(verify_token)):
    store = await get_session_store()
    if req.title is not None:
        title = req.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        await store.update_title(session_id, title)
    # mode 可为空字符串（切回默认模式），故用 is not None 判断
    if req.mode is not None:
        await store.update_mode(session_id, req.mode)
    # model：用于「重名模型点击候选后写回」场景；前端通常传复合格式 `provider/id`
    if req.model is not None:
        await store.update_model(session_id, req.model)
    return {"ok": True}


@router.post("/sessions/{session_id}/pin")
async def pin_session(session_id: str, user_id: str = Depends(verify_token)):
    store = await get_session_store()
    await store.pin_session(session_id)
    return {"ok": True}


@router.delete("/sessions/{session_id}/pin")
async def unpin_session(session_id: str, user_id: str = Depends(verify_token)):
    store = await get_session_store()
    await store.unpin_session(session_id)
    return {"ok": True}



@router.post("/sessions/cleanup-trivial")
async def cleanup_trivial_sessions(user_id: str = Depends(verify_token)):
    """批量删除只含试探性消息的会话（hi/hello/测试/你是谁等）。"""
    store = await get_session_store()
    deleted, deleted_ids = await store.cleanup_trivial()
    return {"deleted": deleted, "deleted_ids": deleted_ids}


@router.post("/sessions/{session_id}/regen-title")
async def regen_title(session_id: str, user_id: str = Depends(verify_token)):
    """用廉价模型重新生成标题（用户手动触发，force 跳过已有标题保护）。"""
    from ethan.memory.session import _PROTECTED_PREFIXES, _generate_smart_title
    store = await get_session_store()
    session = await store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # 受保护标题（定时/后台/心跳）前缀承载结构含义，不可被覆盖
    if any(session.title.startswith(p) for p in _PROTECTED_PREFIXES):
        return {"ok": False, "title": session.title,
                "error": "受保护标题（定时/后台/心跳）不可重新生成"}
    title = await _generate_smart_title(session.messages)
    if title:
        await store.update_title(session_id, title)
        return {"ok": True, "title": title}
    return {"ok": False, "title": session.title, "error": "标题生成失败"}

@router.post("/sessions/{session_id}/compact")
async def compact_session(session_id: str, user_id: str = Depends(verify_token)):
    """压缩会话历史：用廉价模型把旧对话压成摘要替换存储，保留最近一轮，释放上下文。

    供 Web 的 /compact 命令调用。返回 {ok, summary}，前端拿 summary 回显并刷新会话。
    """
    from ethan.core.session_ops import compact_session as _compact
    store = await get_session_store()
    summary = await _compact(store, session_id, get_config().defaults.model)
    return {"ok": True, "summary": summary}


@router.post("/sessions/{session_id}/summary")
async def summary_session(session_id: str, user_id: str = Depends(verify_token)):
    """对当前对话生成结构化总结（只读，不修改会话历史）。

    供 Web 的 /summary 命令调用。返回 {ok, summary}。
    """
    from ethan.core.session_ops import summary_session as _summary
    store = await get_session_store()
    result = await _summary(store, session_id, get_config().defaults.model)
    return {"ok": True, "summary": result}

@router.get("/sessions/{session_id}/messages/{message_id}/tool-raw")
async def get_tool_raw(session_id: str, message_id: int,
                       index: int = 0, tool_call_id: str | None = None,
                       field: str = "args",
                       user_id: str = Depends(verify_token)):
    """返回工具调用的原始参数或结果（未压缩、未截断）。"""
    store = await get_session_store()
    session = await store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 找到目标消息
    msg = None
    for m in session.messages:
        if getattr(m, "id", None) == message_id:
            msg = m
            break
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found in this session")

    tool_calls = getattr(msg, "tool_calls", None) or []
    if not tool_calls:
        raise HTTPException(status_code=404, detail="Message has no tool_calls")

    # 优先按 tool_call_id 匹配，回退到 index
    tc = None
    if tool_call_id:
        for t in tool_calls:
            if getattr(t, "id", None) == tool_call_id:
                tc = t
                break
    if tc is None:
        if index < 0 or index >= len(tool_calls):
            raise HTTPException(status_code=404, detail="tool_calls index out of range")
        tc = tool_calls[index]

    result = {}
    tc_id = getattr(tc, "id", None)

    if field in ("args", "both"):
        args = getattr(tc, "arguments", None)
        if args is None:
            result["args"] = "{}"
        elif isinstance(args, str):
            # 尝试格式化 JSON 字符串
            try:
                result["args"] = json.dumps(json.loads(args), ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, TypeError):
                result["args"] = args
        else:
            result["args"] = json.dumps(args, ensure_ascii=False, indent=2)

    if field in ("result", "both"):
        # 在后续消息中找到 tool role 且 tool_call_id 匹配的消息
        tool_msg = None
        if tc_id:
            for m in session.messages:
                if getattr(m, "role", None) == "tool" and getattr(m, "tool_call_id", None) == tc_id:
                    tool_msg = m
                    break
        if tool_msg is None:
            if field == "result":
                raise HTTPException(status_code=404, detail="Tool result message not found")
            result["result"] = None
        else:
            result["result"] = tool_msg.content

    if not result:
        raise HTTPException(status_code=400, detail=f"Invalid field: {field}. Use args, result, or both.")

    return result
