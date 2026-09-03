from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlparse

import httpx

from ethan.core.config import ProviderConfig
from ethan.providers.base import (
    MIDSTREAM_BREAK_KEYWORDS,
    BaseProvider,
    Message,
    MidstreamBreakError,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)

_CHUNK_TIMEOUT = 120  # 单个 chunk 超时（秒）
_MAX_STREAM_BREAK_RETRIES = 2

# 一些网关/中转不返回标准 tool_calls，而是把工具调用拼成字符串再用包裹符包起来下发。
# ethan 原本只识别 DSML（<｜｜DSML｜｜…）与 `call:tool{args}` 两种文本格式；GLM 兼容层、本地
# workbuddy 等会换包裹符。这里统一兜底识别，并把它们从「展示正文」里剥掉，避免 JSON 原样
# 漏给用户（表现为 assistant 消息里出现一段裸工具调用文本）。
_MARKED_TOOL_RE = re.compile(
    r'<\s*(?P<open>tool_call|tool_use)\s*[^>]*>\s*'
    r'(?P<body>\{[\s\S]*?\})\s*'
    r'</\s*(?P=open)\s*>',
    re.IGNORECASE,
)


def _strip_marked_tool_blocks(content: str) -> str:
    """把 <tool_call>/<tool_use> 包裹的工具调用片段从正文中剥掉，只留真正文。

    无论能否解析成工具调用，都先移除，防止序列化后的工具调用露出为可见正文。
    """
    if not content:
        return content
    return _MARKED_TOOL_RE.sub("", content)


def _buf_has_unclosed_marked_tool(content: str) -> bool:
    """判断文本缓冲区是否包含「尚未闭合」的标记型工具调用块。

    流式分片时 <tool_call>/<tool_use> 的开头标签可能先到、闭合标签后到，若按普通文本
    yield 出去就会露馅。检测到未闭合时持续缓冲，直到流结束再统一解析。
    """
    for tag in ("tool_call", "tool_use"):
        opens = len(re.findall(r'<\s*' + tag + r'\b', content, re.IGNORECASE))
        closes = len(re.findall(r'<\s*/\s*' + tag + r'\s*>', content, re.IGNORECASE))
        if opens > closes:
            return True
    return False


