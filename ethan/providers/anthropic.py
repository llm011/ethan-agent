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

        # 默认走 curl_cffi transport：yuntoken 等中转网关拦截 Python httpx 的 TLS 指纹
        # （ClientHello 阶段 SSL UNEXPECTED_EOF），curl_cffi 模拟 Chrome JA3 能过。
        # 走 curl_cffi 时 _clean_headers 的去指纹头逻辑仍有用（x-stainless 等），
        # 但 event_hooks 只在 httpx 原生 client 上生效，curl_cffi transport 在
        # handle_async_request 里直接读 request.headers，所以这里同步在 transport
        # 层之外无法 hook——改由 transport 内部透传 headers 时由 SDK 已处理的请求头
        # 决定。实测 curl_cffi + impersonate=chrome 已足够绕过指纹拦截。
        # 回退原生 httpx：ETHAN_HTTP_BACKEND=httpx（调试或直连官方 API 时用）。
        import os
        backend = os.environ.get("ETHAN_HTTP_BACKEND", "curl").lower()
        if backend == "httpx":
            http_client = httpx.AsyncClient(
                proxy=proxy if proxy else None,
                event_hooks={"request": [_clean_headers]},
            )
        else:
            from ethan.providers.curl_transport import CurlCffiTransport
            http_client = httpx.AsyncClient(
                transport=CurlCffiTransport(proxy=proxy),
                event_hooks={"request": [_clean_headers]},
            )

        # 空字符串 api_key 会让 SDK 抛 "Could not resolve authentication method"。
        # 转成 None，让 SDK fall back 到 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN 环境变量。
        api_key = provider_cfg.api_key or None
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=provider_cfg.base_url,
            http_client=http_client,
        )
        self._model = model
        self._provider_key = "anthropic"
        self._api_key_configured = bool(api_key) or bool(
            __import__("os").environ.get("ANTHROPIC_API_KEY")
            or __import__("os").environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        self._disable_prompt_cache = getattr(provider_cfg, "disable_prompt_cache", False)

    @property
    def model(self) -> str:
        return self._model

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == "tool":
                tool_content: list[dict] | str = msg.content
                if msg.images:
                    # 工具返回截图时，把图片和文字一起放进 tool_result content 数组
                    parts: list[dict] = []
                    for img in msg.images:
                        parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img.get("media_type", "image/png"),
                                "data": img["data"],
                            },
                        })
                    if msg.content:
                        parts.append({"type": "text", "text": msg.content})
                    tool_content = parts
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": tool_content,
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
            elif msg.role == "user" and msg.images:
                content = []
                for img in msg.images:
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.get("media_type", "image/png"),
                            "data": img["data"],
                        },
                    })
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                result.append({"role": "user", "content": content})
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _to_anthropic_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        result = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]
        # 在第一个工具定义上加 cache_control，使缓存断点位于稳定的工具前缀。
        # 缓存块以 cache_control 所在位置为终点，之前的内容（含所有靠前工具）可被复用。
        # 放在 result[-1] 时，find_tools 激活新工具会改变末尾工具的身份/顺序，
        # 导致整块缓存失效；放在 result[0] 时，只要第一个工具不变（通常是最基础的
        # web_search/shell 等 always-on 工具），缓存前缀就稳定，后续激活新工具
        # 不影响已缓存部分，依然能命中省 token。
        if result and not self._disable_prompt_cache:
            result[0]["cache_control"] = {"type": "ephemeral"}
        return result

    def _parse_response(self, response: anthropic.types.Message) -> Message:  # noqa: F821 — lazy-imported in __init__
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

    def _check_auth(self) -> None:
        """启动时未配置 api_key 且环境变量也没有时，给友好错误而非 SDK 晦涩报错。"""
        if not self._api_key_configured:
            raise RuntimeError(
                "未配置 anthropic provider 的 api_key。请在 ~/.ethan/config.yaml 的 "
                "providers.anthropic.api_key 填入密钥，或设置环境变量 ANTHROPIC_API_KEY。"
            )

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> Message:
        self._check_auth()
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens or get_config().defaults.max_tokens,
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
        self._check_auth()
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
        # usage 在 message_start（input）和 message_delta（output）事件里累积
        usage_input = 0
        usage_output = 0
        usage_cache_read = 0
        usage_cache_creation = 0

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "message_start":
                    u = getattr(event.message, "usage", None)
                    if u:
                        usage_input = getattr(u, "input_tokens", 0) or 0
                        usage_cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
                        usage_cache_creation = getattr(u, "cache_creation_input_tokens", 0) or 0
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_calls_acc[event.index] = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input_raw": "",
                        }
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield StreamChunk(content=event.delta.text)
                    elif event.delta.type == "thinking_delta":
                        # 原生扩展思考：分流到 reasoning，不当正文展示。
                        #
                        # ⚠️ 前提：当前未在 kwargs 里传 `thinking` 参数，扩展思考实际未开启，
                        # 故此分支休眠、不会触发。若将来开启扩展思考，必须同时解决：
                        # Anthropic 要求在带 tool_use 的多轮里，把上一轮**带 signature 的
                        # thinking 块**原样回传，否则续轮报错。而 Agent 层组装
                        # Message(role="assistant", content=full_content, ...) 只留正文、
                        # 丢弃了 thinking 块——届时多轮工具调用会断。开启前先让 Message
                        # 能携带并回放 thinking 块（含 signature）。
                        yield StreamChunk(content="", reasoning=event.delta.thinking)
                    elif event.delta.type == "input_json_delta":
                        if event.index in tool_calls_acc:
                            tool_calls_acc[event.index]["input_raw"] += event.delta.partial_json
                elif event.type == "message_delta":
                    u = getattr(event.usage, "output_tokens", None)
                    if u:
                        usage_output = u
                elif event.type == "message_stop":
                    tool_calls = []
                    for tc in tool_calls_acc.values():
                        try:
                            args = json.loads(tc["input_raw"]) if tc["input_raw"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))
                    usage_dict = {
                        "input": usage_input,
                        "output": usage_output,
                        "cache_read": usage_cache_read,
                        "cache_creation": usage_cache_creation,
                    }
                    yield StreamChunk(content="", tool_calls=tool_calls, is_final=True, usage=usage_dict)
