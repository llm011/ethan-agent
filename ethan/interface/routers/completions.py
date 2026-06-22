"""completions 路由：/v1/chat/completions（OpenAI 兼容）+ API Key 管理。"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ethan.core.config import get_config
from ethan.memory.api_keys import APIKeyStore
from ethan.memory.facts import FactStore
from ethan.memory.session import SessionStore
from ethan.providers.base import Message

from .deps import create_agent

router = APIRouter()


# ── API Key鉴权 ───────────────────────────────────────────────────


async def _verify_api_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    key = auth.removeprefix("Bearer ").strip()
    # 优先用 config.yaml 的多用户 api_keys 解析（user_id 隔离）
    from ethan.core.users import get_user_store
    user_id = get_user_store().resolve_api_key(key)
    if user_id is None:
        # 兼容旧的 api_keys.db（无 user 绑定 → admin）
        store: APIKeyStore = request.app.state.api_key_store
        if await store.verify(key):
            user_id = get_user_store().get_admin_user_id()
        else:
            raise HTTPException(401, "Invalid API key")
    request.state.user_id = user_id
    return user_id


# ── API Key 管理 ──────────────────────────────────────────────────

from .deps import verify_token


class APIKeyCreateRequest(BaseModel):
    name: str


@router.get("/api-keys", dependencies=[Depends(verify_token)])
async def list_api_keys(request: Request):
    return {"keys": await request.app.state.api_key_store.list_keys()}


@router.post("/api-keys", dependencies=[Depends(verify_token)])
async def create_api_key(req: APIKeyCreateRequest, request: Request):
    return await request.app.state.api_key_store.create(req.name)


@router.delete("/api-keys/{key_id}", dependencies=[Depends(verify_token)])
async def delete_api_key(key_id: str, request: Request):
    ok = await request.app.state.api_key_store.delete(key_id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"ok": True}


# ── /v1/chat/completions ──────────────────────────────────────────


class CompletionMessage(BaseModel):
    role: str
    content: str


class CompletionsRequest(BaseModel):
    model: str | None = None
    messages: list[CompletionMessage]
    stream: bool = False
    session_id: str | None = None  # Ethan 扩展字段：指定对话 session


@router.post("/v1/chat/completions")
async def completions(req: CompletionsRequest, request: Request, user_id: str = Depends(_verify_api_key)):
    """OpenAI 兼容的 completions 接口。

    扩展字段 `session_id`：绑定到已有 Session 实现上下文持续对话，
    效果与 Web UI 完全一致（WorkingMemory + cold facts）。
    返回体中 `ethan.session_id` 可用于下次继续对话。
    """
    from ethan.core.paths import user_sessions_db_path, user_facts_path
    agent = create_agent(req.model, channel="api", user_id=user_id)

    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()

    if req.session_id:
        session_id = req.session_id
        user_msg = Message(role=req.messages[-1].role, content=req.messages[-1].content)
        await store.save_message(session_id, user_msg)

        from ethan.memory.working import MemoryConfig, WorkingMemory

        session_obj = await store.load(session_id)
        history = session_obj.messages if session_obj else []

        memory = WorkingMemory(config=MemoryConfig(hot_size=10))
        memory.cold_facts = FactStore(path=user_facts_path()).build_context()

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

        messages = memory.build_context() + [user_msg]
    else:
        # 无 session_id：直接用请求里的完整消息列表，不走 WorkingMemory 重建
        session_id = None
        messages = [Message(role=m.role, content=m.content) for m in req.messages]

    if req.stream:
        return StreamingResponse(
            _stream_completions(agent, messages, store, session_id, req.model, user_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        response = await agent.chat(messages)
        usage_dict = {"input": agent.usage.input_tokens, "output": agent.usage.output_tokens, "cache": agent.usage.cache_tokens}
        if session_id:
            await store.save_message(session_id, Message(role="assistant", content=response.content, usage=usage_dict))
            await store.touch(session_id)
        return {
            "id": f"chatcmpl-{(session_id or 'nosession')[:8]}",
            "object": "chat.completion",
            "model": req.model or get_config().defaults.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": response.content}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": agent.usage.input_tokens,
                "completion_tokens": agent.usage.output_tokens,
                "total_tokens": agent.usage.input_tokens + agent.usage.output_tokens,
            },
            "ethan": {"session_id": session_id},
        }
    finally:
        await store.close()


async def _stream_completions(agent, messages, store: SessionStore, session_id: str | None, model: str | None, user_id: str = ""):
    from ethan.providers.base import ToolEvent
    from ethan.interface.routers.chat import _maybe_consolidate, _maybe_generate_skill

    full = ""
    try:
        try:
            async for item in agent.stream_chat(messages):
                if isinstance(item, ToolEvent):
                    continue  # completions 接口不暴露工具调用过程
                full += item
                chunk = {
                    "id": f"chatcmpl-{(session_id or 'nosession')[:8]}",
                    "object": "chat.completion.chunk",
                    "model": model or get_config().defaults.model,
                    "choices": [{"delta": {"content": item}, "index": 0, "finish_reason": None}],
                    "ethan": {"session_id": session_id},
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

        if full and session_id:
            usage_dict = {"input": agent.usage.input_tokens, "output": agent.usage.output_tokens, "cache": agent.usage.cache_tokens}
            await store.save_message(session_id, Message(role="assistant", content=full, usage=usage_dict))
            await store.touch(session_id)
            asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, user_id))
            asyncio.create_task(_maybe_generate_skill(session_id, agent._provider.model, user_id))
    finally:
        await store.close()
