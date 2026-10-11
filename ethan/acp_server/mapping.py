"""纯映射函数：ethan 的内容块/流事件 → ACP schema 对象。

全部函数无副作用、不做 IO，是协议正确性的核心（单测覆盖重点）。

实测踩坑（SDK agent-client-protocol 0.12.1，勿删）：
1. 所有 session_update 事件必须带判别字段 ``sessionUpdate=...``，
   漏了会被 agent 侧 pydantic 校验拒掉（客户端收到 Invalid params）。
2. ToolKind / ToolCallStatus 是 Literal 字符串，直接传 str
   （``ToolKind.execute`` 这类属性访问不存在）。
3. TextContentBlock 等 union 成员必须显式 ``type="text"``。
"""
from __future__ import annotations

import base64
import binascii

from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    ContentToolCallContent,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)

# ── ToolKind 映射：ethan 工具名/分类 → ACP tool kind ──────────────────

_TOOL_KIND_BY_NAME: dict[str, str] = {
    "file_read": "read",
    "file_list": "read",
    "skill_read": "read",
    "skill_list": "read",
    "knowledge_read": "read",
    "plan_read": "read",
    "doc_list": "read",
    "config_get": "read",
    "list_secrets": "read",
    "get_secret": "read",
    "recall_memory": "read",
    "file_write": "edit",
    "file_edit": "edit",
    "memory_write": "edit",
    "knowledge_add": "edit",
    "knowledge_edit": "edit",
    "profile_update": "edit",
    "plan_write": "edit",
    "plan_update": "edit",
    "procedure_write": "edit",
    "doc_save": "edit",
    "config_set": "edit",
    "set_secret": "edit",
    "shell": "execute",
    "browser": "execute",
    "browser_session": "execute",
    "browser_tab": "execute",
    "browser_page": "execute",
    "desktop_notify": "execute",
    "desktop_countdown": "execute",
    "deliver_file": "move",
    "rg_search": "search",
    "fd_find": "search",
    "web_search": "fetch",
    "image_search": "fetch",
    "web_fetch": "fetch",
    "weather": "fetch",
    "ask_user": "think",
    "decide": "think",
    "wait_for_user": "think",
}


def tool_kind(tool_name: str) -> str:
    """ethan 工具名 → ACP ToolKind Literal 字符串。未知工具归 other。"""
    return _TOOL_KIND_BY_NAME.get(tool_name, "other")


# ── 工具调用状态映射：ToolEvent.state → ACP ToolCallStatus ────────────

def tool_status(event_state: str) -> str:
    """ethan ToolEvent.state（start/done/error）→ ACP status Literal。"""
    if event_state == "start":
        return "in_progress"
    if event_state == "error":
        return "failed"
    return "completed"


# ── 内容块转换：ACP prompt 内容块 → ethan text / images ───────────────

def blocks_to_text_and_images(blocks: list) -> tuple[str, list[dict]]:
    """把 ACP prompt 内容块列表转成 (text, images)。

    - TextContentBlock → 拼接 text
    - ImageContentBlock（base64 data）→ images [{"data", "media_type"}]，与
      Message.images 的格式对齐
    - Audio / Resource / EmbeddedResource → 目前不支持，忽略并记入 text 占位
      （客户端会收到说明文字，不至于静默丢失）
    """
    texts: list[str] = []
    images: list[dict] = []
    skipped: list[str] = []
    for block in blocks:
        btype = getattr(block, "type", None)
        if btype == "text":
            text = getattr(block, "text", "")
            if text:
                texts.append(text)
        elif btype == "image":
            data = getattr(block, "data", "") or ""
            mime = getattr(block, "mime_type", "") or "image/png"
            if data:
                images.append({"data": data, "media_type": mime})
        elif btype is not None:
            skipped.append(btype)
    if skipped:
        texts.append(f"[Unsupported content block(s) ignored: {', '.join(sorted(set(skipped)))}]")
    return "\n".join(texts), images


def image_blocks_from_message_images(images: list[dict]) -> list:
    """ethan Message.images → ACP ImageContentBlock 列表（session/load 历史重放用）。

    数据异常（缺 data / base64 损坏）的条目跳过，不抛异常。
    """
    from acp.schema import ImageContentBlock

    out = []
    for img in images or []:
        data = img.get("data") or ""
        mime = img.get("media_type") or "image/png"
        if not data:
            continue
        try:
            base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            continue
        out.append(ImageContentBlock(type="image", data=data, mime_type=mime))
    return out


# ── session_update 事件构造（全部带 sessionUpdate 判别字段）───────────

def message_chunk(text: str) -> AgentMessageChunk:
    """正文增量。"""
    return AgentMessageChunk(sessionUpdate="agent_message_chunk", content=TextContentBlock(type="text", text=text))


def thought_chunk(text: str) -> AgentThoughtChunk:
    """思考增量。"""
    return AgentThoughtChunk(sessionUpdate="agent_thought_chunk", content=TextContentBlock(type="text", text=text))


def user_chunk(text: str) -> UserMessageChunk:
    """历史重放时的用户消息块。"""
    return UserMessageChunk(sessionUpdate="user_message_chunk", content=TextContentBlock(type="text", text=text))


def tool_call_start(tool_call_id: str, tool_name: str, args_summary: str) -> ToolCallStart:
    """工具调用开始。title 取「工具名 + 参数摘要」，与 Web 时间线语义一致。"""
    title = f"{tool_name}: {args_summary}" if args_summary else tool_name
    return ToolCallStart(
        sessionUpdate="tool_call",
        toolCallId=tool_call_id,
        title=title[:200],
        kind=tool_kind(tool_name),
        status="in_progress",
    )


def tool_call_update(event_state: str, tool_call_id: str, tool_name: str, result_preview: str) -> ToolCallProgress:
    """工具调用状态更新（完成/失败）。result 摘要放进 content 文本。

    注意 content 元素结构：ContentToolCallContent(type="content",
    content=<单个内容块>)，不是裸的 TextContentBlock 列表。
    """
    status = tool_status(event_state)
    content = []
    if result_preview:
        content = [
            ContentToolCallContent(type="content", content=TextContentBlock(type="text", text=result_preview[:2000]))
        ]
    return ToolCallProgress(
        sessionUpdate="tool_call_update",
        toolCallId=tool_call_id,
        kind=tool_kind(tool_name),
        status=status,
        content=content,
    )


def tool_call_id_for(event) -> str:
    """为没有 tool_call_id 的 ToolEvent 生成稳定 id（与 StreamCollector 的 key 兜底一致）。"""
    return event.tool_call_id or f"tc_{event.tool_name}"
