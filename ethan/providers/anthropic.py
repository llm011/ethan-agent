from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from ethan.core.config import ProviderConfig, get_config
from ethan.providers.base import (
    BaseProvider,
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)


def _split_system_for_cache(system: str) -> tuple[str, str]:
    """Split system prompt into stable (cacheable) and dynamic (non-cached) parts.

    Split point: everything before 'Current time:' is stable; from there on is dynamic
    (includes current time, scheduled_tasks, available_skills, user_context, etc.).
    """
    marker = "Current time:"
    idx = system.find(marker)
    if idx == -1:
        return system, ""
    return system[:idx].rstrip(), system[idx:]


def _build_system_blocks(system: str) -> list[dict]:
    """Convert a system prompt string into Anthropic content blocks with prompt caching.

    The stable prefix gets cache_control so repeated calls within 5 min pay only 0.1x.
    The dynamic suffix (time, tasks, skills, context) is always sent fresh.
    """
    stable, dynamic = _split_system_for_cache(system)
    blocks: list[dict] = []
    if stable:
        blocks.append({
            "type": "text",
            "text": stable,
            "cache_control": {"type": "ephemeral"},
        })
    if dynamic:
        blocks.append({
            "type": "text",
            "text": dynamic,
        })
    # Fallback: if split produced nothing, wrap the whole string uncached
    if not blocks and system:
        blocks.append({"type": "text", "text": system})
    return blocks


class AnthropicProvider(BaseProvider):
    def __init__(self, provider_cfg: ProviderConfig, model: str, proxy: Optional[str] = None):
        import anthropic  # lazy: SDK is heavy; only load when a provider instance is created

        # httpx event hooks must be async; strip SDK fingerprint headers that
        # third-party relays (yuntoken.vip etc.) block, and replace the user-agent.
        async def _clean_headers(request: httpx.Request) -> None:
            for key in [k for k in request.headers if k.lower().startswith("x-stainless")]:
                del request.headers[key]
            # Some relays block the default anthropic-python user-agent
            request.headers["user-agent"] = "python-httpx/0.28.1"

        http_client = httpx.AsyncClient(
            proxy=proxy if proxy else None,
            event_hooks={"request": [_clean_headers]},
        )

        self._client = anthropic.AsyncAnthropic(
            api_key=provider_cfg.api_key,
            base_url=provider_cfg.base_url,
            http_client=http_client,
        )
        self._model = model
        self._disable_prompt_cache = getattr(provider_cfg, "disable_prompt_cache", False)

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
                "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
                "cache_creation": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
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
            "max_tokens": get_config().defaults.max_tokens,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system if self._disable_prompt_cache else _build_system_blocks(system)
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
            "max_tokens": get_config().defaults.max_tokens,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system if self._disable_prompt_cache else _build_system_blocks(system)
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
