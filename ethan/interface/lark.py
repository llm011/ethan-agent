"""Feishu (Lark) bot webhook integration.

Event Subscription URL: https://your-domain:8900/lark/webhook

Handles:
- URL verification challenge (type=url_verification)
- im.message.receive_v1 — new text message from user
  * Looks up or creates a session keyed by open_chat_id
  * Runs Agent.chat() and replies in the same chat thread
"""
import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ethan.core.config import get_config
from ethan.core.agent import Agent
from ethan.memory.session import SessionStore
from ethan.providers.base import Message
from ethan.skills.registry import SkillRegistry
from ethan.tools.registry import ToolRegistry
from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.builtin.schedule import lark_chat_id_var

logger = logging.getLogger(__name__)

lark_router = APIRouter()


def _get_lark_client() -> lark.Client | None:
    """Build an authenticated Lark SDK client from config."""
    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id or not lark_cfg.app_secret:
        logger.warning("Lark app_id / app_secret not configured — replies disabled")
        return None
    return (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )


def _get_lark_user_id() -> str:
    """Lark 渠道无用户登录上下文，MVP 固定归到 admin 用户。"""
    from ethan.core.users import get_user_store
    return get_user_store().get_admin_user_id()


def _create_agent(user_id: str = "") -> Agent:
    from ethan.core.paths import ensure_user_dirs
    uid = user_id or _get_lark_user_id()
    ensure_user_dirs(uid)
    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())
    skills = SkillRegistry(user_id=uid)
    skills.load()
    return Agent(tool_registry=registry, skill_registry=skills, channel="lark", user_id=uid)


async def _get_or_create_session(store: SessionStore, chat_id: str) -> str:
    """Return the most recent session ID for *chat_id*, or create a new one."""
    # Use session title prefix to track Lark sessions
    title_prefix = f"lark:{chat_id}:"
    sessions = await store.list_recent(limit=100)
    for s in sessions:
        if s.title and s.title.startswith(title_prefix):
            return s.id

    config = get_config()
    session = await store.create(config.defaults.model)
    # Tag the session title so we can find it next time
    await store.update_title(session.id, f"{title_prefix}{session.id[:8]}")
    return session.id


async def _send_lark_reply(client: lark.Client, chat_id: str, text: str) -> None:
    """Send a plain-text reply to the given Feishu chat."""
    content = json.dumps({"text": text}, ensure_ascii=False)
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(content)
            .build()
        )
        .build()
    )
    resp = client.im.v1.message.create(req)
    if not resp.success():
        logger.error(
            "Lark send message failed: code=%s msg=%s", resp.code, resp.msg
        )


async def _add_reaction(client: lark.Client, message_id: str, emoji: str = "THINKING_FACE") -> None:
    """Add a reaction emoji to a message to signal receipt."""
    import asyncio
    try:
        from lark_oapi.api.im.v1 import CreateMessageReactionRequest, CreateMessageReactionRequestBody
        from lark_oapi.api.im.v1.model import EmojiType
        req = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(EmojiType.builder().emoji_type(emoji).build())
                .build()
            )
            .build()
        )
        await asyncio.to_thread(client.im.v1.message_reaction.create, req)
    except Exception:
        logger.debug("Failed to add reaction to message %s", message_id, exc_info=True)


@lark_router.post("/lark/webhook")
async def lark_webhook(request: Request):
    body = await request.json()

    # ── 1. URL verification challenge ────────────────────────────
    if body.get("type") == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    # ── 2. Event callback ─────────────────────────────────────────
    event_type = (
        body.get("header", {}).get("event_type")
        or body.get("event", {}).get("type", "")
    )

    if event_type != "im.message.receive_v1":
        # Silently acknowledge any other event
        return JSONResponse({"code": 0})

    event = body.get("event", {})
    msg = event.get("message", {})
    msg_type = msg.get("message_type", "")

    if msg_type != "text":
        # Non-text messages (images, files, etc.) — ignore gracefully
        return JSONResponse({"code": 0})

    # Extract text content
    try:
        msg_content = json.loads(msg.get("content", "{}"))
        text = msg_content.get("text", "").strip()
    except (json.JSONDecodeError, AttributeError):
        text = ""

    if not text:
        return JSONResponse({"code": 0})

    chat_id: str = msg.get("chat_id", "")
    message_id: str = msg.get("message_id", "")
    if not chat_id:
        logger.warning("Lark event missing chat_id, skipping")
        return JSONResponse({"code": 0})

    # ── 3. Add "thinking" reaction immediately to signal receipt ──
    client = _get_lark_client()
    if client and message_id:
        await _add_reaction(client, message_id, "THINKING_FACE")

    # ── 4. Run Agent ──────────────────────────────────────────────
    from ethan.core.paths import user_sessions_db_path
    lark_user_id = _get_lark_user_id()
    store = SessionStore(db_path=user_sessions_db_path(lark_user_id))
    await store.init()

    try:
        session_id = await _get_or_create_session(store, chat_id)

        user_msg = Message(role="user", content=text)
        await store.save_message(session_id, user_msg)

        # 注入 chat_id，让 ScheduleCreateTool 创建定时任务时能读到来源渠道
        token = lark_chat_id_var.set(chat_id)
        try:
            agent = _create_agent(user_id=lark_user_id)
            response = await agent.chat([user_msg])
        finally:
            lark_chat_id_var.reset(token)

        await store.save_message(session_id, response)
        await store.touch(session_id)
    except Exception:
        logger.exception("Agent error while handling Lark message")
        await store.close()
        return JSONResponse({"code": 0})

    await store.close()

    # ── 5. Reply via Lark API ─────────────────────────────────────
    if client and response.content:
        try:
            await _send_lark_reply(client, chat_id, response.content)
        except Exception:
            logger.exception("Failed to send Lark reply")

    return JSONResponse({"code": 0})
