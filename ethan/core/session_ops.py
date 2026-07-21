"""Session 级操作（跨渠道复用）。

提供：
- ``compact_session``：用廉价模型把会话历史压成摘要，替换存储，释放上下文。
- ``summary_session``：用模型对当前对话生成结构化总结（只读，不改会话历史）。

TUI / Web 后端 / 飞书 / 微信都调这些函数，避免逻辑重复。
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


# ── /summary：结构化总结当前对话（只读，不改历史） ───────────────────

_SUMMARY_SYSTEM = "你是一个专业的内容总结助手，按照用户要求的格式输出结构化总结。"

_SUMMARY_PROMPT = """\
请按照以下格式，对下面的对话内容做结构化总结：

格式要求：
首先，先发一句最核心的观点，这里用一句话讲明白。

## 背景
一句话概括文章背景/问题。

## 核心洞察
1. **[洞察名称]**
   - 关键词:短句1;短句2。
   - 数据:具体数字。
   - 证据:原文引用。

2. **[洞察名称]**（如有多个）
   - 关键词:短句1;短句2。
   - 链条:步骤1 → 步骤2。

## 子叙事
1. **[子视角]**
   - 详情

---
用最直白的话，把最重要的抓出来，不讲废话。

以下是对话内容：
{conversation}
"""


async def summary_session(store, session_id: str, model: str) -> str:
    """对当前对话生成结构化总结（只读，不修改会话历史）。

    返回总结文本。对话太短或无内容时返回提示串。
    """
    session = await store.load(session_id)
    if not session:
        return "会话不存在，无法总结。"
    msgs = [m for m in session.messages if m.role in ("user", "assistant") and m.content]
    if len(msgs) < 2:
        return "对话太短，先聊几句再 /summary 吧~"

    conversation = "\n".join(
        f"{'用户' if m.role == 'user' else 'AI'}: {m.content}"
        for m in msgs
    )

    # 用主模型做总结（质量优先）
    from ethan.providers.manager import create_provider
    provider = await create_provider(model)
    try:
        resp = await provider.chat(
            [Message(role="user", content=_SUMMARY_PROMPT.format(conversation=conversation))],
            system=_SUMMARY_SYSTEM,
        )
    except Exception:
        logger.exception("summary_session: LLM call failed for %s", session_id)
        return "总结失败，请稍后再试。"

    result = (resp.content or "").strip()
    if not result:
        return "总结失败，请稍后再试。"
    return result
