"""WeChat iLink bot event loop — receive messages, run Agent, reply.

Architecture mirrors lark_events.py:
  - start_wechat_listener() / stop_wechat_listener() called from api.py lifespan
  - _bot_loop() long-polls iLink, dispatches to _handle_message()
  - _handle_message() looks up / creates a session, runs Agent.chat(), sends reply

Credentials are persisted to ~/.ethan/memory/wechat_credentials.json by
wechat_ilink.login_via_qrcode().  Re-login is triggered automatically when the
token is rejected (HTTP 401/403 or iLink ret=100).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_listeners: list[asyncio.Task] = []
_RETRY_DELAY_S = 2
_MAX_CONSECUTIVE_ERRORS = 5
_BACKOFF_S = 30


def _wechat_configured() -> bool:
    from ethan.interface.wechat_ilink import load_credentials
    return load_credentials() is not None


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
        WeChatCredentials,
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


async def _handle_message(msg: dict[str, Any], creds: "WeChatCredentials") -> None:  # noqa: F821
    """Process a single iLink message, run Agent, reply."""
    from ethan.interface.wechat_ilink import send_text, send_typing
    import httpx

    # Deduplicate by message_id
    msg_id = str(msg.get("message_id") or msg.get("msg_id") or "")
    if msg_id and msg_id in _seen_msg_ids:
        return
    if msg_id:
        _seen_msg_ids.add(msg_id)
        if len(_seen_msg_ids) > 2000:
            _seen_msg_ids.clear()

    # iLink message_type: 1=user, 2=bot — skip our own outgoing messages
    message_type = msg.get("message_type")
    if message_type == 2:
        return

    # Extract text from item_list[0].text_item.text (actual iLink structure)
    text = ""
    item_list = msg.get("item_list") or []
    for item in item_list:
        if item.get("type") == 1:  # ITEM_TEXT
            text_item = item.get("text_item") or {}
            text = (text_item.get("text") or "").strip()
            if text:
                break

    if not text:
        logger.debug("[WeChat] skipping non-text or empty message: msg_type=%s", message_type)
        return

    sender = msg.get("from_user_id") or ""
    group_id = msg.get("group_id") or ""
    context_token = msg.get("context_token") or ""
    chat_key = group_id or sender or msg_id[:16]

    if not context_token:
        logger.warning("[WeChat] message has no context_token — cannot reply: %s", msg)
        return

    logger.info("[WeChat] msg from=%s group=%s text=%r", sender[:20], group_id, text[:80])

    # Send typing indicator
    async with httpx.AsyncClient() as client:
        await send_typing(client, creds, context_token, typing=True)

    # ── Session + Agent ───────────────────────────────────────────────────────
    from ethan.core.agent_factory import create_agent
    from ethan.core.config import get_config
    from ethan.core.paths import user_sessions_db_path
    from ethan.core.users import get_user_store
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    user_id = get_user_store().get_admin_user_id()
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()

    try:
        session_id = await _get_or_create_session(store, chat_key)
        user_msg = Message(role="user", content=text)
        await store.save_message(session_id, user_msg)

        agent = create_agent(channel="wechat", user_id=user_id, toolset="full")
        response = await agent.chat([user_msg])

        await store.save_message(session_id, response)
        await store.touch(session_id)
    except Exception:
        logger.exception("[WeChat] Agent error for chat_key=%s", chat_key)
        await store.close()
        return

    await store.close()

    # ── Reply ─────────────────────────────────────────────────────────────────
    reply_text = response.content or ""
    if reply_text:
        async with httpx.AsyncClient() as client:
            try:
                await send_text(client, creds, sender, context_token, reply_text)
            except Exception:
                logger.exception("[WeChat] Failed to send reply")


async def _get_or_create_session(store: "SessionStore", chat_key: str) -> str:  # noqa: F821
    from ethan.core.config import get_config
    prefix = f"wechat:{chat_key}:"
    sessions = await store.list_recent(limit=100)
    for s in sessions:
        if s.title and s.title.startswith(prefix):
            return s.id
    cfg = get_config()
    session = await store.create(cfg.defaults.model)
    await store.update_title(session.id, f"{prefix}{session.id[:8]}")
    return session.id
