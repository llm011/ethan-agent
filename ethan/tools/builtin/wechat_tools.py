"""WeChat message send tool — let Agent proactively send messages to the owner via WeChat."""
from __future__ import annotations

import logging

from ethan.tools.base import BaseTool

logger = logging.getLogger(__name__)


class WeChatMessageSendTool(BaseTool):
    """Send a WeChat message to the owner (the person who linked this bot)."""

    cacheable = False
    side_effect = True
    no_compress = True

    name = "wechat_message_send"
    description = (
        "Send a WeChat message to the owner (主人). "
        "Use this to proactively notify or reply to the user via WeChat. "
        "Only plain text is supported."
    )

    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Message text to send. Required.",
            },
        },
        "required": ["content"],
    }

    def consent_check(self, **kwargs) -> str | None:
        content = kwargs.get("content", "")
        preview = content[:60] + ("..." if len(content) > 60 else "")
        return f"Send WeChat message to owner: {preview}"

    async def run(self, content: str) -> str:
        if not content:
            return "Error: content is required"

        from ethan.core.config import get_config
        from ethan.interface.wechat_ilink import load_credentials, send_text

        cfg = get_config()
        owner_id = cfg.wechat.owner_user_id
        if not owner_id:
            return (
                "Error: owner_user_id not set. "
                "The owner's WeChat ID is auto-captured on first private message. "
                "Please send a message to the bot via WeChat first."
            )

        creds = load_credentials()
        if not creds:
            return "Error: WeChat not logged in. Run `ethan wechat login` first."

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await send_text(client, creds, owner_id, "", content)
            return "Message sent to owner via WeChat."
        except Exception as e:
            logger.exception("[WeChat] wechat_message_send failed")
            return f"Error sending WeChat message: {e}"
