"""工具结果进模型上下文前的「预算管控」——防止重工具任务把上下文撑爆。

背景（真实 bug）：agent 主循环把每个 tool result 全量 append 到 working、每轮回灌给模型。
像 code review 这种任务，单个 mr diff（238K）/ comments（102K）/ CI log 动辄几十万字，
且这些多是 no_compress 工具（shell）的输出，不走 result_compressor 摘要，
几轮滚下来上下文冲到几百万 token，远超任何模型窗口——最后该出总结的那一轮模型面对
超限上下文直接返回空，整轮白干（29 个工具全 done 却无总结）。

本模块在 tool result 进 working 前做两件事：
  1. 单条结果硬封顶 MAX_TOOL_RESULT_CHARS：超长就截断 + 标注省略字数与查看方式。
     —— 任何模型都吃不下几十万字的单条结果；超了就该让模型用 file_read offset/limit
        或重跑命令 + grep/head 按需取片段（Claude Code 等也是这么做的）。
  2. 全量预算 CONTEXT_BUDGET_CHARS：累计超出就从最旧的 tool result 开始压成小摘要，
     保留最近的完整——agent loop 里最近的上下文最重要，旧的压成提示即可。

只动 role=='tool' 的消息，不碰 user/assistant/system；通过替换 working 里的 Message
引用实现（不就地改写历史 Message.content，避免污染调用方共享的 session 内存对象）。

阈值是经验默认值，后续可上提到 config。
"""
from __future__ import annotations

from ethan.providers.base import Message

# 单条 tool result 在上下文里的上限（≈5K tokens）。超出即截断 + 标注。
MAX_TOOL_RESULT_CHARS = 20000
# working 里所有 tool result 合计的上限（≈25K tokens，给 200K 窗口的模型留足余量）。
CONTEXT_BUDGET_CHARS = 100000
# 被预算淘汰的旧结果压成多长（够提醒模型「这步做过什么」即可，≈150 tokens）。
EVICTED_STUB_CHARS = 600

_TRUNCATION_NOTE = (
    "\n\n[…内容过长已截断，省略 {omitted} 字。"
    "如需完整内容请用 file_read 的 offset/limit 分段读取，或重跑对应命令后用 grep/head 取需要的片段…]"
)
_EVICTED_NOTE = "[…旧工具结果已折叠以节省上下文，省略 {omitted} 字…]\n"


def _truncated_copy(msg: Message, keep: int, *, evicted: bool = False) -> Message:
    """复制一条 tool 消息，把 content 截到 keep 字并加标注（不改原对象）。"""
    original = msg.content or ""
    omitted = max(0, len(original) - keep)
    if omitted == 0:
        return msg
    if evicted:
        body = _EVICTED_NOTE.format(omitted=omitted) + original[:keep]
    else:
        body = original[:keep] + _TRUNCATION_NOTE.format(omitted=omitted)
    return Message(
        role=msg.role, content=body,
        tool_calls=msg.tool_calls, tool_call_id=msg.tool_call_id,
        usage=msg.usage, created_at=msg.created_at,
        tool_steps=msg.tool_steps, thought=msg.thought,
        quote=msg.quote, a2ui=msg.a2ui, mcp_apps=msg.mcp_apps,
    )


def enforce_context_budget(working: list[Message]) -> None:
    """就地（按引用替换）管控 working 里的 tool result 体积。

    1. 每条 tool 消息封顶 MAX_TOOL_RESULT_CHARS。
    2. 合计超 CONTEXT_BUDGET_CHARS 时，从最旧开始压成 EVICTED_STUB_CHARS 摘要，直到回到预算内。

    幂等：已是摘要的旧消息不会再被重复截断（长度已 ≤ 阈值）。
    """
    if not working:
        return
    # (1) 单条封顶
    for i, m in enumerate(working):
        if m.role == "tool" and m.content and len(m.content) > MAX_TOOL_RESULT_CHARS:
            working[i] = _truncated_copy(m, MAX_TOOL_RESULT_CHARS, evicted=False)
    # (2) 全量预算：从最旧开始淘汰
    tool_idx = [i for i, m in enumerate(working) if m.role == "tool"]
    total = sum(len(working[i].content or "") for i in tool_idx)
    if total <= CONTEXT_BUDGET_CHARS:
        return
    for i in tool_idx:  # 列表顺序即时间顺序，最旧在前
        if total <= CONTEXT_BUDGET_CHARS:
            break
        m = working[i]
        cur = len(m.content or "")
        if cur <= EVICTED_STUB_CHARS:
            continue
        working[i] = _truncated_copy(m, EVICTED_STUB_CHARS, evicted=True)
        # 用截断后的真实长度算 delta（含标注 overhead），避免累计偏差导致提前停手
        total -= cur - len(working[i].content)
