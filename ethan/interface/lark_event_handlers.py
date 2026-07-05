"""飞书事件处理（已读、reaction、卡片按钮回调）。

轻量 stub handler，日志记录 + 留扩展点。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _handle_message_read(event_data: dict) -> None:
    reader_id = (
        event_data.get("reader_id")
        or event_data.get("reader_open_id")
        or event_data.get("open_id")
        or ""
    )
    message_id = event_data.get("message_id", "")
    chat_id = event_data.get("chat_id", "")
    logger.info("[Lark] message read: chat=%s msg=%s by=%s", chat_id, message_id, reader_id)


async def _handle_reaction(event_data: dict) -> None:
    reaction_type = event_data.get("reaction_type", "")
    operator_id = (
        event_data.get("operator_id")
        or event_data.get("operator_open_id")
        or event_data.get("open_id")
        or ""
    )
    message_id = event_data.get("message_id", "")
    chat_id = event_data.get("chat_id", "")
    logger.info(
        "[Lark] reaction created: chat=%s msg=%s emoji=%s by=%s",
        chat_id, message_id, reaction_type, operator_id,
    )


async def _handle_card_action(event_data: dict) -> None:
    action_tag = event_data.get("action_tag", "")
    action_value_raw = event_data.get("action_value", "")
    action_name = event_data.get("action_name", "")
    form_value = event_data.get("form_value", {})
    message_id = event_data.get("message_id", "")
    chat_id = event_data.get("chat_id", "")
    open_id = event_data.get("open_id", "")
    token = event_data.get("token", "")

    import json as _json
    try:
        action_value = _json.loads(action_value_raw) if action_value_raw else {}
    except (ValueError, TypeError):
        action_value = {"_raw": action_value_raw}

    logger.info(
        "[Lark] card action: chat=%s msg=%s tag=%s name=%s value=%s form=%s by=%s",
        chat_id, message_id, action_tag, action_name, action_value, form_value, open_id,
    )

    cmd = (action_value.get("cmd") if isinstance(action_value, dict) else "") or ""
    if cmd == "test" and chat_id:
        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "✅ card.action.trigger 已打通"},
                "template": "green",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": (
                            f"收到按钮回调：`tag={action_tag}` `name={action_name}`\n"
                            f"点击者：`{open_id}`\n"
                            f"原消息：`{message_id}`\n"
                            "事件链路 OK，后续可据 action_value 路由到具体工作流。"
                        ),
                    }
                ]
            },
        }
        from ethan.interface.lark_send import _send_interactive_card
        await _send_interactive_card(chat_id, card)
        logger.debug(
            "[Lark] card action test echo sent: chat=%s token_present=%s",
            chat_id, bool(token),
        )
