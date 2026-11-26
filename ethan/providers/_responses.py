"""响应解析：把 OpenAI Chat Completions 的非流式 choice / usage 转成 ethan 的 Message。

从 openai_compat.py 拆出。工具调用兜底解析委托 _text_toolcalls，usage 解析纯函数。
OpenAICompatProvider 在类上保留同名方法作薄转发，故对外行为与拆分前完全一致。
"""
from __future__ import annotations

import json
import math

from ethan.providers._text_toolcalls import (
    _MARKED_TOOL_RE,
    _strip_marked_tool_blocks,
    parse_dsml_tool_calls,
    parse_marked_text_tool_calls,
    parse_text_tool_calls,
)
from ethan.providers.base import Message, ToolCall


def _valid_cache_count(value) -> bool:
    """Presence means a usable upstream count, not a default or malformed value."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value >= 0 and (isinstance(value, int) or math.isfinite(value)))


def parse_usage(usage) -> dict:
    """解析 usage，统一读取 OpenAI 标准 + DeepSeek 专有的缓存字段。

    各家返回结构：
    - OpenAI 标准：prompt_tokens_details.cached_tokens
    - DeepSeek 官方：prompt_cache_hit_tokens / prompt_cache_miss_tokens
      （同时也会在 prompt_tokens_details.cached_tokens 回填，两者取一致值）
    - 火山 ARK：prompt_tokens_details.cached_tokens

    返回统一字段：input/output/cache，其中 cache = 命中缓存的 token 数。
    附加 cache_usage.cache_reported 只观测有效字段是否存在，不改变旧数值计算。
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
    raw_reported = getattr(usage, "_ethan_cache_reported", None)
    # SDK field sets preserve keys, not original types; coerced values cannot
    # establish raw presence without our per-response conversion observation.
    known = isinstance(raw_reported, bool)
    reported = raw_reported if known else False
    usage_dict["cache_usage"] = {"cache_reported": reported, "cache_presence_known": known}
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

    # reasoning_content（思考过程）：DeepSeek reasoning 模型 / 兼容 thinking 的中转
    # 会在非流式响应的 message.reasoning_content 里返回。必须原样挂到 Message 上，
    # 下一轮请求回传——否则带 tools 的 thinking 模式请求会 400：
    # 「The reasoning_content in the thinking mode must be passed back to the API.」
    reasoning = getattr(msg, "reasoning_content", None) or None

    return Message(
        role="assistant",
        content=content_text,
        tool_calls=tool_calls,
        usage=usage_dict,
        reasoning=reasoning,
    )
