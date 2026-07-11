"""completions 路由：/v1/chat/completions（OpenAI 兼容）+ API Key 管理。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ethan.core.config import get_config
from ethan.memory.api_keys import APIKeyStore
from ethan.memory.facts import FactStore
from ethan.memory.session import SessionStore
from ethan.providers.base import Message

from .deps import create_agent, verify_token
from .helpers import _friendly_error
from .producers import _save_progress
from .tasks import _maybe_regen_title

logger = logging.getLogger(__name__)

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
    from ethan.core.paths import user_facts_path, user_sessions_db_path
    agent = create_agent(req.model, channel="api", user_id=user_id)

    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()

    # 未传 session_id 时自动创建 session，确保所有 API 调用都持久化到会话列表
    if not req.session_id:
        from ethan.memory.session import _generate_id
        req.session_id = _generate_id()
        model_id = req.model or get_config().defaults.model
        await store.create_with_id(req.session_id, model_id, source="api")

    session_id = req.session_id
    user_msg = Message(role=req.messages[-1].role, content=req.messages[-1].content)
    await store.save_message(session_id, user_msg)

    # 加载历史上下文（首轮对话时 history 为空，等同于无状态）
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

    if req.stream:
        return StreamingResponse(
            _stream_completions(agent, messages, store, session_id, req.model, user_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # 非流式：走 stream_chat + StreamCollector 收集工具步骤并实时落库，
    # 这样中断/异常时 Web UI 仍能看到已执行的工具调用过程（与 Web stream 路径行为一致）。
    from ethan.core.stream_collector import StreamCollector
    from ethan.providers.base import SkillsMatchedEvent, ThinkingEvent, ToolEvent

    collector = StreamCollector().bind(agent)
    progress_msg_id: int | None = None
    try:
        try:
            async for item in agent.stream_chat(messages):
                if isinstance(item, (ToolEvent, ThinkingEvent, SkillsMatchedEvent)):
                    collector.feed(item)
                    # 工具事件实时落库进度，中断也不丢过程
                    if isinstance(item, ToolEvent) and session_id:
                        try:
                            progress_msg_id = await _save_progress(
                                store, session_id, progress_msg_id,
                                collector.tool_steps or [], collector.a2ui or None,
                            )
                        except Exception:
                            logger.exception("实时保存工具进度失败 session=%s", session_id)
                    continue
                collector.feed(item)
        except asyncio.CancelledError:
            # 调用被取消：保存已生成的部分内容 + tool_steps，标记 [已停止]
            if session_id:
                try:
                    stopped_content = (collector.full or "") + "\n\n_（已停止）_"
                    stopped_msg = Message(
                        role="assistant", content=stopped_content,
                        thought=collector.thought, usage=collector.usage_dict,
                        tool_steps=collector.tool_steps or [], a2ui=collector.a2ui or None,
                        matched_skills=collector.matched_skills or None,
                    )
                    if progress_msg_id:
                        await store.update_message(progress_msg_id, session_id, stopped_msg)
                    else:
                        await store.save_message(session_id, stopped_msg)
                    await store.touch(session_id)
                except Exception:
                    logger.exception("保存已停止内容失败 session=%s", session_id)
            raise
        except Exception as e:
            # 异常中断：把错误信息 + 已执行 tool_steps 持久化，刷新后仍可见
            err_text = _friendly_error(e, agent)
            error_content = (collector.full + "\n\n" if collector.full else "") + err_text
            err_msg = Message(
                role="assistant", content=error_content,
                thought=collector.thought, usage=collector.usage_dict,
                tool_steps=collector.tool_steps or [], a2ui=collector.a2ui or None,
                matched_skills=collector.matched_skills or None,
            )
            try:
                if progress_msg_id:
                    await store.update_message(progress_msg_id, session_id, err_msg)
                else:
                    await store.save_message(session_id, err_msg)
                await store.touch(session_id)
            except Exception:
                logger.exception("保存错误消息失败 session=%s", session_id)
            raise

        usage_dict = collector.usage_dict
        content = collector.full or ""
        if not content.strip():
            logger.warning("completions() session=%s 返回空回复，usage=%s", session_id, usage_dict)
            content = "[Agent 返回了空回复。可能原因：上下文过大、模型异常或工具执行卡住。请重试或简化任务。]"
        asst_msg = Message(
            role="assistant", content=content, thought=collector.thought,
            usage=usage_dict, tool_steps=collector.tool_steps or [],
            a2ui=collector.a2ui or None,
            matched_skills=collector.matched_skills or None,
        )
        # 正常结束：把实时进度行更新为最终回复，复用同一行避免重复两条 assistant 消息
        if progress_msg_id:
            await store.update_message(progress_msg_id, session_id, asst_msg)
        else:
            await store.save_message(session_id, asst_msg)
        await store.touch(session_id)
        asyncio.create_task(_maybe_regen_title(session_id))
        return {
            "id": f"chatcmpl-{session_id[:8]}",
            "object": "chat.completion",
            "model": req.model or get_config().defaults.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": agent.usage.input_tokens,
                "completion_tokens": agent.usage.output_tokens,
                "total_tokens": agent.usage.input_tokens + agent.usage.output_tokens,
            },
            "ethan": {"session_id": session_id},
        }
    finally:
        await store.close()


async def _stream_completions(agent, messages, store: SessionStore, session_id: str, model: str | None, user_id: str = ""):
    from ethan.core.stream_collector import StreamCollector
    from ethan.interface.routers.chat import _maybe_consolidate, _maybe_generate_skill
    from ethan.providers.base import SkillsMatchedEvent, ThinkingEvent, ToolEvent

    collector = StreamCollector().bind(agent)
    progress_msg_id: int | None = None
    try:
        try:
            async for item in agent.stream_chat(messages):
                if isinstance(item, (ToolEvent, ThinkingEvent, SkillsMatchedEvent)):
                    collector.feed(item)
                    # 工具事件实时落库进度，连接中断也不丢工具调用过程
                    if isinstance(item, ToolEvent) and session_id:
                        try:
                            progress_msg_id = await _save_progress(
                                store, session_id, progress_msg_id,
                                collector.tool_steps or [], collector.a2ui or None,
                            )
                        except Exception:
                            logger.exception("实时保存工具进度失败 session=%s", session_id)
                    continue  # completions 接口不暴露工具调用 / 思考过程给客户端
                text = collector.feed(item)
                if not text:
                    continue
                chunk = {
                    "id": f"chatcmpl-{session_id[:8]}",
                    "object": "chat.completion.chunk",
                    "model": model or get_config().defaults.model,
                    "choices": [{"delta": {"content": text}, "index": 0, "finish_reason": None}],
                    "ethan": {"session_id": session_id},
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            # 客户端断开 / 超时：保存已生成部分 + tool_steps，标记 [已停止]
            if session_id:
                try:
                    stopped_content = (collector.full or "") + "\n\n_（已停止）_"
                    stopped_msg = Message(
                        role="assistant", content=stopped_content,
                        thought=collector.thought, usage=collector.usage_dict,
                        tool_steps=collector.tool_steps or [], a2ui=collector.a2ui or None,
                        matched_skills=collector.matched_skills or None,
                    )
                    if progress_msg_id:
                        await store.update_message(progress_msg_id, session_id, stopped_msg)
                    else:
                        await store.save_message(session_id, stopped_msg)
                    await store.touch(session_id)
                except Exception:
                    logger.exception("保存已停止内容失败 session=%s", session_id)
            raise
        except Exception as e:
            # 异常中断：持久化错误信息 + 已执行 tool_steps，刷新后仍可见
            err_text = _friendly_error(e, agent)
            error_content = (collector.full + "\n\n" if collector.full else "") + err_text
            err_msg = Message(
                role="assistant", content=error_content,
                thought=collector.thought, usage=collector.usage_dict,
                tool_steps=collector.tool_steps or [], a2ui=collector.a2ui or None,
                matched_skills=collector.matched_skills or None,
            )
            try:
                if progress_msg_id:
                    await store.update_message(progress_msg_id, session_id, err_msg)
                else:
                    await store.save_message(session_id, err_msg)
                await store.touch(session_id)
            except Exception:
                logger.exception("保存错误消息失败 session=%s", session_id)
            yield f"data: {json.dumps({'error': err_text})}\n\n"
            return

        yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

        if collector.full or collector.tool_steps:
            usage_dict = collector.usage_dict
            asst_msg = Message(
                role="assistant", content=collector.full,
                thought=collector.thought, usage=usage_dict,
                tool_steps=collector.tool_steps or [], a2ui=collector.a2ui or None,
                matched_skills=collector.matched_skills or None,
            )
            # 正常结束：把实时进度行更新为最终回复，复用同一行避免重复两条 assistant 消息
            if progress_msg_id:
                await store.update_message(progress_msg_id, session_id, asst_msg)
            else:
                await store.save_message(session_id, asst_msg)
            await store.touch(session_id)
            asyncio.create_task(_maybe_regen_title(session_id))
            asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, user_id))
            asyncio.create_task(_maybe_generate_skill(session_id, agent._provider.model, user_id))
    finally:
        await store.close()
