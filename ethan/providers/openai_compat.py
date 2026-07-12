from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from ethan.core.config import ProviderConfig
from ethan.providers.base import (
    BaseProvider,
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)


class OpenAICompatProvider(BaseProvider):
    def __init__(self, provider_cfg: ProviderConfig, model: str, proxy: Optional[str] = None):
        from openai import AsyncOpenAI  # lazy: SDK is heavy; only load when a provider instance is created
        http_client = None
        if proxy:
            http_client = httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(120.0, connect=10.0))
        self._client = AsyncOpenAI(
            api_key=provider_cfg.api_key or "none",
            base_url=provider_cfg.base_url,
            http_client=http_client,
            timeout=120.0,  # 2 分钟超时，防止 LLM 不响应导致无限挂起
        )
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def _to_openai_messages(self, messages: list[Message]) -> list[dict]:
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
                result.append({
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": oai_tool_calls,
                })
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
                result.append({"role": msg.role, "content": msg.content})

        # 末尾剩余的图片消息（最后一组 tool messages 后面没有后续消息时）
        result.extend(pending_img_messages)
        return result

    def _to_openai_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    def _parse_choice(self, choice, usage=None) -> Message:
        msg = choice.message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        # Fallback：某些模型/中转（如 Gemini 经 cliproxy）偶尔不返回标准 tool_calls，
        # 而是把工具调用写成文本：`call:default_api:shell{command:...,intent:...}`
        # 此时从 content 里解析出工具调用，避免 agent 循环中断。
        content_text = msg.content or ""
        if not tool_calls and content_text:
            parsed = self._parse_text_tool_calls(content_text)
            if parsed:
                tool_calls = parsed
                content_text = ""  # 解析成功则清空文本，避免把工具调用指令当回复返回

        usage_dict = None
        if usage:
            usage_dict = {
                "input": getattr(usage, "prompt_tokens", 0),
                "output": getattr(usage, "completion_tokens", 0),
                "cache": getattr(usage.prompt_tokens_details, "cached_tokens", 0) if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details else 0,
            }

        return Message(
            role="assistant",
            content=content_text,
            tool_calls=tool_calls,
            usage=usage_dict,
        )

    def _parse_text_tool_calls(self, content: str) -> list[ToolCall]:
        """从文本中解析 `call:<tool_name>{<args>}` 格式的工具调用。

        某些中转 API（如 cliproxy 转发 Gemini）在 function calling 退化时，
        会把工具调用序列化成文本而非标准 tool_calls 字段。格式示例：
            call:default_api:shell{command:gh auth status,intent:检查权限}

        其中 default_api 是 provider 前缀，实际工具名是冒号后的部分。
        args 不是标准 JSON（key 不带引号），需要宽松解析。
        """
        import re
        import uuid

        # 匹配 call:<prefix>:<tool_name>{<args>} 或 call:<tool_name>{<args>}
        pattern = re.compile(
            r'call:\w+:(?P<tool>\w+)\{(?P<args>[^}]*)\}'
            r'|call:(?P<tool2>\w+)\{(?P<args2>[^}]*)\}'
        )
        results = []
        for m in pattern.finditer(content):
            tool_name = m.group("tool") or m.group("tool2") or ""
            args_str = m.group("args") or m.group("args2") or ""
            if not tool_name:
                continue

            # 宽松解析 args：key:value,key:value 格式
            # value 可能包含逗号（如 shell 命令），用贪心匹配到最后一个 value
            args = {}
            # 尝试按 key:value 拆分，但 value 里可能含逗号
            # 策略：找到所有 key: 模式，然后取到下一个 key: 之前的内容作为 value
            key_pattern = re.compile(r'(\w+):')
            key_positions = [(km.start(), km.group(1)) for km in key_pattern.finditer(args_str)]
            for i, (pos, key) in enumerate(key_positions):
                val_start = pos + len(key) + 1  # 跳过 "key:"
                if i + 1 < len(key_positions):
                    val_end = key_positions[i + 1][0]
                else:
                    val_end = len(args_str)
                val = args_str[val_start:val_end].rstrip(',').strip()
                args[key] = val

            if args:
                results.append(ToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=tool_name,
                    arguments=args,
                ))

        return results

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> Message:
        oai_messages = self._to_openai_messages(messages)
        if system:
            oai_messages.insert(0, {"role": "system", "content": system})

        kwargs: dict = {
            "model": self._model,
            "messages": oai_messages,
        }
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        if not response.choices:
            raise RuntimeError("模型返回空 choices（可能触发内容过滤、配额用尽或服务异常）")
        return self._parse_choice(response.choices[0], response.usage)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        oai_messages = self._to_openai_messages(messages)
        if system:
            oai_messages.insert(0, {"role": "system", "content": system})

        kwargs: dict = {
            "model": self._model,
            "messages": oai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        tool_calls_acc: dict[int, dict] = {}
        final_tool_calls: list[ToolCall] = []  # 累积已构建的 tool_calls，供后续独立 usage chunk 的 final yield 携带
        stream_usage = None

        async for chunk in await self._client.chat.completions.create(**kwargs):  # type: ignore
            delta = chunk.choices[0].delta if chunk.choices else None

            # Usage comes in the final chunk (with empty choices or after finish)
            if chunk.usage:
                stream_usage = {
                    "input": chunk.usage.prompt_tokens or 0,
                    "output": chunk.usage.completion_tokens or 0,
                    "cache": 0,
                }
                if hasattr(chunk.usage, "prompt_tokens_details") and chunk.usage.prompt_tokens_details:
                    stream_usage["cache"] = getattr(chunk.usage.prompt_tokens_details, "cached_tokens", 0) or 0

                # If this is the standalone usage chunk (choices is empty), yield it and we're done.
                # 必须携带累积的 tool_calls：部分网关（如 Gemini 经由 openai 兼容端点）在
                # finish_reason chunk（非 final）里给出 tool_call，usage 在独立的 final chunk 里。
                # 若此处不带 tool_calls，消费方只看 final chunk 就会丢掉工具调用 → 表现为"秒退"。
                if not chunk.choices:
                    yield StreamChunk(content="", tool_calls=final_tool_calls, is_final=True, usage=stream_usage)
                    continue

            if delta is None:
                continue

            # 思考内容（reasoning_content）：deepseek-reasoner 等 reasoning 模型，以及部分中转把
            # 思考放在 delta.reasoning_content（或 model_extra 里）。与正文分流，避免漏进最终回答。
            rc = getattr(delta, "reasoning_content", None)
            if rc is None:
                me = getattr(delta, "model_extra", None) or {}
                rc = me.get("reasoning_content")
            if rc:
                yield StreamChunk(content="", reasoning=rc)

            if delta.content:
                yield StreamChunk(content=delta.content)

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": "", "name": "", "args_raw": ""}
                    if tc_delta.id:
                        tool_calls_acc[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_acc[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_acc[idx]["args_raw"] += tc_delta.function.arguments

            if chunk.choices and chunk.choices[0].finish_reason in ("tool_calls", "stop"):
                tool_calls = []
                for tc in tool_calls_acc.values():
                    try:
                        args = json.loads(tc["args_raw"]) if tc["args_raw"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))
                # If usage is already present in this chunk, it's the true final chunk.
                # If not, and stream_options is enabled, we expect a subsequent standalone usage chunk.
                is_final_now = bool(stream_usage) or not kwargs.get("stream_options")
                final_tool_calls = tool_calls  # 保存：若后续有独立 usage chunk，其 final yield 需要带上
                yield StreamChunk(content="", tool_calls=tool_calls, is_final=is_final_now, usage=stream_usage if is_final_now else None)
