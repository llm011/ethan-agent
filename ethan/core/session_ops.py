"""Session 级操作（跨渠道复用）。

目前提供 ``compact_session``：用廉价模型把会话历史压成摘要，替换存储，释放上下文。
TUI / Web 后端 / 飞书 / 微信都调这一个函数，避免逻辑重复。
"""
from __future__ import annotations

import logging

from ethan.providers.base import Message

logger = logging.getLogger(__name__)


def _split_keep_recent(messages: list[Message], keep_pairs: int) -> tuple[list[Message], list[Message]]:
    """把消息切成 (保留的最近 keep_pairs 轮, 其余待压缩)。

    一轮 = 一对 (user, assistant)。从末尾往前数 keep_pairs 个完整轮次归入「保留」，
    其余全部归入「待压缩」。中间无法配对的消息（如连续 user）归入待压缩。
    """
    # 从末尾向前找 keep_pairs 个 user→assistant 配对的边界
    pairs_found = 0
    split_idx = len(messages)
    for i in range(len(messages) - 2, -1, -1):
        if messages[i].role == "user" and messages[i + 1].role == "assistant":
            pairs_found += 1
            if pairs_found == keep_pairs:
                split_idx = i
                break
        # 遇到非配对就继续往前
    if pairs_found == 0:
        # 没有完整轮次可保留 → 全部压缩
        return [], list(messages)
    return list(messages[split_idx:]), list(messages[:split_idx])


async def compact_session(store, session_id: str, model: str, keep_last_pairs: int = 1) -> str:
    """压缩 session 历史：保留最后 keep_last_pairs 轮原文，其余压成一条摘要替换存储。

    返回摘要文本（供各 surface 回显给用户）。对话太短或无内容时返回提示串（不抛异常）。
    复用 Consolidator.compress（含重要性打分 + 廉价模型）。
    """
    from ethan.memory.consolidator import Consolidator

    session = await store.load(session_id)
    if not session:
        return "会话不存在，无法压缩。"
    # 只看 user/assistant 文本消息
    msgs = [m for m in session.messages if m.role in ("user", "assistant") and m.content]
    if len(msgs) < 3:
        return "对话太短，无需压缩。"

    kept, to_compress = _split_keep_recent(msgs, keep_last_pairs)
    if not to_compress:
        return "没有可压缩的历史。"

    consolidator = Consolidator(main_model=model)
    try:
        summary = await consolidator.compress(to_compress)
    except Exception:
        logger.exception("compact_session: compress failed for %s", session_id)
        return "压缩失败，请稍后再试。"

    summary = (summary or "").strip()
    if not summary:
        return "压缩失败，请稍后再试。"

    # 替换为：[对话摘要] user + ack assistant + 保留的最近几轮原文
    summary_pair = [
        Message(role="user", content=f"[对话摘要] {summary}"),
        Message(role="assistant", content="好的，我已了解之前的对话内容。"),
    ]
    await store.replace_messages(session_id, summary_pair + kept)
    logger.info("compact_session: %s compressed %d msgs → summary", session_id, len(to_compress))
    return summary
