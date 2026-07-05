"""飞书打字状态管理：THINKING 表情 add/remove + TypingState 上下文管理器。"""
from __future__ import annotations

import asyncio
import logging

from ethan.interface.lark_client import _lark_client

logger = logging.getLogger(__name__)


async def _send_reaction(message_id: str) -> str | None:
    """给消息添加 THINKING_FACE 表情，返回 reaction_id 以便后续删除。"""
    from lark_oapi.api.im.v1 import (
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
    )
    from lark_oapi.api.im.v1.model.emoji import Emoji

    client = _lark_client()
    if client is None:
        return None

    try:
        req = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(Emoji.builder().emoji_type("THINKING_FACE").build())
                .build()
            )
            .build()
        )
        resp = await asyncio.to_thread(client.im.v1.message_reaction.create, req)
        if resp.success() and resp.data:
            return resp.data.reaction_id
        logger.debug("Failed to add reaction to %s: code=%s msg=%s", message_id, resp.code, resp.msg)
        return None
    except Exception:
        logger.debug("Failed to add reaction to %s", message_id, exc_info=True)
        return None


async def _remove_reaction(message_id: str, reaction_id: str) -> None:
    """删除之前添加的 THINKING_FACE 表情。"""
    from lark_oapi.api.im.v1 import DeleteMessageReactionRequest

    client = _lark_client()
    if client is None:
        return

    try:
        req = (
            DeleteMessageReactionRequest.builder()
            .message_id(message_id)
            .reaction_id(reaction_id)
            .build()
        )
        await asyncio.to_thread(client.im.v1.message_reaction.delete, req)
    except Exception:
        pass


class TypingState:
    """管理飞书 THINKING 表情的生命周期（上下文管理器）。

    用法：
        async with TypingState(message_id) as ts:
            # 进入时自动加 THINKING 表情
            await do_work()
            # 可选：移到另一条消息
            await ts.move_to(new_message_id)
            # 可选：提前清理（如答案定稿后立刻移除，不必等退出）
            await ts.clear()
        # 退出时自动清理（如果还有表情）

    TypingState 封装了对 THINKING 表情的添加、移动和删除，确保在异常场景下也能正确清理。
    一个 TypingState 实例只跟踪一条消息上的一个表情；move_to 把表情从当前消息迁移到新消息。
    """

    def __init__(self, message_id: str):
        self.message_id = message_id
        self.reaction_id: str | None = None

    async def __aenter__(self) -> "TypingState":
        """进入上下文时添加 THINKING 表情。"""
        self.reaction_id = await _send_reaction(self.message_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出上下文时自动移除 THINKING 表情（如果还有）。

        异常情况下也会被调用，确保表情不会残留。捕获并吞掉清理过程中的异常，
        避免掩盖原本的异常。
        """
        if self.reaction_id:
            try:
                await _remove_reaction(self.message_id, self.reaction_id)
            except Exception:
                logger.debug("TypingState.__aexit__ cleanup failed", exc_info=True)
            finally:
                self.reaction_id = None

    async def move_to(self, new_message_id: str) -> None:
        """把 THINKING 表情从当前消息移到新消息。

        先移除旧消息的表情（如果有），再给新消息添加表情。任何环节失败都不抛异常——
        旧表情删除失败不会阻断新表情的添加；新表情添加失败只是没有指示器，不影响主流程。
        """
        old_msg_id = self.message_id
        old_reaction_id = self.reaction_id
        self.message_id = new_message_id
        self.reaction_id = None

        # 移除旧表情（若有）
        if old_reaction_id:
            await _remove_reaction(old_msg_id, old_reaction_id)

        # 给新消息加表情
        self.reaction_id = await _send_reaction(new_message_id)

    async def clear(self) -> None:
        """立刻移除当前消息上的表情（如果还有）。

        用于在退出上下文之前提前清理——例如答案卡片定稿后立刻移除 THINKING，
        不必等到函数返回。清理后 reaction_id 置 None，后续 __aexit__ 不会重复清理。
        """
        if self.reaction_id:
            try:
                await _remove_reaction(self.message_id, self.reaction_id)
            except Exception:
                logger.debug("TypingState.clear failed", exc_info=True)
            finally:
                self.reaction_id = None
