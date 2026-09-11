"""响应解析：把 OpenAI Chat Completions 的非流式 choice / usage 转成 ethan 的 Message。

从 openai_compat.py 拆出。工具调用兜底解析委托 _text_toolcalls，usage 解析纯函数。
OpenAICompatProvider 在类上保留同名方法作薄转发，故对外行为与拆分前完全一致。
"""
from __future__ import annotations

import json

from ethan.providers._text_toolcalls import (
    _MARKED_TOOL_RE,
    _strip_marked_tool_blocks,
    parse_dsml_tool_calls,
    parse_marked_text_tool_calls,
    parse_text_tool_calls,
)
from ethan.providers.base import Message, ToolCall


def parse_usage(usage) -> dict:
    """解析 usage，统一读取 OpenAI 标准 + DeepSeek 专有的缓存字段。

    各家返回结构：
    - OpenAI 标准：prompt_tokens_details.cached_tokens
    - DeepSeek 官方：prompt_cache_hit_tokens / prompt_cache_miss_tokens
      （同时也会在 prompt_tokens_details.cached_tokens 回填，两者取一致值）
    - 火山 ARK：prompt_tokens_details.cached_tokens

    返回统一字段：input/output/cache，其中 cache = 命中缓存的 token 数。
    """
    usage_dict = {
        "input": getattr(usage, "prompt_tokens", 0) or 0,
        "output": getattr(usage, "completion_tokens", 0) or 0,
        "cache": 0,
    }
    # OpenAI 标准 / ARK 隐式缓存的 cached_tokens
    ptd = getattr(usage, "prompt_tokens_details", None)
    if ptd:
        usage_dict["cache"] = getattr(ptd, "cached_tokens", 0) or 0
    # DeepSeek 专有字段（优先级高于标准字段，若两者不一致以专有字段为准）
    hit = getattr(usage, "prompt_cache_hit_tokens", None)
    if hit and hit > usage_dict["cache"]:
        usage_dict["cache"] = hit
    return usage_dict


def parse_choice(choice, usage=None) -> Message:
    msg = choice.message
    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, AttributeError):
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    # Fallback：某些模型/中转偶尔不返回标准 tool_calls，而是把工具调用写成文本。
    # 支持两种格式：
    # 1. Gemini 经 cliproxy: `call:default_api:shell{command:...,intent:...}`
    # 2. DeepSeek DSML: `<｜｜DSML｜｜tool_calls>...<｜｜DSML｜｜invoke name="...">...`
    content_text = msg.content or ""
    if not tool_calls and content_text:
        parsed = parse_dsml_tool_calls(content_text) or parse_text_tool_calls(content_text)
        if parsed:
            tool_calls = parsed
            content_text = ""
        else:
            marked = parse_marked_text_tool_calls(content_text)
            if marked or _MARKED_TOOL_RE.search(content_text):
                tool_calls = marked
                content_text = _strip_marked_tool_blocks(content_text)

    usage_dict = None
    if usage:
        usage_dict = parse_usage(usage)

    return Message(
        role="assistant",
        content=content_text,
        tool_calls=tool_calls,
        usage=usage_dict,
    )
