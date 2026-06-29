"""chat 路由：/health, /poll, /chat 及 SSE 流式辅助函数。"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ethan.core.config import get_config
from ethan.memory.facts import FactStore
from ethan.memory.session import SessionStore
from ethan.providers.base import Message
from ethan import __version__

from .deps import verify_token, create_agent

router = APIRouter()


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


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    stream: bool = False
    session_id: str | None = None
    channel: str = "web"
    quote: dict | None = None  # {role, content}：引用某条历史消息，注入给模型但不入库
    mode: str = ""  # "" = 工作助手; 规范英文 key，如 "legal"/"companion"（见 core/modes.py）


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict


@router.post("/chat")
async def chat(req: ChatRequest, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path, user_facts_path
    from ethan.core.context import set_session_id
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

    if req.session_id:
        from ethan.memory.working import WorkingMemory

        session = await store.load(req.session_id)
        history = session.messages if session else []

        fact_store = FactStore(path=user_facts_path())
        memory = WorkingMemory.from_history(history, cold_facts=fact_store.build_context(), hot_size=10)

        current_user = _with_quote(messages[-1], req.quote)
        messages = memory.build_context() + [current_user]
    elif req.quote and messages and messages[-1].role == "user":
        messages[-1] = _with_quote(messages[-1], req.quote)

    if req.stream:
        # 生成与连接解耦：把 agent.stream_chat 放进后台 producer 任务，事件写入
        # ChatRun 缓冲并扇出给订阅者。SSE 响应只是一个订阅者，断开（刷新）只退订，
        # 不影响 producer——生成照常跑完并入库。刷新后可经 GET /chat/{id}/stream 重连回放。
        from ethan.core.consent import WebConsentProvider
        from ethan.core.run_manager import RunManager

        consent = WebConsentProvider(session_id=req.session_id or "")
        manager = RunManager.instance()
        run = manager.create(req.session_id or "", consent=consent)
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
    """
    from fastapi import Response
    from ethan.core.run_manager import RunManager
    run = RunManager.instance().get(session_id)
    if run is None:
        return Response(status_code=204)
    return StreamingResponse(
        _sse_from_run(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── SSE helpers ───────────────────────────────────────────────────


def _friendly_error(e: Exception, agent) -> str:
    """把 provider 鉴权 / 配置类错误转成给用户的友好提示，建议切换 model。"""
    msg = str(e)
    lower = msg.lower()
    # 鉴权缺失：空 api_key / 没配 token
    if "could not resolve authentication method" in lower or "未配置" in msg or "api_key" in lower and "not" in lower:
        model = getattr(agent, "_provider", None)
        model_id = getattr(model, "model", "") if model else ""
        return (
            f"当前模型 {model_id} 的 provider 未配置 api_key 或鉴权失败。"
            "请在设置页切换到已配置的模型，或在 ~/.ethan/config.yaml 的 providers 段补上对应 api_key。"
        )
    # 网络层 fetch failed（多见于第三方中转服务挂了）
    if "fetch failed" in lower or "connection" in lower or "timeout" in lower:
        return f"请求上游服务失败（可能中转服务不可达）：{msg[:120]}。建议在设置页切换 model 重试。"
    # 流式输出中途断连（上游/中转在生成过程中关闭了连接）
    if any(k in lower for k in ("unexpected eof", "peer closed", "incomplete chunked",
                                "remoteprotocolerror", "connection reset",
                                "stream ended", "incompleteread", "chunkedencodingerror")):
        return "上游连接在生成中途断开（多见于中转服务不稳）。以上内容已保存，可直接发「继续」补全，或在设置页切换 model 重试。"
    return msg[:300]


def _with_quote(user_msg: Message, quote: dict | None) -> Message:
    """返回一份带「引用块」前缀的用户消息副本（仅发给模型，不入库）。

    quote 形如 {"role": "user"|"assistant", "content": "..."}。
    """
    if not quote or not quote.get("content"):
        return user_msg
    role_label = "用户" if quote.get("role") == "user" else "Ethan"
    quote_text = str(quote["content"]).replace("\n", "\n> ")
    prefixed = f"> [引用 {role_label} 的消息]:\n> {quote_text}\n\n{user_msg.content}"
    return Message(role=user_msg.role, content=prefixed, created_at=user_msg.created_at)


async def _run_generation(
    run,
    agent,
    messages: list[Message],
    store: SessionStore,
    session_id: str | None,
    user_id: str = "",
    consent=None,
    mode: str = "",
) -> None:
    """Producer：后台任务跑 Agent 生成，把事件 emit 进 run 缓冲并扇出给订阅者。

    与 HTTP 连接解耦——订阅者（SSE 响应）断开不会取消本任务，生成照常跑完并入库。
    所有原先 `yield` 的地方改为 `run.emit(...)`。
    """
    from ethan.core.stream_collector import StreamCollector
    from ethan.core.consent import ConsentEvent, set_consent_provider
    from ethan.providers.base import ToolEvent, ThinkingEvent

    # consent provider 经 ContextVar 注入；本任务有独立 context，需在任务内设置。
    set_consent_provider(consent)

    collector = StreamCollector().bind(agent)
    try:
        async for item in agent.stream_chat(messages):
            if isinstance(item, ConsentEvent):
                run.emit({
                    "consent_request": True,
                    "request_id": item.request_id,
                    "tool": item.tool,
                    "description": item.description,
                    "detail": item.detail,
                })
            elif isinstance(item, ThinkingEvent):
                run.emit({"thinking": True})
            elif isinstance(item, ToolEvent):
                collector.feed(item)
                if item.state == "start":
                    run.emit({"tool": item.tool_name, "args": item.args_summary, "state": "start",
                              "id": item.tool_call_id})
                else:
                    step = collector.tool_steps[-1]
                    evt = {
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": item.state,
                        "id": item.tool_call_id,
                        "duration_ms": step.get("duration_ms"),
                        "result_preview": item.result_preview or "",
                        "result_detail": item.result_detail or "",
                        "sub_steps": item.sub_steps or [],
                    }
                    if item.ui:
                        evt["ui"] = item.ui
                    run.emit(evt)
            else:
                collector.feed(item)
                run.emit({"content": item})
    except asyncio.CancelledError:
        # 被显式取消（如新 run 替换旧 run）：不入库，直接收尾。
        if consent is not None:
            consent.cancel_all()
        run.finish()
        RunManager_schedule_removal(run.session_id)
        raise
    except Exception as e:
        run.emit({"error": _friendly_error(e, agent)})
    finally:
        # 流结束（正常/异常）时取消未决授权 Future，避免泄漏
        if consent is not None:
            consent.cancel_all()

    usage_dict = collector.usage_dict

    if session_id and (collector.full or collector.thought):
        asst_msg = Message(
            role="assistant",
            content=collector.full,
            thought=collector.thought,
            usage=usage_dict,
            tool_steps=collector.tool_steps or [],
            a2ui=collector.a2ui or None,
        )
        await store.save_message(session_id, asst_msg)
        await store.touch(session_id)
        if agent._skills and agent.last_matched_skills:
            for _name in agent.last_matched_skills:
                asyncio.create_task(asyncio.to_thread(agent._skills.record_hit, _name))
        asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, user_id, mode=mode))
        asyncio.create_task(_maybe_regen_title(session_id, store))
        asyncio.create_task(_maybe_generate_skill(session_id, agent._provider.model, user_id))

    await store.close()

    # 通知所有订阅者「流结束」并附最终 usage
    run.emit({"done": True, "usage": usage_dict})
    run.finish()
    RunManager_schedule_removal(run.session_id)