def parse_marked_text_tool_calls(content: str) -> list[ToolCall]:
    """解析以包裹符序列化的文本工具调用。

    兼容两种形状：
      - 直接 {"name": ..., "arguments": {...}}
      - 嵌套 {"function": {"name":..., "arguments":...}}
      解析失败静默跳过，不抛错。返回 ToolCall 列表（可能为空）。
    """
    results: list[ToolCall] = []
    for m in _MARKED_TOOL_RE.finditer(content or ""):
        raw = m.group("body").strip()
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("tool_name")
        arguments = obj.get("arguments") or obj.get("input")
        if isinstance(obj.get("function"), dict):
            fn = obj["function"]
            name = name or fn.get("name")
            if arguments is None:
                arguments = fn.get("arguments")
        if not name or not isinstance(arguments, dict):
            continue
        results.append(ToolCall(
            id=f"call_{uuid.uuid4().hex[:8]}",
            name=str(name),
            arguments=arguments,
        ))
    return results


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
            # 禁用 SDK 内部重试：默认 max_retries=2 会静默重试 3 次 × 120s ≈ 6 分钟，
            # 期间 agent 层完全无感知（lite 档回退主模型的逻辑被拖到超时后才触发）。
            # 失败立即冒泡，交给 agent 层回退/流式断连重试兜底。
            max_retries=0,
        )
        self._model = model
        self._base_url = (provider_cfg.base_url or "").lower()

    @property
    def model(self) -> str:
        return self._model

    def _to_openai_messages(self, messages: list[Message], include_reasoning: bool = False) -> list[dict]:
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
        if not self._supports_vision():
            for msg_dict in result:
                if isinstance(msg_dict.get("content"), list):
                    msg_dict["content"] = self._strip_images_from_content(msg_dict["content"])

        return result

    def _to_openai_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": self._strip_unsupported_schema_fields(t.parameters),
                },
            }
            for t in tools
        ]

    @staticmethod
    def _strip_unsupported_schema_fields(schema: dict | None) -> dict:
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

        # Fallback：某些模型/中转偶尔不返回标准 tool_calls，而是把工具调用写成文本。
        # 支持两种格式：
        # 1. Gemini 经 cliproxy: `call:default_api:shell{command:...,intent:...}`
        # 2. DeepSeek DSML: `<｜｜DSML｜｜tool_calls>...<｜｜DSML｜｜invoke name="...">...`
        content_text = msg.content or ""
        if not tool_calls and content_text:
            parsed = self._parse_dsml_tool_calls(content_text) or self._parse_text_tool_calls(content_text)
            if parsed:
                tool_calls = parsed
                content_text = ""
            else:
                marked = parse_marked_text_tool_calls(content_text)
                if marked:
                    tool_calls = marked
                    content_text = _strip_marked_tool_blocks(content_text)

        usage_dict = None
        if usage:
            usage_dict = self._parse_usage(usage)

        return Message(
            role="assistant",
            content=content_text,
            tool_calls=tool_calls,
            usage=usage_dict,
        )

    @staticmethod
    def _parse_usage(usage) -> dict:
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

    @staticmethod
    def _parse_dsml_tool_calls(content: str) -> list[ToolCall]:
        """解析 DeepSeek DSML 格式的工具调用文本。

        DeepSeek 模型偶尔会在 content 中以自有标记格式输出 tool calls：
            <｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="tool"> <｜｜DSML｜｜parameter name="key" string="true">value</｜｜DSML｜｜parameter> ...
        """
        import re
        import uuid

        # 全角和半角竖线都匹配
        sep = r'[｜|]'
        tag = sep + sep + r'DSML' + sep + sep

        if "DSML" not in content:
            return []

        results = []
        # 匹配每个 invoke 块
        invoke_pattern = re.compile(
            r'<' + tag + r'invoke\s+name="([^"]+)"[^>]*>(.*?)</' + tag + r'invoke>',
            re.DOTALL
        )
        param_pattern = re.compile(
            r'<' + tag + r'parameter\s+name="([^"]+)"[^>]*>(.*?)</' + tag + r'parameter>',
            re.DOTALL
        )

        for inv_match in invoke_pattern.finditer(content):
            tool_name = inv_match.group(1)
            body = inv_match.group(2)
            args = {}
            for p_match in param_pattern.finditer(body):
                args[p_match.group(1)] = p_match.group(2).strip()
            results.append(ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=tool_name,
                arguments=args,
            ))

        return results

    @staticmethod
    def _contains_dsml(content: str) -> bool:
        return "DSML" in content and ("｜｜DSML｜｜" in content or "||DSML||" in content)

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

    # --- reasoning / thinking 协议（DeepSeek R1 / deepseek-reasoner / 兼容 reasoning_content 的转发）---

    _REASONING_MODEL_PATTERNS = ("deepseek-r1", "deepseek-reasoner")
    # 支持图像输入的模型关键词；不匹配的模型发送消息时会剥离图片 content blocks
    _VISION_KEYWORDS = ("vision", "gpt-4o", "gpt-4.1", "claude", "gemini", "glm-4v", "glm-4.0v")

    def _wants_reasoning(self) -> bool:
        """当前模型是否走 reasoning 协议（序列化历史 reasoning_content + 注入顶层 thinking）。

        只看模型名，不看历史：会话中途从 reasoning 模型切到普通模型（如 gpt-4o）时，
        历史里存的 reasoning 不再发给新端点——严格校验的 API 收到额外字段会 400
        (Extra inputs are not permitted)，与 _skip_thinking_field 是同族防护。
        """
        model = (self._model or "").lower()
        return any(k in model for k in self._REASONING_MODEL_PATTERNS)

    def _supports_vision(self) -> bool:
        """检查当前模型是否支持图像输入（content 中可含 image_url blocks）。"""
        model = (self._model or "").lower()
        return any(kw in model for kw in self._VISION_KEYWORDS)

    @staticmethod
    def _strip_images_from_content(content: Any) -> Any:
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

    def _skip_thinking_field(self) -> bool:
        """直连 DeepSeek 官方 API 时不传顶层 thinking 字段：
        官方对 deepseek-reasoner 默认强制开启推理，额外字段会报 400
        (Extra inputs are not permitted)。该字段仅面向需要显式声明的
        Anthropic 风格中转网关。
        """
        try:
            host = urlparse(self._base_url).hostname or ""
        except ValueError:
            return False
        return host == "api.deepseek.com" or host.endswith(".deepseek.com")

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> Message:
        reasoning = self._wants_reasoning()
        oai_messages = self._to_openai_messages(messages, include_reasoning=reasoning)
        if system:
            oai_messages.insert(0, {"role": "system", "content": system})

        kwargs: dict = {
            "model": self._model,
            "messages": oai_messages,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"
        if reasoning and not self._skip_thinking_field():
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

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
        reasoning = self._wants_reasoning()
        oai_messages = self._to_openai_messages(messages, include_reasoning=reasoning)
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
        if reasoning and not self._skip_thinking_field():
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        tool_calls_acc: dict[int, dict] = {}
        final_tool_calls: list[ToolCall] = []
        stream_usage = None
        content_buf = ""  # 缓冲区：检测 DSML 标记

        try:
            resp_iter = await self._client.chat.completions.create(**kwargs)  # type: ignore
        except Exception as e:
            # 打印请求摘要帮助排查
            import logging as _log
            _lg = _log.getLogger("ethan.providers.openai_compat")
            _lg.error("[stream_chat] API error: %s", e)
            _lg.error("[stream_chat] model=%s, messages=%d, tools=%d",
                      kwargs.get("model"), len(kwargs.get("messages", [])), len(kwargs.get("tools", [])))
            if kwargs.get("tools"):
                _lg.error("[stream_chat] tool_names=%s", [t["function"]["name"] for t in kwargs["tools"]])
            # dump 第一个 tool schema 帮助定位
            if kwargs.get("tools"):
                _lg.error("[stream_chat] first_tool_params=%s", json.dumps(kwargs["tools"][0]["function"].get("parameters", {}), ensure_ascii=False)[:500])
            # dump messages 摘要
            for i, m in enumerate(kwargs.get("messages", [])):
                role = m.get("role", "?")
                content = m.get("content")
                content_preview = str(content)[:100] if content else "(None)"
                _lg.error("[stream_chat] msg[%d] role=%s content=%s", i, role, content_preview)
            raise

        aiter = resp_iter.__aiter__()
        _break_retries = 0  # 中途断连（未产出内容时）已重试次数
        _salvaged = False  # 标记是否因中途断连而 salvage 退出
        # 是否已向调用方产出过正文/思考。不能用 content_buf 判断：它只是 DSML 检测
        # 缓冲，正常文本每次 yield 后即清空，多数时刻为空。
        _produced_any = False
        while True:
            try:
                chunk = await asyncio.wait_for(aiter.__anext__(), timeout=_CHUNK_TIMEOUT)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                # 关闭底层流，归还连接池，防止 socket 泄漏
                try:
                    await resp_iter.aclose()
                except Exception:
                    pass
                raise TimeoutError(
                    f"模型响应超时：超过 {_CHUNK_TIMEOUT} 秒未收到新数据，可能是 API 挂起。"
                    "请稍后重试，或检查网络状况。"
                )
            except Exception as e:
                # 流式读取中途 TLS 记录层失败 / 连接被重置 / 中转提前断开
                # （如 "peer closed connection without sending complete message body"）。
                # 已产出部分内容时直接当作正常结束，保留已生成内容避免整段丢失；
                # 未产出任何内容时带退避重试。
                # 关键词与 interface 层文案分类共用 MIDSTREAM_BREAK_KEYWORDS，防止漂移
                _msg = str(e).lower()
                is_midstream_break = any(k in _msg for k in MIDSTREAM_BREAK_KEYWORDS)
                if not is_midstream_break:
                    raise
                try:
                    await resp_iter.aclose()
                except Exception:
                    pass
                # 已向调用方产出过内容或 tool_calls → 优雅收尾（标记 truncated，
                # 上层 agent 会自动续接），既不丢用户已等到的输出，也避免整段重发
                # 造成内容重复。
                if _produced_any or content_buf or final_tool_calls or any(
                    tc.get("args_raw") for tc in tool_calls_acc.values()
                ):
                    import logging as _log
                    _log.getLogger("ethan.providers.openai_compat").warning(
                        "[stream_chat] midstream break, salvaging partial output: %s", e
                    )
                    _salvaged = True
                    break
                # 未产出任何内容 → 退避后重建连接重试（中转抖动多为瞬态，立即重试
                # 一次往往不够）
                if _break_retries >= _MAX_STREAM_BREAK_RETRIES:
                    raise MidstreamBreakError(
                        "上游连接在流式响应中途断开，自动重试 "
                        f"{_MAX_STREAM_BREAK_RETRIES} 次后仍失败（未产出任何内容）：{e}"
                    ) from e
                _break_retries += 1
                import logging as _log
                _log.getLogger("ethan.providers.openai_compat").warning(
                    "[stream_chat] midstream break with no output, retry %d/%d: %s",
                    _break_retries, _MAX_STREAM_BREAK_RETRIES, e
                )
                await asyncio.sleep(0.6 * _break_retries)
                resp_iter = await self._client.chat.completions.create(**kwargs)  # type: ignore
                aiter = resp_iter.__aiter__()
                continue
            delta = chunk.choices[0].delta if chunk.choices else None

            # Usage comes in the final chunk (with empty choices or after finish)
            if chunk.usage:
                stream_usage = self._parse_usage(chunk.usage)

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
                _produced_any = True
                yield StreamChunk(content="", reasoning=rc)

            if delta.content:
                _produced_any = True
                content_buf += delta.content
                # 标记型工具调用（<tool_call>/<tool_use>）分片未闭合 → 继续缓冲，不 yield
                if _buf_has_unclosed_marked_tool(content_buf):
                    pass
                # DSML 标记开头特征：一旦检测到就持续缓冲直到流结束或 finish
                elif self._contains_dsml(content_buf):
                    pass  # 继续缓冲，不 yield
                elif "<｜" in content_buf or "<|" in content_buf:
                    # 可能是 DSML 片段还没完整，继续缓冲（最多 200 字符探测）
                    if len(content_buf) < 200:
                        pass
                    else:
                        yield StreamChunk(content=content_buf)
                        content_buf = ""
                elif content_buf.rstrip().endswith("<"):
                    # 末尾 < 可能是 DSML 标记的开头，短暂缓冲等待后续字符
                    if len(content_buf) < 50:
                        pass
                    else:
                        yield StreamChunk(content=content_buf)
                        content_buf = ""
                else:
                    yield StreamChunk(content=content_buf)
                    content_buf = ""

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
                # 处理缓冲区中可能的文本 tool calls：标记型（<tool_call>/<tool_use>）优先，
                # 其次 DSML
                if content_buf:
                    marked_calls = parse_marked_text_tool_calls(content_buf)
                    if marked_calls:
                        pre_text = _strip_marked_tool_blocks(content_buf).strip()
                        if pre_text:
                            yield StreamChunk(content=pre_text)
                        for mc in marked_calls:
                            tool_calls_acc[len(tool_calls_acc)] = {
                                "id": mc.id, "name": mc.name,
                                "args_raw": json.dumps(mc.arguments, ensure_ascii=False),
                            }
                        content_buf = ""
                    else:
                        dsml_calls = self._parse_dsml_tool_calls(content_buf)
                        if dsml_calls:
                            # 保留 DSML 标记之前的正文
                            import re as _re
                            dsml_start = _re.search(r'<[｜|][｜|]DSML[｜|][｜|]', content_buf)
                            pre_text = content_buf[:dsml_start.start()].rstrip() if dsml_start else ""
                            if pre_text:
                                yield StreamChunk(content=pre_text)
                            for dc in dsml_calls:
                                tool_calls_acc[len(tool_calls_acc)] = {
                                    "id": dc.id, "name": dc.name, "args_raw": json.dumps(dc.arguments, ensure_ascii=False)
                                }
                            content_buf = ""
                        else:
                            yield StreamChunk(content=content_buf)
                            content_buf = ""
                
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

        # 中途断连 salvage：flush 剩余缓冲并标记 truncated，上层 agent 据此自动续接
        if _salvaged:
            if content_buf:
                yield StreamChunk(content=content_buf)
            yield StreamChunk(content="", is_final=True, truncated=True)
