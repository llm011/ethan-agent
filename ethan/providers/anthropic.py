import json
from typing import AsyncIterator, Optional

import anthropic
import httpx

from ethan.core.config import ProviderConfig
from ethan.providers.base import (
    BaseProvider,
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)


class AnthropicProvider(BaseProvider):
    def __init__(self, provider_cfg: ProviderConfig, model: str, proxy: Optional[str] = None):
        http_client = None
        if proxy:
            http_client = httpx.AsyncClient(proxy=proxy)
        self._client = anthropic.AsyncAnthropic(
            api_key=provider_cfg.api_key,
            base_url=provider_cfg.base_url,
            http_client=http_client,
        )
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == "tool":
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }],
                })
            elif msg.is_tool_call:
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    })
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _to_anthropic_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _parse_response(self, response: anthropic.types.Message) -> Message:
        tool_calls = []
        text_content = ""
        for block in response.content:
            if block.type == "text":
                text_content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        usage_dict = None
        if response.usage:
            usage_dict = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
                "cache": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            }

        return Message(role="assistant", content=text_content, tool_calls=tool_calls, usage=usage_dict)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> Message:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        # Accumulate tool use blocks during streaming
        tool_calls_acc: dict[int, dict] = {}

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_calls_acc[event.index] = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input_raw": "",
                        }
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield StreamChunk(content=event.delta.text)
                    elif event.delta.type == "input_json_delta":
                        if event.index in tool_calls_acc:
                            tool_calls_acc[event.index]["input_raw"] += event.delta.partial_json
                elif event.type == "message_stop":
                    tool_calls = []
                    for tc in tool_calls_acc.values():
                        try:
                            args = json.loads(tc["input_raw"]) if tc["input_raw"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))
                    yield StreamChunk(content="", tool_calls=tool_calls, is_final=True)