def RunManager_schedule_removal(session_id: str) -> None:
    from ethan.core.run_manager import RunManager
    RunManager.instance().schedule_removal(session_id)


async def _sse_from_run(run) -> AsyncGenerator[str, None]:
    """Consumer：把一个 ChatRun 的事件流转成 SSE。

    先回放缓冲（断线重连补齐已生成内容），再实时读队列直到收到结束哨兵。
    本生成器被取消（客户端断开）只退订，不影响 producer。
    """
    from ethan.core.run_manager import SENTINEL

    q, backlog = run.subscribe()
    try:
        for evt in backlog:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        # 缓冲已含结束事件且 producer 已完成：无需再等队列
        if run.done:
            return
        while True:
            item = await q.get()
            if item is SENTINEL:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    finally:
        run.unsubscribe(q)


async def _maybe_regen_title(session_id: str, store: SessionStore) -> None:
    try:
        from ethan.memory.session import decide_title
        session = await store.load(session_id)
        if not session:
            return
        title = await decide_title(session.messages)
        if title and title != session.title:
            await store.update_title(session_id, title)
    except Exception:
        pass


async def _maybe_consolidate(session_id: str, model: str, user_id: str = "", mode: str = "") -> None:
    try:
        from ethan.memory.consolidator import Consolidator
        from ethan.memory.facts import FactStore
        from ethan.memory.working import MemoryConfig, WorkingMemory
        from ethan.core.paths import user_sessions_db_path, user_facts_path

        # 心理画像是否额外抽取：由当前 mode 自身声明，不在此硬编码模式名
        from ethan.core.modes import resolve_mode
        extract_psych = resolve_mode(mode).extract_psych

        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        session = await store.load(session_id)
        await store.close()
        if not session:
            return

        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns == 0 or user_turns % 10 != 0:
            return

        memory = WorkingMemory(config=MemoryConfig(hot_size=10))
        fact_store = FactStore(path=user_facts_path())
        memory.cold_facts = fact_store.build_context()

        history = list(session.messages)
        pairs = []
        i = 0
        while i < len(history) - 1:
            if history[i].role == "user" and history[i + 1].role == "assistant":
                pairs.append((history[i], history[i + 1]))
                i += 2
            else:
                i += 1
        for u, a in pairs:
            memory.add_turn(u, a)

        consolidator = Consolidator(main_model=model)
        while memory.needs_compression():
            batch = memory.get_compress_batch()
            summary = await consolidator.compress(batch, memory.warm_summary)
            memory.apply_summary(summary)

        if memory.needs_cold_extraction():
            result = await consolidator.extract_cold(
                memory.warm_summary, memory.cold_facts
            )
            for fact in result["key_facts"]:
                fact_store.add(fact, confidence=0.8, source=session_id)
            from ethan.core.profile import apply_extraction
            apply_extraction(result)
            memory.apply_cold_extraction(fact_store.build_context(), result["condensed"])
    except Exception:
        pass


async def _maybe_generate_skill(session_id: str, model: str, user_id: str = "") -> None:
    try:
        from ethan.skills.generator import SkillGenerator, MIN_TURNS
        from ethan.core.paths import user_sessions_db_path
        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        session = await store.load(session_id)
        await store.close()
        if not session:
            return
        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns < MIN_TURNS or user_turns % 5 != 0:
            return
        generator = SkillGenerator(model=model, user_id=user_id)
        await generator.maybe_generate(session)
    except Exception:
        pass
