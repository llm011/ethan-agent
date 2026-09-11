"""请求构造：把 ethan 的 Message/ToolDefinition 转成 OpenAI Chat Completions 入参。

从 openai_compat.py 拆出。纯函数，不依赖 provider 实例状态——vision 能力以 bool 显式
传入。OpenAICompatProvider 在类上保留同名方法作薄转发，故对外行为与拆分前完全一致。
"""
from __future__ import annotations

import json
from typing import Any

from ethan.providers.base import Message, ToolDefinition


def strip_unsupported_schema_fields(schema: dict | None) -> dict:
    """递归移除 JSON Schema 中 Gemini 等模型不支持的字段（如 default、additionalProperties）。"""
    if not schema or not isinstance(schema, dict):
        return schema or {}
    import copy
    s = copy.deepcopy(schema)
    _UNSUPPORTED = {"default", "additionalProperties"}

    def _clean(obj):
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if key in _UNSUPPORTED:
                    del obj[key]
                else:
                    _clean(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                _clean(item)
    _clean(s)
    return s


def strip_images_from_content(content: Any) -> Any:
    """剥离 content 中的图片 blocks，只保留文本部分。
    非 vision 模型（如 GLM-5.2）不接受 image_url content blocks，
    如果不剥离会导致 400 "Input should be a valid string" 格式校验失败。"""
    if not isinstance(content, list):
        return content
    text_parts = []
    for part in content:
        if isinstance(part, dict):
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        elif isinstance(part, str):
            text_parts.append(part)
    return "\n".join(text_parts) if text_parts else ""


def to_openai_messages(
    messages: list[Message],
    include_reasoning: bool,
    supports_vision: bool,
) -> list[dict]:
    result = []
    # 第一遍：按原顺序转换所有消息，图片 user 消息先暂存
    pending_img_messages: list[dict] = []

    for msg in messages:
        if msg.role == "tool":
            result.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content or "Screenshot taken.",
            })
            if msg.images:
                img_parts: list[dict] = []
                for img in msg.images:
                    media_type = img.get("media_type", "image/png")
                    data = img["data"]
                    img_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data}"},
                    })
                img_parts.append({"type": "text", "text": "Above is the screenshot result."})
                pending_img_messages.append({"role": "user", "content": img_parts})
        elif msg.is_tool_call:
            # 遇到新的 assistant tool_call 消息前，先把积压的图片 user 消息刷出
            # （说明上一组 tool 消息已全部到齐）
            result.extend(pending_img_messages)
            pending_img_messages = []
            oai_tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
            msg_dict = {
                "role": "assistant",
                "content": msg.content or None,
                "tool_calls": oai_tool_calls,
            }
            if msg.reasoning and include_reasoning:
                # DeepSeek / deepseek-reasoner 等 reasoning 模型要求：上一轮 API 返回过
                # reasoning_content（思考过程），下一轮请求必须原样回传在 assistant 消息里，
                # 否则返回 400: "The reasoning_content in the thinking mode must be passed back to the API."
                # 仅当前模型走 reasoning 协议时才序列化，避免切换模型后污染新端点。
                msg_dict["reasoning_content"] = msg.reasoning
            result.append(msg_dict)
        elif msg.role == "user" and msg.images:
            # 普通用户图片消息（发送时粘贴的图），同样先刷积压图片
            result.extend(pending_img_messages)
            pending_img_messages = []
            content = []
            for img in msg.images:
                media_type = img.get("media_type", "image/png")
                data = img["data"]
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                })
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            result.append({"role": "user", "content": content})
        else:
            # 非 tool 消息：刷积压图片后追加
            result.extend(pending_img_messages)
            pending_img_messages = []
            # 跳过空 assistant 消息（带 tool_calls 的已在上方 elif is_tool_call 分支处理，
            # 能到这里的 assistant 必然无 tool_calls），Gemini 不接受纯空 assistant 消息。
            # 但如果该消息携带 reasoning_content（推理模型的思考过程），必须保留——
            # DeepSeek 等 API 要求 reasoning_content 原样回传，丢弃会导致 400。
            if msg.role == "assistant" and not msg.content:
                if not (msg.reasoning and include_reasoning):
                    continue
            out = {"role": msg.role, "content": msg.content}
            if msg.role == "assistant" and msg.reasoning and include_reasoning:
                # reasoning_content 回传：详见上方 is_tool_call 分支注释
                out["reasoning_content"] = msg.reasoning
            result.append(out)

    # 末尾剩余的图片消息（最后一组 tool messages 后面没有后续消息时）
    result.extend(pending_img_messages)

    # 非 vision 模型：剥离 content 中的图片 blocks，只保留文本。
    # GLM-5.2 等模型的 content 必须是 string，image_url blocks 会导致 400 格式校验失败。
    if not supports_vision:
        for msg_dict in result:
            if isinstance(msg_dict.get("content"), list):
                msg_dict["content"] = strip_images_from_content(msg_dict["content"])

    return result


def to_openai_tools(tools: list[ToolDefinition]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": strip_unsupported_schema_fields(t.parameters),
            },
        }
        for t in tools
    ]
