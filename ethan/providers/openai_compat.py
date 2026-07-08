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
            http_client = httpx.AsyncClient(proxy=proxy)
        self._client = AsyncOpenAI(
            api_key=provider_cfg.api_key or "none",
            base_url=provider_cfg.base_url,
            http_client=http_client,
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

        usage_dict = None
        if usage:
            usage_dict = {
                "input": getattr(usage, "prompt_tokens", 0),
                "output": getattr(usage, "completion_tokens", 0),
                "cache": getattr(usage.prompt_tokens_details, "cached_tokens", 0) if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details else 0,
            }

        return Message(
            role="assistant",
            content=msg.content or "",
            tool_calls=tool_calls,
            usage=usage_dict,
        )

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
