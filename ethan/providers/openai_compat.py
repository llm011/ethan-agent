from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlparse

import httpx

from ethan.core.config import ProviderConfig
from ethan.providers import _responses, _transform
from ethan.providers._text_toolcalls import (
    _MARKED_TOOL_RE,
    _buf_has_unclosed_marked_tool,
    _strip_marked_tool_blocks,
    parse_marked_text_tool_calls,
)
from ethan.providers._text_toolcalls import (
    contains_dsml as _contains_dsml_impl,
)
from ethan.providers._text_toolcalls import (
    parse_dsml_tool_calls as _parse_dsml_tool_calls_impl,
)
from ethan.providers._text_toolcalls import (
    parse_text_tool_calls as _parse_text_tool_calls_impl,
)
from ethan.providers.base import (
    MIDSTREAM_BREAK_KEYWORDS,
    BaseProvider,
    Message,
    MidstreamBreakError,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)

# 文本/标记型工具调用解析拆到 ethan/providers/_text_toolcalls.py，请求构造拆到 _transform.py，
# 响应解析拆到 _responses.py。此处 re-import 保留 openai_compat 命名空间对外可见（既有单测
# 从本模块导入 _MARKED_TOOL_RE / _strip_marked_tool_blocks / parse_marked_text_tool_calls，
# 且 stream_chat 状态机内以裸名引用 _buf_has_unclosed_marked_tool 等），避免破坏导入路径。
__all__ = [
    "OpenAICompatProvider",
    "_MARKED_TOOL_RE",
    "_strip_marked_tool_blocks",
    "_buf_has_unclosed_marked_tool",
    "parse_marked_text_tool_calls",
]

_CHUNK_TIMEOUT = 120  # 单个 chunk 超时（秒）
_MAX_STREAM_BREAK_RETRIES = 2


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
        return _transform.to_openai_messages(
            messages,
            include_reasoning=include_reasoning,
            supports_vision=self._supports_vision(),
        )

    def _to_openai_tools(self, tools: list[ToolDefinition]) -> list[dict]:
        return _transform.to_openai_tools(tools)

    @staticmethod
    def _strip_unsupported_schema_fields(schema: dict | None) -> dict:
        """递归移除 JSON Schema 中 Gemini 等模型不支持的字段（如 default、additionalProperties）。"""
        return _transform.strip_unsupported_schema_fields(schema)

    def _parse_choice(self, choice, usage=None) -> Message:
        return _responses.parse_choice(choice, usage)

    @staticmethod
    def _parse_usage(usage) -> dict:
        """解析 usage，统一读取 OpenAI 标准 + DeepSeek 专有的缓存字段。"""
        return _responses.parse_usage(usage)

    @staticmethod
    def _parse_dsml_tool_calls(content: str) -> list[ToolCall]:
        """解析 DeepSeek DSML 格式的工具调用文本。

        实现见 _text_toolcalls.parse_dsml_tool_calls。保留本类同名 staticmethod 转发：
        agent.py 以 `OpenAICompatProvider._parse_dsml_tool_calls(...)` 类属性方式调用。
        """
        return _parse_dsml_tool_calls_impl(content)

    @staticmethod
    def _contains_dsml(content: str) -> bool:
        # 保留本类同名 staticmethod 转发：agent.py 以 `OpenAICompatProvider._contains_dsml(...)`
        # 类属性方式调用。实现见 _text_toolcalls.contains_dsml。
        return _contains_dsml_impl(content)

    def _parse_text_tool_calls(self, content: str) -> list[ToolCall]:
        """从文本中解析 `call:<tool_name>{<args>}` 格式的工具调用。

        实现见 _text_toolcalls.parse_text_tool_calls（不依赖实例状态）。
        """
        return _parse_text_tool_calls_impl(content)

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
        return _transform.strip_images_from_content(content)

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
        disable_thinking: bool = False,
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
            state = "disabled" if disable_thinking else "enabled"
            kwargs["extra_body"] = {"thinking": {"type": state}}

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
                # 标记型工具调用（<tool_call>/<tool_use>）：未闭合 → 持续缓冲；
                # 已闭合 → 同样缓冲到 finish 统一解析。否则闭合标签到达的瞬间
                # opens==closes，整块会被下面的 else 当正文 yield 漏给用户。
                if _buf_has_unclosed_marked_tool(content_buf) or _MARKED_TOOL_RE.search(content_buf):
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
                    if marked_calls or _MARKED_TOOL_RE.search(content_buf):
                        # 哪怕一个块都解析不出来（如截断的半截块）也要剥，
                        # 否则包裹符里的内容会当正文漏给用户
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
                pre = _strip_marked_tool_blocks(content_buf)
                if pre.strip():
                    yield StreamChunk(content=pre)
            yield StreamChunk(content="", is_final=True, truncated=True)
