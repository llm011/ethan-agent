"""WeChat iLink bot event loop — receive messages, run Agent, reply.

Architecture mirrors lark_events.py:
  - start_wechat_listener() / stop_wechat_listener() called from api.py lifespan
  - _bot_loop() long-polls iLink, dispatches to _handle_message()
  - _handle_message() loads session history, runs Agent.stream_chat(), sends tool
    progress as individual messages, then sends final reply

Credentials are persisted to ~/.ethan/.secrets/wechat_credentials.json by
wechat_ilink.login_via_qrcode().  Re-login is triggered automatically when the
token is rejected (HTTP 401/403 or iLink ret=100).
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

_listeners: list[asyncio.Task] = []
_RETRY_DELAY_S = 2
_MAX_CONSECUTIVE_ERRORS = 5
_BACKOFF_S = 30

# 工具名 → emoji（与飞书保持一致）
_TOOL_EMOJI: dict[str, str] = {
    "shell": "💻", "web_search": "🔍", "web_fetch": "🌐",
    "file_read": "📖", "file_write": "✏️", "file_list": "📁",
    "memory_write": "🧠", "knowledge_search": "📚", "knowledge_read": "📖",
    "schedule_create": "⏰", "schedule_list": "📋", "schedule_remove": "📋",
    "rg_search": "🔍", "fd_find": "📁",
}

def _tool_icon(name: str) -> str:
    return _TOOL_EMOJI.get(name, "🔧")


def start_wechat_listener() -> None:
    """Spawn the bot loop task (idempotent)."""
    if _listeners:
        return
    task = asyncio.ensure_future(_bot_loop())
    _listeners.append(task)
    logger.info("[WeChat] iLink bot listener started")


def stop_wechat_listener() -> None:
    """Cancel the bot loop task."""
    for t in _listeners:
        if not t.done():
            t.cancel()
    _listeners.clear()
    logger.info("[WeChat] iLink bot listener stopped")


# ── Bot main loop ─────────────────────────────────────────────────────────────

async def _bot_loop() -> None:
    import httpx

    from ethan.interface.wechat_ilink import (
        get_updates,
        load_credentials,
        login_via_qrcode,
    )

    consecutive_errors = 0
    buf = ""

    while True:
        creds = load_credentials()
        if not creds:
            logger.info("[WeChat] No credentials — starting QR login...")
            try:
                creds = await login_via_qrcode()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("[WeChat] Login failed: %s — retrying in %ss", e, _BACKOFF_S)
                await asyncio.sleep(_BACKOFF_S)
                continue

        try:
            async with httpx.AsyncClient() as client:
                logger.info("[WeChat] Connected, polling for messages...")
                consecutive_errors = 0
                buf = ""
                while True:
                    msgs, buf = await get_updates(client, creds, buf)
                    for msg in msgs:
                        asyncio.ensure_future(_handle_message(msg, creds))

        except asyncio.CancelledError:
            raise
        except PermissionError as e:
            logger.warning("[WeChat] Token expired: %s — clearing creds, will re-login", e)
            from ethan.interface.wechat_ilink import clear_credentials
            clear_credentials()
            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            logger.warning("[WeChat] Poll error (%d/%d): %s", consecutive_errors, _MAX_CONSECUTIVE_ERRORS, e)
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                logger.error("[WeChat] Too many errors, backing off %ss", _BACKOFF_S)
                await asyncio.sleep(_BACKOFF_S)
                consecutive_errors = 0
            else:
                await asyncio.sleep(_RETRY_DELAY_S)


# ── Message handler ───────────────────────────────────────────────────────────

_seen_msg_ids: set[str] = set()
_seen_msg_order: deque[str] = deque(maxlen=2000)


async def _handle_message(msg: dict[str, Any], creds: Any) -> None:
    """Process a single iLink message: load history, stream Agent, send tool progress + reply."""
    import httpx

    from ethan.interface.wechat_ilink import send_text, send_typing
    from ethan.providers.base import Message, ToolEvent

    # ── Deduplicate ──────────────────────────────────────────────────────────
    msg_id = str(msg.get("message_id") or msg.get("msg_id") or "")
    if msg_id and msg_id in _seen_msg_ids:
        return
    if msg_id:
        if len(_seen_msg_order) == _seen_msg_order.maxlen:
            _seen_msg_ids.discard(_seen_msg_order[0])
        _seen_msg_order.append(msg_id)
        _seen_msg_ids.add(msg_id)

    # Skip bot's own outgoing messages (message_type=2)
    if msg.get("message_type") == 2:
        return

    # ── Extract text ─────────────────────────────────────────────────────────
    text = ""
    for item in (msg.get("item_list") or []):
        if item.get("type") == 1:
            text = ((item.get("text_item") or {}).get("text") or "").strip()
            if text:
                break

    if not text:
        return

    sender = msg.get("from_user_id") or ""
    group_id = msg.get("group_id") or ""
    context_token = msg.get("context_token") or ""
    chat_key = group_id or sender or msg_id[:16]
    # 群消息回复目标是群，私信回复目标是发信人
    reply_to = group_id or sender

    if not context_token:
        logger.warning("[WeChat] no context_token, cannot reply")
        return

    logger.info("[WeChat] msg from=%s group=%s text=%r", sender[:20], group_id[:20], text[:80])

    # ── Ack immediately ───────────────────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        try:
            await send_text(client, creds, reply_to, context_token, "收到，处理中...")
            logger.debug("[WeChat] ack sent to %s", reply_to[:20])
        except Exception as e:
            logger.warning("[WeChat] Failed to send ack: %s", e)
        await send_typing(client, creds, context_token, typing=True)

    # ── Session + history ─────────────────────────────────────────────────────
    from ethan.core.users import get_user_store
    from ethan.memory.session import get_session_store
    from ethan.memory.working import MemoryConfig, WorkingMemory

    user_id = get_user_store().get_admin_user_id()
    store = await get_session_store()

    session_id = await _get_or_create_session(store, chat_key)
    session_obj = await store.load(session_id)
    history = session_obj.messages if session_obj else []

    # Build context: last 5 turns (same as lark)；长期记忆由 system prompt 统一注入
    memory = WorkingMemory(config=MemoryConfig(hot_size=5))
    hist_ua = [m for m in history if m.role in ("user", "assistant")]
    pairs, i = [], 0
    while i < len(hist_ua) - 1:
        if hist_ua[i].role == "user" and hist_ua[i + 1].role == "assistant":
            pairs.append((hist_ua[i], hist_ua[i + 1]))
            i += 2
        else:
            i += 1
    for u, a in pairs[-memory.config.hot_size:]:
        memory.hot.extend([u, a])

    # Inject channel context so Agent doesn't try Lark tools
    agent_text = f"[当前渠道：微信]\n{text}"
    user_msg = Message(role="user", content=text)
    agent_user_msg = Message(role="user", content=agent_text)
    await store.save_message(session_id, user_msg)

    context_messages = memory.build_context() + [agent_user_msg]

    # ── Stream Agent ──────────────────────────────────────────────────────────
    from ethan.core.agent_factory import create_agent
    from ethan.interface.lark_tool_trace import sanitize_args_summary, sanitize_result_preview
    from ethan.tools.builtin.schedule import wechat_chat_id_var
    wechat_token = wechat_chat_id_var.set(reply_to)
    agent = create_agent(channel="wechat", user_id=user_id, toolset="full")
    final_answer = ""

    try:
        async for chunk in agent.stream_chat(context_messages):
            if isinstance(chunk, ToolEvent):
                if chunk.state == "start":
                    icon = _tool_icon(chunk.tool_name)
                    args = sanitize_args_summary(chunk.args_summary or "")
                    intent = chunk.intent or ""
                    line = f"{icon} {chunk.tool_name}"
                    if intent:
                        line += f" · {intent}"
                    elif args:
                        line += f" · {args}"
                    async with httpx.AsyncClient() as client:
                        try:
                            await send_text(client, creds, reply_to, context_token, line)
                        except Exception:
                            pass
                elif chunk.state == "done":
                    preview = sanitize_result_preview(chunk.result_preview or "")
                    if preview:
                        async with httpx.AsyncClient() as client:
                            try:
                                await send_text(client, creds, reply_to, context_token, f"✓ {preview[:300]}")
                            except Exception:
                                pass
                elif chunk.state == "error":
                    async with httpx.AsyncClient() as client:
                        try:
                            await send_text(client, creds, reply_to, context_token, f"✗ {chunk.result_preview or '工具调用失败'}")
                        except Exception:
                            pass
            elif isinstance(chunk, str):
                final_answer += chunk

    except Exception:
        logger.exception("[WeChat] Agent stream error for chat_key=%s", chat_key)
        wechat_chat_id_var.reset(wechat_token)
        return
    wechat_chat_id_var.reset(wechat_token)

    if not final_answer:
        logger.warning("[WeChat] stream_chat produced no text for chat_key=%s", chat_key)

    # ── Persist + reply ───────────────────────────────────────────────────────
    reply = final_answer.strip()
    if reply:
        final_response = Message(role="assistant", content=reply)
        await store.save_message(session_id, final_response)
    await store.touch(session_id)

    # A3: 微信渠道也触发后台记忆抽取（原来只有 Web/REPL 触发）
    try:
        from ethan.interface.routers.tasks import _maybe_consolidate
        task = asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, user_id))
        task.add_done_callback(lambda t: logger.error("consolidate failed", exc_info=t.exception()) if not t.cancelled() and t.exception() else None)
    except Exception:
        pass

    if reply:
        async with httpx.AsyncClient() as client:
            try:
                await send_text(client, creds, reply_to, context_token, reply)
            except Exception:
                logger.exception("[WeChat] Failed to send reply")
    else:
        logger.warning("[WeChat] no reply to send for chat_key=%s", chat_key)


async def _get_or_create_session(store: Any, chat_key: str) -> str:
    from ethan.core.config import get_config
    prefix = f"微信:{chat_key}:"
    sessions = await store.list_recent(limit=100)
    for s in sessions:
        if s.title and s.title.startswith(prefix):
            return s.id
    cfg = get_config()
    session = await store.create(cfg.defaults.model, source="wechat")
    await store.update_title(session.id, f"{prefix}{session.id[:8]}")
    return session.id
