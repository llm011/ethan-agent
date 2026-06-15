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


@router.get("/poll", dependencies=[Depends(verify_token)])
async def poll():
    store = SessionStore()
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


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict


@router.post("/chat", dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest):
    agent = create_agent(req.model, channel=req.channel)
    messages = [Message(role=m["role"], content=m.get("content", "")) for m in req.messages]

    store = SessionStore()
    await store.init()

    if req.session_id:
        for m in messages[-1:]:
            if m.role == "user":
                await store.save_message(req.session_id, m)

    if req.session_id:
        from ethan.memory.working import MemoryConfig, WorkingMemory

        session = await store.load(req.session_id)
        history = session.messages if session else []

        memory = WorkingMemory(config=MemoryConfig(hot_size=10))
        fact_store = FactStore()
        memory.cold_facts = fact_store.build_context()

        pairs: list[tuple[Message, Message]] = []
        hist_ua = [m for m in history if m.role in ("user", "assistant")]
        i = 0
        while i < len(hist_ua) - 1:
            if hist_ua[i].role == "user" and hist_ua[i + 1].role == "assistant":
                pairs.append((hist_ua[i], hist_ua[i + 1]))
                i += 2
            else:
                i += 1

        for u, a in pairs[-memory.config.hot_size:]:
            memory.hot.append(u)
            memory.hot.append(a)

        current_user = messages[-1]
        messages = memory.build_context() + [current_user]

    if req.stream:
        return StreamingResponse(
            _stream_response(agent, messages, store, req.session_id),
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


async def _stream_response(
    agent,
    messages: list[Message],
    store: SessionStore,
    session_id: str | None,
) -> AsyncGenerator[str, None]:
    from ethan.providers.base import ToolEvent

    tool_start_times: dict[str, float] = {}
    collected_tool_steps: list[dict] = []
    full = ""
    try:
        async for item in agent.stream_chat(messages):
            if isinstance(item, ToolEvent):
                if item.state == "start":
                    tool_start_times[item.tool_name] = time.time()
                    collected_tool_steps.append({
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": "running",
                        "duration_ms": None,
                        "result_preview": "",
                    })
                    evt = {"tool": item.tool_name, "args": item.args_summary, "state": "start"}
                else:
                    duration_ms = int(
                        (time.time() - tool_start_times.pop(item.tool_name, time.time())) * 1000
                    )
                    for step in reversed(collected_tool_steps):
                        if step["tool"] == item.tool_name and step["state"] == "running":
                            step["state"] = item.state
                            step["duration_ms"] = duration_ms
                            step["result_preview"] = item.result_preview or ""
                            break
                    evt = {
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": item.state,
                        "duration_ms": duration_ms,
                        "result_preview": item.result_preview or "",
                    }
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            else:
                full += item
                yield f"data: {json.dumps({'content': item}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

    if session_id and full:
        usage_dict = {
            "input": agent.usage.input_tokens,
            "output": agent.usage.output_tokens,
            "cache": agent.usage.cache_tokens,
        }
        asst_msg = Message(
            role="assistant",
            content=full,
            usage=usage_dict,
            tool_steps=collected_tool_steps or [],
        )
        await store.save_message(session_id, asst_msg)
        await store.touch(session_id)
        if agent._skills and agent.last_matched_skills:
            for _name in agent.last_matched_skills:
                asyncio.create_task(asyncio.to_thread(agent._skills.record_hit, _name))
        asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model))
        asyncio.create_task(_maybe_regen_title(session_id, store))
        asyncio.create_task(_maybe_generate_skill(session_id, agent._provider.model))


async def _maybe_regen_title(session_id: str, store: SessionStore) -> None:
    try:
        from ethan.memory.session import _generate_smart_title
        session = await store.load(session_id)
        if not session:
            return
        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns != 3:
            return
        title = await _generate_smart_title(session.messages)
        await store.update_title(session_id, title)
    except Exception:
        pass


async def _maybe_consolidate(session_id: str, model: str) -> None:
    try:
        from ethan.memory.consolidator import Consolidator
        from ethan.memory.facts import FactStore
        from ethan.memory.working import MemoryConfig, WorkingMemory

        store = SessionStore()
        await store.init()
        session = await store.load(session_id)
        await store.close()
        if not session:
            return

        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns == 0 or user_turns % 10 != 0:
            return

        memory = WorkingMemory(config=MemoryConfig(hot_size=10))
        fact_store = FactStore()
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
            facts_list, condensed = await consolidator.extract_cold(
                memory.warm_summary, memory.cold_facts
            )
            for fact in facts_list:
                fact_store.add(fact, confidence=0.8, source=session_id)
            memory.apply_cold_extraction(fact_store.build_context(), condensed)
    except Exception:
        pass


async def _maybe_generate_skill(session_id: str, model: str) -> None:
    try:
        from ethan.skills.generator import SkillGenerator, MIN_TURNS
        store = SessionStore()
        await store.init()
        session = await store.load(session_id)
        await store.close()
        if not session:
            return
        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns < MIN_TURNS or user_turns % 5 != 0:
            return
        generator = SkillGenerator(model=model)
        await generator.maybe_generate(session)
    except Exception:
        pass
