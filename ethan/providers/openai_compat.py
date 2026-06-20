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
        for msg in messages:
            if msg.role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            elif msg.is_tool_call:
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
            else:
                result.append({"role": msg.role, "content": msg.content})
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

                # If this is the standalone usage chunk (choices is empty), yield it and we're done
                if not chunk.choices:
                    yield StreamChunk(content="", is_final=True, usage=stream_usage)
                    continue

            if delta is None:
                continue

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
                # Not passing stream_usage here because it might arrive in a later standalone chunk
                yield StreamChunk(content="", tool_calls=tool_calls, is_final=not kwargs.get("stream_options"))
