"""工具结果进模型上下文前的「预算管控」——防止重工具任务把上下文撑爆。

背景（真实 bug）：agent 主循环把每个 tool result 全量 append 到 working、每轮回灌给模型。
像 code review 这种任务，单个 mr diff（238K）/ comments（102K）/ CI log 动辄几十万字，
且这些多是 no_compress 工具（shell）的输出，不走 result_compressor 摘要，
几轮滚下来上下文冲到几百万 token，远超任何模型窗口——最后该出总结的那一轮模型面对
超限上下文直接返回空，整轮白干（29 个工具全 done 却无总结）。

本模块在 tool result 进 working 前做两件事：
  1. 单条结果硬封顶 MAX_TOOL_RESULT_CHARS：超长就截断 + 标注省略字数与查看方式。
     —— 任何模型都吃不下几十万字的单条结果；超了就该让模型用 file_read offset/limit
        或重跑命令 + grep/head 取需片段（Claude Code 等也是这么做的）。
  2. 全量预算 CONTEXT_BUDGET_CHARS：累计超出就从最旧的 tool result 开始压成小摘要，
     保留最近的完整——agent loop 里最近的上下文最重要，旧的压成提示即可。

另外提供 compress_previous_round_tools()：对上一轮的 web_search/web_fetch 结果
做分级压缩（search 压成 title+url，fetch 存文件替换为指针），在不损失当前轮信息
的前提下大幅减少历史 tool result 的重复发送。

只动 role=='tool' 的消息，不碰 user/assistant/system；通过替换 working 里的 Message
引用实现（不就地改写历史 Message.content，避免污染调用方共享的 session 内存对象）。

阈值是经验默认值，后续可上提到 config。
"""
from __future__ import annotations

