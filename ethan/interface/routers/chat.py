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
    mode: str = ""  # "" = 默认工作助手(Ethan); "陪伴" = 苏念·陪伴倾听模式


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict


@router.post("/chat")
async def chat(req: ChatRequest, user_id: str = Depends(verify_token)):
    from ethan.core.paths import user_sessions_db_path, user_facts_path
    agent = create_agent(req.model, channel=req.channel, user_id=user_id, mode=req.mode)
    messages = [Message(role=m["role"], content=m.get("content", "")) for m in req.messages]

    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()

    if req.session_id:
        for m in messages[-1:]:
            if m.role == "user":
                await store.save_message(req.session_id, m)

    # 持久化对话模式到 session：用户切换工作助手/苏念后，下次进入该会话自动恢复
    if req.session_id and req.mode:
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
        # 注入 Web 授权 provider（敏感操作经 SSE 弹窗确认）
        from ethan.core.consent import WebConsentProvider, set_consent_provider
        consent = WebConsentProvider()
        set_consent_provider(consent)
        return StreamingResponse(
            _stream_response(agent, messages, store, req.session_id, user_id, consent, mode=req.mode),
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


async def _stream_response(
    agent,
    messages: list[Message],
    store: SessionStore,
    session_id: str | None,
    user_id: str = "",
    consent=None,
    mode: str = "",
) -> AsyncGenerator[str, None]:
    from ethan.core.stream_collector import StreamCollector
    from ethan.core.consent import ConsentEvent
    from ethan.providers.base import ToolEvent

    collector = StreamCollector().bind(agent)
    try:
        async for item in agent.stream_chat(messages):
            if isinstance(item, ConsentEvent):
                evt = {
                    "consent_request": True,
                    "request_id": item.request_id,
                    "tool": item.tool,
                    "description": item.description,
                    "detail": item.detail,
                }
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            elif isinstance(item, ToolEvent):
                collector.feed(item)
                # 即时把 ToolEvent 推给前端（SSE 不能等批处理）
                if item.state == "start":
                    evt = {"tool": item.tool_name, "args": item.args_summary, "state": "start",
                           "id": item.tool_call_id}
                else:
                    step = collector.tool_steps[-1]  # feed 刚追加/关闭的那个
                    evt = {
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": item.state,
                        "id": item.tool_call_id,
                        "duration_ms": step.get("duration_ms"),
                        "result_preview": item.result_preview or "",
                        "sub_steps": item.sub_steps or [],
                    }
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            else:
                collector.feed(item)
                yield f"data: {json.dumps({'content': item}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': _friendly_error(e, agent)}, ensure_ascii=False)}\n\n"
    finally:
        # 流结束（正常或异常）时，取消所有未决的授权 Future，避免泄漏
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
        )
        await store.save_message(session_id, asst_msg)
        await store.touch(session_id)
        if agent._skills and agent.last_matched_skills:
            for _name in agent.last_matched_skills:
                asyncio.create_task(asyncio.to_thread(agent._skills.record_hit, _name))
        asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, user_id, mode=mode))
        asyncio.create_task(_maybe_regen_title(session_id, store))
        asyncio.create_task(_maybe_generate_skill(session_id, agent._provider.model, user_id))

    # Always send final usage to frontend so it knows the stream is done
    evt = {"done": True, "usage": usage_dict}
    yield f"data: {json.dumps(evt)}\n\n"


async def _maybe_regen_title(session_id: str, store: SessionStore) -> None:
    try:
        from ethan.memory.session import _generate_smart_title
        session = await store.load(session_id)
        if not session:
            return
        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns != 2:
            return
        title = await _generate_smart_title(session.messages)
        await store.update_title(session_id, title)
    except Exception:
        pass


async def _maybe_consolidate(session_id: str, model: str, user_id: str = "", mode: str = "") -> None:
    try:
        from ethan.memory.consolidator import Consolidator
        from ethan.memory.facts import FactStore
        from ethan.memory.working import MemoryConfig, WorkingMemory
        from ethan.core.paths import user_sessions_db_path, user_facts_path
        # 心理画像仅在苏念·陪伴倾听模式下抽取;工作助手模式不分析用户心理
        extract_psych = mode in ("陪伴", "counselor", "苏念")

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
                memory.warm_summary, memory.cold_facts, extract_psych=extract_psych
            )
            for fact in result["key_facts"]:
                fact_store.add(fact, confidence=0.8, source=session_id)
            # 基础特征 + 心理与情绪 → 写进 user_profile.md(merge 去重)
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
