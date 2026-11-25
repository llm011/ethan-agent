"""Provider transports and bounded generation retries (loop step two).

Chat retains the provider Message; stream emits every round, including retries.
Fallback rounds intentionally use the primary stream provider, not the route.
"""
import logging
import time
from datetime import datetime

from ethan.core import agent as compat
from ethan.providers.base import InjectEvent, Message, ThinkingEvent

logger = logging.getLogger(__name__)


class ChatTransport:
    streaming = False
    stop_finalize_tools = False

    async def generate(self, agent, state, tools, system, purpose="main"):
        provider = state.provider
        try:
            response = await provider.chat(state.working, tools=tools, system=system)
        except Exception as error:
            if purpose != "main":
                raise
            if compat._is_image_error(error) and not state.image_stripped:
                state.image_stripped = True
                if not compat._strip_images_from_messages(state.working, agent.session_id):
                    raise
            elif compat.is_input_length_error(error) and not state.length_trimmed:
                state.length_trimmed = True
                trim_retry(state, system, error)
            else:
                raise
            response = await provider.chat(state.working, tools=tools, system=system)
        agent.usage.add(response.usage)
        state.response = response
        state.generated_wire = response
        state.final_chunk = None
        if False:
            yield None

    async def ensure_nonempty(self, agent, state, reason):
        state.response = await agent._ensure_non_empty(state.response, state.working, state.monitor, reason)
        if False:
            yield None

    async def instant(self, agent, working):
        if False:
            yield None


class StreamTransport:
    streaming = True
    stop_finalize_tools = True

    async def instant(self, agent, working):
        text = agent._get_last_user_text(working)
        instant = compat.classify_instant(text) if text else None
        self.instant_handled = bool(instant)
        if not instant:
            return
        if instant.kind == "math":
            yield f"{instant.answer}"
        elif instant.kind == "time":
            yield f"现在是 {instant.answer}"
        elif instant.kind == "greeting":
            from ethan.core.timezone import get_local_timezone
            now = datetime.now(get_local_timezone()).strftime("%Y-%m-%d %H:%M:%S %A")
            system = (f"{agent._system_files.get('identity', 'You are a helpful assistant.')}\n"
                      f"Current time: {now}\n简洁直接地回答，不需要调用任何工具。")
            persona = agent._persona_block()
            if persona:
                system += f"\n{persona}"
            agent._trim_input_if_needed(working, system)
            async for chunk in agent._provider.stream_chat(working, tools=None, system=system):
                if chunk.reasoning:
                    yield ThinkingEvent(delta=chunk.reasoning)
                if chunk.content:
                    yield chunk.content
                if chunk.is_final:
                    agent.usage.add(chunk.usage)

    async def generate(self, agent, state, tools, system, purpose="main"):
        started = time.monotonic()
        content, reasoning, final = "", "", None
        provider = state.provider if purpose == "main" else agent._provider

        async def pump(source):
            nonlocal content, reasoning, final
            async for chunk in source.stream_chat(state.working, tools=tools, system=system):
                if chunk.reasoning:
                    reasoning += chunk.reasoning
                    # Legacy varied/stuck do not emit ThinkingEvent.
                    if purpose not in {"varied", "stuck"}:
                        yield ThinkingEvent(delta=chunk.reasoning)
                if chunk.content:
                    content += chunk.content
                    yield chunk.content
                if chunk.is_final:
                    final = chunk
                    agent.usage.add(chunk.usage)

        try:
            async for event in pump(provider):
                yield event
        except Exception as error:
            if purpose != "main":
                raise
            if compat._is_image_error(error) and not state.image_stripped and not content:
                state.image_stripped = True
                if not compat._strip_images_from_messages(state.working, agent.session_id):
                    raise
            elif compat.is_input_length_error(error) and not state.length_trimmed and not content:
                state.length_trimmed = True
                omitted = trim_retry(state, system, error)
                yield InjectEvent(messages=[f"会话过长，已自动截断较早的历史消息（约省略 {omitted} 字），正在继续处理…"])
            elif provider is not agent._provider and not content:
                provider = state.provider = agent._provider
                agent._lite_provider = agent._provider
            elif (isinstance(error, TimeoutError) or compat._is_retriable_connect_error(error)) and not content:
                fallback = agent._get_timeout_fallback(provider)
                if fallback is not None:
                    provider = fallback  # Only this round uses timeout fallback.
                elif not state.same_model_retried:
                    state.same_model_retried = True
                else:
                    raise
            else:
                raise
            content, reasoning, final = "", "", None
            async for event in pump(provider):
                yield event
        state.gen_ms = int((time.monotonic() - started) * 1000)
        calls = final.tool_calls if final else []
        if purpose == "main" and not calls and content:
            calls = agent._parse_stream_text_tool_calls(content)
            if calls:
                content = strip_text_calls(content)
        # Existing nudge/finalize paths discarded reasoning in working. Keep that
        # legacy prompt policy, but recorder receives the full generated wire.
        prompt_reasoning = reasoning if purpose == "main" else ""
        state.response = Message("assistant", content, tool_calls=calls, reasoning=prompt_reasoning or None)
        state.generated_wire = Message("assistant", content, tool_calls=calls, reasoning=reasoning or None,
                                       usage=final.usage if final else None)
        state.final_chunk = final

    async def ensure_nonempty(self, agent, state, reason):
        if state.response.content:
            return
        text = None
        if not state.empty_retried:
            state.empty_retried = True
            text = await agent._minimal_retry(state.working)
        if not text:
            calls = [m for m in state.working if m.role == "assistant" and m.tool_calls]
            text = compat._empty_reply_fallback_text(reason, len(calls))
        state.response = Message("assistant", text)
        yield text


def trim_retry(state, system, error):
    budget = compat.effective_input_budget()
    trimmed, omitted = compat.trim_for_retry(state.working, system, budget)
    if not omitted or compat.total_input_chars(trimmed, system) > budget // 2:
        raise RuntimeError("会话内容过长，已超过当前模型的输入上限，自动截断后仍放不下。"
                           "请新开会话，或在设置页切换上下文更大的模型。") from error
    state.working[:] = trimmed
    return omitted


def strip_text_calls(content):
    import re

    from ethan.providers._text_toolcalls import parse_invoke_tool_calls, strip_invoke_tool_blocks
    from ethan.providers.openai_compat import OpenAICompatProvider
    if OpenAICompatProvider._contains_dsml(content):
        match = re.search(r"<[｜|][｜|]DSML[｜|][｜|]", content)
        if match:
            content = content[:match.start()].rstrip()
    if parse_invoke_tool_calls(content):
        content = strip_invoke_tool_blocks(content).strip()
    return content if content.strip() else ""