import os
import re

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
_EVICTED_NOTE = (
    "[…旧工具结果已折叠（省略 {omitted} 字），以节省上下文空间。"
    "若需回顾该工具的完整输出，可重新调用相同工具，或用 rg_search/file_read 检索相关内容。]\n"
)


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
    2. 合计超 CONTEXT_BUDGET_CHARS 时，保留最近 3 条 tool 消息不动，
       对其余可驱逐消息优先淘汰大块结果（按内容长度降序），压成 EVICTED_STUB_CHARS 摘要。

    幂等：已是摘要的旧消息不会再被重复截断（长度已 ≤ 阈值）。
    """
    if not working:
        return
    # (1) 单条封顶
    for i, m in enumerate(working):
        if m.role == "tool" and m.content and len(m.content) > MAX_TOOL_RESULT_CHARS:
            working[i] = _truncated_copy(m, MAX_TOOL_RESULT_CHARS, evicted=False)
    # (2) 全量预算：优先淘汰大块旧结果，保留最近 3 条不被驱逐
    tool_idx = [i for i, m in enumerate(working) if m.role == "tool"]
    total = sum(len(working[i].content or "") for i in tool_idx)
    if total <= CONTEXT_BUDGET_CHARS:
        return
    # 保留最近 3 条 tool 消息不被驱逐（最新上下文最重要）
    evictable = tool_idx[:-3] if len(tool_idx) > 3 else []
    # 优先淘汰大块结果（> 2000 字的先淘汰），同长度再按时间顺序（索引小的先淘汰）
    evictable_sorted = sorted(evictable, key=lambda i: (-len(working[i].content or ""), i))
    for i in evictable_sorted:
        if total <= CONTEXT_BUDGET_CHARS:
            break
        m = working[i]
        cur = len(m.content or "")
        if cur <= EVICTED_STUB_CHARS:
            continue
        working[i] = _truncated_copy(m, EVICTED_STUB_CHARS, evicted=True)
        # 用截断后的真实长度算 delta（含标注 overhead），避免累计偏差导致提前停手
        total -= cur - len(working[i].content)


# ── 上一轮工具结果分级压缩 ──────────────────────────────────────────────

_COMPRESSED_MARKER = "[搜索结果已压缩"
_FETCH_OFFLOADED_MARKER = "[fetch结果已存文件"


def _find_tool_name(working: list[Message], tool_idx: int) -> str:
    """根据 tool_call_id 反查对应的工具名。"""
    target_id = working[tool_idx].tool_call_id
    if not target_id:
        return ""
    for j in range(tool_idx - 1, -1, -1):
        msg = working[j]
        if msg.is_tool_call and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.id == target_id:
                    return tc.name
    return ""


def _compress_search_content(content: str) -> str:
    """把 web_search 的多结果文本压成 title + url 列表。

    原始格式（web_search._build_result）：
        **[source] title** [date]
        snippet

        url

    压缩后：
        [搜索结果已压缩为标题+URL列表]
        - title | url
    """
    blocks = content.split("\n\n")
    lines: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("Found ~"):
            continue
        parts = block.split("\n")
        title_line = parts[0] if parts else ""
        url_line = parts[-1] if len(parts) > 1 else ""
        # 去掉 ** 和 [source] 前缀
        title = re.sub(r"^\*\*\[.*?\]\s*", "", title_line).replace("**", "").strip()
        url = url_line.strip()
        if url.startswith("http"):
            lines.append(f"- {title} | {url}")
    if not lines:
        return content[:200] + "…" if len(content) > 200 else content
    return _COMPRESSED_MARKER + "为标题+URL列表]\n" + "\n".join(lines)


def _offload_fetch_content(content: str, session_id: str, tool_call_id: str) -> str:
    """把 web_fetch 结果写入文件，返回文件指针提示。"""
    dir_path = f"/tmp/ethan/{session_id}"
    os.makedirs(dir_path, exist_ok=True)
    file_path = f"{dir_path}/{tool_call_id}.md"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        return content  # 写文件失败则不压缩，保留原文
    return (
        f"{_FETCH_OFFLOADED_MARKER}: {file_path}]\n"
        f"如需引用该页面内容，用 file_read 读取 {file_path}。"
    )


def _replace_content(msg: Message, new_content: str) -> Message:
    """复制一条 tool 消息，替换 content（不改原对象）。"""
    return Message(
        role=msg.role, content=new_content,
        tool_calls=msg.tool_calls, tool_call_id=msg.tool_call_id,
        usage=msg.usage, created_at=msg.created_at,
        tool_steps=msg.tool_steps, thought=msg.thought,
        quote=msg.quote, a2ui=msg.a2ui, mcp_apps=msg.mcp_apps,
    )


def compress_previous_round_tools(working: list[Message], session_id: str = "") -> None:
    """对上一轮的 web_search/web_fetch 结果做分级压缩。

    只压缩「旧」tool result（最后一个 assistant 消息之前的），当前轮保持完整。
    - web_search: 压成 title+url 列表（丢 snippet，模型已看过、后续轮通常只需 URL）
    - web_fetch: 写入 /tmp/ethan/<session_id>/ 文件，替换为文件指针
      （模型刚拿到的当前轮保持全文；下一轮起只保留路径，需要时 file_read 取回）
    """
    if not working or not session_id:
        return

    # 找最后一条 assistant 消息（不论是否带 tool_calls），它之前的 tool result 都是「旧的」
    last_asst_idx = -1
    for i in range(len(working) - 1, -1, -1):
        if working[i].role == "assistant":
            last_asst_idx = i
            break
    if last_asst_idx <= 0:
        return

    for i in range(last_asst_idx):
        msg = working[i]
        if msg.role != "tool":
            continue
        content = msg.content or ""
        if not content:
            continue
        # 已压缩过的跳过
        if _COMPRESSED_MARKER in content or _FETCH_OFFLOADED_MARKER in content:
            continue

        tool_name = _find_tool_name(working, i)
        if tool_name == "web_search":
            working[i] = _replace_content(msg, _compress_search_content(content))
        elif tool_name == "web_fetch" and len(content) > 500:
            tc_id = msg.tool_call_id or f"tool_{i}"
            working[i] = _replace_content(msg, _offload_fetch_content(content, session_id, tc_id))
