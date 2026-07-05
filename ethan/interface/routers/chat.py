"""chat 路由：/health, /poll, /chat, /reconnect, /stop。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ethan.memory.facts import FactStore
from ethan.memory.session import SessionStore
from ethan.providers.base import Message
from ethan import __version__

from .deps import verify_token, create_agent
from .schemas import ChatRequest, ChatResponse
from .sse import _sse_from_run
from .producers import _run_generation, _run_delegate_generation

router = APIRouter()

logger = logging.getLogger(__name__)


# ── Health / Poll ────────────────────────────────────────────────


@router.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


@router.get("/poll")
async def poll(user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    sessions = await store.list_recent(50)
    await store.close()
    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "model": s.model,
                "updated_at": s.updated_at,
                "source": getattr(s, "source", "web"),
                "mode": getattr(s, "mode", "") or "",
            }
            for s in sessions
        ]
    }


# ── Chat ─────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(req: ChatRequest, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path, user_facts_path
    from ethan.core.context import set_session_id
    from .helpers import _with_quote
    set_session_id(req.session_id or "")  # browser 工具按对话隔离/授权
    agent = create_agent(req.model, channel=req.channel, user_id=user_id, mode=req.mode)
    messages = [Message(role=m["role"], content=m.get("content", "")) for m in req.messages]

    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()

    if req.session_id:
        for m in messages[-1:]:
            if m.role == "user":
                # 把引用信息附到消息上一起持久化，刷新后仍能渲染引用气泡
                if req.quote and req.quote.get("content"):
                    m.quote = req.quote
                await store.save_message(req.session_id, m)
        # 持久化对话模式：退出再进入保持当前模式
        if req.mode:
            await store.update_mode(req.session_id, req.mode)

    if req.session_id and not req.btw:
        from ethan.memory.working import WorkingMemory

        session = await store.load(req.session_id)
        history = session.messages if session else []

        fact_store = FactStore(path=user_facts_path())
        memory = WorkingMemory.from_history(history, cold_facts=fact_store.build_context(), hot_size=10)

        current_user = _with_quote(messages[-1], req.quote)
        messages = memory.build_context() + [current_user]
    elif req.btw and messages:
        # /btw：只带本条消息，不带任何历史
        messages = [_with_quote(messages[-1], req.quote)]
    elif req.quote and messages and messages[-1].role == "user":
        messages[-1] = _with_quote(messages[-1], req.quote)

    if req.stream:
        from ethan.core.run_manager import RunManager

        # (1) 沉浸式工具模式：会话 mode 解析出 delegate_agent 时，整条会话的每句话都
        #     直接续接该 coding agent（同一工具 session），不走 Ethan chat 模型。
        #     工作目录按会话隔离（~/.ethan/agent-sessions/<会话id>）。
        from ethan.core.modes import resolve_mode
        from ethan.core.paths import user_agent_session_dir
        _mode = resolve_mode(req.mode)
        if _mode.delegate_agent and req.session_id:
            import os as _os
            cwd = str(user_agent_session_dir(req.session_id))
            _os.makedirs(cwd, exist_ok=True)
            prompt = (req.messages[-1].get("content", "") if req.messages else "").strip()
            run = RunManager.instance().create(req.session_id, user_id=user_id)
            run.task = asyncio.create_task(
                _run_delegate_generation(run, prompt, _mode.delegate_agent, cwd,
                                         store, req.session_id, user_id)
            )
            return StreamingResponse(
                _sse_from_run(run),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # (2) 镜像会话续接：source=codex/claude/opencode 的临时委派会话，用户直接发消息
        #     时把消息当新 prompt 续接对应 coding agent（resume），过程实时推回该会话。
        from ethan.acp import get_mirror_info
        minfo = get_mirror_info(req.session_id or "", user_id=user_id)
        if minfo and req.session_id:
            prompt = (req.messages[-1].get("content", "") if req.messages else "").strip()
            run = RunManager.instance().create(req.session_id, user_id=user_id)
            run.task = asyncio.create_task(
                _run_delegate_generation(run, prompt, minfo["agent"], minfo["cwd"],
                                         store, req.session_id, user_id)
            )
            return StreamingResponse(
                _sse_from_run(run),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # (3) 普通 chat：生成与连接解耦——把 agent.stream_chat 放进后台 producer 任务，
        # 事件写入 ChatRun 缓冲并扇出给订阅者。SSE 响应只是一个订阅者，断开（刷新）只退订，
        # 不影响 producer——生成照常跑完并入库。刷新后可经 GET /chat/{id}/stream 重连回放。
        from ethan.core.consent import WebConsentProvider

        consent = WebConsentProvider(session_id=req.session_id or "")
        manager = RunManager.instance()
        run = manager.create(req.session_id or "", consent=consent, user_id=user_id)
        run.task = asyncio.create_task(
            _run_generation(run, agent, messages, store, req.session_id, user_id, consent, mode=req.mode)
        )
        return StreamingResponse(
            _sse_from_run(run),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response = await agent.chat(messages)

    if req.session_id:
        await store.save_message(req.session_id, response)
        await store.touch(req.session_id)

    await store.close()
    return ChatResponse(
        content=response.content,
        model=agent._provider.model,
        usage={
            "input": agent.usage.input_tokens,
            "output": agent.usage.output_tokens,
            "cache": agent.usage.cache_tokens,
        },
    )


@router.get("/chat/{session_id}/stream")
async def reconnect_stream(session_id: str, user_id: str = Depends(verify_token)):
    """重连一个仍在进行的生成：刷新页面后前端调此端点，回放缓冲 + 继续实时推送。

    无活跃 run（已结束或从未开始）返回 204，前端据此走普通 fetchSession 拿落库结果。
    传 user_id 校验会话归属——不属于当前用户的 session_id 一律当作不存在（204），
    防止任意已登录用户凭 session_id attach 到他人正在生成的实时流（IDOR）。
    """
    from fastapi import Response
    from ethan.core.run_manager import RunManager
    run = RunManager.instance().get(session_id, user_id=user_id)
    if run is None:
        return Response(status_code=204)
    return StreamingResponse(
        _sse_from_run(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/{session_id}/stop")
async def stop_generation(session_id: str, user_id: str = Depends(verify_token)):
    """停止某 session 进行中的生成。已生成的部分内容会被保存并标记 [已停止]。

    返回 {ok, stopped}：stopped=True 表示确实停了一个进行中的 run；
    False 表示没有进行中的 run（可能刚好结束）。user_id 校验归属，防跨用户停别人的任务。
    """
    from ethan.core.run_manager import RunManager
    stopped = RunManager.instance().stop(session_id, user_id=user_id)
    return {"ok": True, "stopped": stopped}
