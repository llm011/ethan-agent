"""Shared seven-step agent orchestration, with explicit transport policies."""
import logging
import time
from dataclasses import asdict, replace

from ethan.core import agent as compat
from ethan.core import loop_control as control
from ethan.core.agent_loop_state import (
    MAX_INJECT_EXTRA_ROUNDS,
    LoopState,
    inject_decision_context,
    intercept_decision,
)
from ethan.core.agent_tool_phase import StreamToolPhase
from ethan.core.context import get_injected_messages, reset_active_tools
from ethan.providers.base import InjectEvent, Message, SkillsMatchedEvent, ToolEvent

logger = logging.getLogger(__name__)


async def run_loop(agent, messages, transport):
    """The single orchestration shared by chat and streaming, not public delegation."""
    agent._executor.reset_cache()
    reset_active_tools()
    working = expand_wire_history(messages)
    agent._wire_transcript = []
    async for event in transport.instant(agent, working):
        yield event
    if getattr(transport, "instant_handled", False):
        return
    from ethan.core.artifacts import inject_artifacts_prompt
    inject_artifacts_prompt(working)
    compat.enforce_context_budget(working, agent.session_id)
    compat.compress_previous_round_tools(working, agent.session_id)
    route, system, tools_list, max_iters = agent._select_route(working)
    from ethan.core.session_memory import prepare_session_memory
    await prepare_session_memory(agent, working, route)
    provider = agent._provider_for_route(route)
    agent._trim_input_if_needed(working, system)
    state = LoopState(working, system, tools_list, max_iters, provider, len(working),
                      wire_transcript=agent._wire_transcript)
    if transport.streaming and agent.last_matched_skills:
        yield SkillsMatchedEvent(skills=[{
            "name": name, "is_default": getattr(agent._skills.get(name) if agent._skills else None, "is_default", False),
            "category": getattr(agent._skills.get(name) if agent._skills else None, "category", "default"),
        } for name in agent.last_matched_skills])

    for iteration in range(max_iters + MAX_INJECT_EXTRA_ROUNDS):
        # 1. Drain inbound context and choose bounded tool availability.
        state.iteration = iteration
        await state.checkpoint(agent, "iteration")
        injected = state.begin_round()
        if injected and transport.streaming:
            yield InjectEvent(messages=list(injected))
        finalize = state.finalize
        tools = None if finalize else agent._broadcast_tools(tools_list)
        system_round = system + (control.finalize_system_suffix("max_iters") if finalize else state.pending_suffix)
        state.pending_suffix = ""

        # 2. Generate via transport, retaining chat Message identity and stream events.
        async for event in transport.generate(agent, state, tools, system_round):
            yield event
        response = state.response
        working.append(response)
        await record_generation(agent, state)

        # 3. Response controls: stream truncation, nudge, natural finish, decide.
        final = state.final_chunk
        if (transport.streaming and final and final.truncated and not response.is_tool_call
                and response.content and not state.ssl_continue_used and not finalize):
            state.ssl_continue_used = True
            working.append(Message("user", "[网络中断，请从断点继续你的回复，不要重复已说内容。]"))
            continue
        empty = not response.content if transport.streaming else not (response.content or "").strip()
        if not finalize and not response.is_tool_call and (empty or compat._is_degenerate_reply(response.content, tools)):
            working.pop()
            working.append(Message("user", "[继续。请根据已有信息回答问题，或继续使用工具完成任务。]"))
            async for event in transport.generate(agent, state, tools, system, purpose="nudge"):
                yield event
            working.pop()
            response = state.response
            await record_generation(agent, state)
            retry_success = bool(response.content if transport.streaming else (response.content or "").strip())
            if retry_success or response.is_tool_call:
                working.append(response)
                if not response.is_tool_call:
                    injected = state.late_injection()
                    if injected:
                        if transport.streaming:
                            yield InjectEvent(messages=list(injected))
                        continue
                    if not transport.streaming:
                        yield response
                    return
            else:
                async for event in transport.generate(agent, state, None,
                        system + control.finalize_system_suffix("max_iters"), purpose="nudge_exhausted"):
                    yield event
                await record_generation(agent, state)
                async for event in transport.ensure_nonempty(agent, state, "nudge_exhausted" if transport.streaming else "finalize"):
                    yield event
                injected = state.late_injection(state.response, append_response=True)
                if injected:
                    if transport.streaming:
                        yield InjectEvent(messages=list(injected))
                    continue
                if not transport.streaming:
                    yield state.response
                return

        response = state.response
        if not response.is_tool_call:
            has_content = bool(response.content if transport.streaming else (response.content or "").strip())
            if state.monitor.awaiting_decision_response and has_content and not finalize:
                working.pop()
                state.monitor.silent_decision_count += 1
                state.monitor.awaiting_decision_response = False
                working.append(Message("user", "[继续执行任务。请直接调用工具完成下一步，不要用文字描述你的决策。]"))
                continue
            if transport.streaming and finalize and not response.content:
                async for event in transport.ensure_nonempty(agent, state, "finalize"):
                    yield event
            injected = state.late_injection()
            if injected:
                if transport.streaming:
                    yield InjectEvent(messages=list(injected))
                continue
            if not transport.streaming:
                async for event in transport.ensure_nonempty(agent, state, "finalize"):
                    yield event
                yield state.response
            return
        if finalize and transport.stop_finalize_tools:
            async for event in transport.ensure_nonempty(agent, state, "finalize"):
                yield event
            injected = state.late_injection()
            if injected:
                yield InjectEvent(messages=list(injected))
                continue
            return

        intercept_decision(state)
        calls = state.response.tool_calls
        if not calls:
            state.monitor.record([], False)
            await inject_decision_context(agent, state)
            # Stream's decide-only branch does not run reflection detection.
            if transport.streaming:
                continue
        else:
            # 4/5. Transport-specific authorization, then common dispatch/results.
            async for event in dispatch_tools(agent, state, transport):
                yield event

        # 6. Update progress, hints and adaptive decision context once.
        if calls:
            await inject_decision_context(agent, state)
        monitor = state.monitor
        if monitor.awaiting_reflection_followup:
            monitor.awaiting_reflection_followup = False
            if monitor.repeated_after_reflection():
                state.pending_suffix = "\n\n[System: " + control.reflection_followup_message() + "]"
                continue

        # 7. Reflect or finalize with the transport's compatible provider policy.
        if monitor.is_stuck():
            reason = "varied" if monitor._freq_limit_varied else "stuck" if monitor.exhausted() else None
            if reason:
                async for event in transport.generate(agent, state, None,
                        system + control.finalize_system_suffix(reason), purpose=reason):
                    yield event
                await record_generation(agent, state)
                async for event in transport.ensure_nonempty(agent, state, reason):
                    yield event
                injected = state.late_injection(state.response, append_response=True)
                if injected:
                    if transport.streaming:
                        yield InjectEvent(messages=list(injected))
                    continue
                if not transport.streaming:
                    yield state.response
                return
            result = state.results[-1].content if state.results else ""
            state.pending_suffix = "\n\n[System: " + control.reflection_message(monitor, result) + "]"
            monitor.mark_reflected()
    if get_injected_messages():
        logger.warning("Agent reached the iteration limit with unprocessed injected messages")
    if not transport.streaming:
        yield Message("assistant", "[max tool iterations reached]")


async def record_generation(agent, state):
    wire = state.generated_wire or state.response
    # decide is an internal control signal, not an executable wire tool.
    if any(call.name == "decide" for call in wire.tool_calls):
        wire = replace(wire, tool_calls=[call for call in wire.tool_calls if call.name != "decide"])
        if not wire.tool_calls and not wire.content:
            await state.checkpoint(agent, "generation")
            return
    agent._wire_transcript.append(wire)
    await state.checkpoint(agent, "generation")


async def dispatch_tools(agent, state, transport):
    calls = state.response.tool_calls
    allowed = calls
    await state.checkpoint(agent, "prepared", tool_calls=[asdict(c) for c in calls])
    if transport.streaming:
        phase = StreamToolPhase()
        async for event in phase.prepare(agent, calls, state.working, state.gen_ms):
            yield event
        allowed = phase.allowed_calls
    # Persist synthetic interaction results as well as executor results.
    known = {m.tool_call_id for m in agent._wire_transcript if m.role == "tool"}
    for message in state.working:
        if message.role == "tool" and message.tool_call_id in {c.id for c in calls} and message.tool_call_id not in known:
            agent._wire_transcript.append(message)
            call = next(call for call in calls if call.id == message.tool_call_id)
            await state.checkpoint(agent, "finished", result=message, tool_call=asdict(call), call_id=call.id)
    await state.checkpoint(agent, "prepared", tool_calls=[asdict(c) for c in allowed])
    finished = {}
    callback = getattr(agent, "_checkpoint_callback", None)
    executor = agent._executor
    old_hook = getattr(executor, "checkpoint_hook", None)

    async def hook(kind, call, result):
        if old_hook:
            await old_hook(kind, call, result)
        extra = {"tool_call": asdict(call), "call_id": call.id}
        if result is not None:
            message = tool_message(agent, call, result)
            finished[call.id] = message
            agent._wire_transcript.append(message)
            extra.update(result=message, had_error=result.is_error)
        await state.checkpoint(agent, kind, **extra)

    if callback:
        executor.checkpoint_hook = hook
    try:
        results = await executor.execute(allowed) if allowed or not transport.streaming else []
    finally:
        if callback:
            executor.checkpoint_hook = old_hook
    state.results = results
    for result, call in zip(results, allowed):
        if transport.streaming:
            yield result_event(result, call)
        message = finished.get(call.id) or tool_message(agent, call, result)
        state.working.append(message)
        if call.id not in finished:
            agent._wire_transcript.append(message)
            await state.checkpoint(agent, "finished", result=message, tool_call=asdict(call),
                                   call_id=call.id, had_error=result.is_error)
    compat.enforce_context_budget(state.working, agent.session_id)
    compat.compress_previous_round_tools(state.working, agent.session_id)
    had_error = any(getattr(r, "is_error", False) for r in results)
    state.monitor.record(calls, had_error)
    agent._run_checkpoint = {
        "iter": state.iteration + 1, "max_iters": state.max_iters,
        "last_tools": [c.name for c in calls], "last_had_error": had_error,
        "tool_names": list(state.monitor._tool_names[-8:]), "signatures": list(state.monitor._signatures[-4:]),
        "reflections_used": state.monitor.reflections_used, "updated_at": time.time(),
    }
    if had_error:
        state.pending_suffix = "\n\n[System: " + control.tool_error_hint(
            results[-1].content if results else "", calls[0].name if calls else "") + "]"
    await state.checkpoint(agent, "transcript", had_error=had_error)


def tool_message(agent, call, result):
    content = result.content or ""
    extra = getattr(agent, "_consent_msgs", {}).pop(call.id, None)
    if extra:
        content = f"[用户在授权时补充]：{extra}\n\n{content}"
    return Message("tool", content, tool_call_id=result.tool_call_id, images=result.images or [])


def result_event(result, call):
    from ethan.core.services.secrets_store import mask_text
    return ToolEvent(
        tool_name=call.name, tool_call_id=call.id, args_summary="",
        state="cancelled" if getattr(result, "is_cancelled", False) else "error" if result.is_error else "done",
        result_preview=mask_text(compat._preview(result.content)) if result.content else "",
        result_detail=mask_text(compat._detail(result.content)) if result.content else "",
        sub_steps=getattr(result, "sub_steps", []) or [], ui=getattr(result, "ui", None),
        mcp_app=getattr(result, "mcp_app", None), cards=getattr(result, "cards", None),
        cards_meta=getattr(result, "cards_meta", None), entity_type=compat.classify_tool(call.name),
        entity_id=compat.extract_entity_id(call.name, call.arguments),
        skill_category=compat.resolve_skill_category(call.name, call.arguments),
    )


def expand_wire_history(messages):
    working = []
    for message in messages:
        wire = getattr(message, "_wire_transcript", None)
        if message.role == "assistant" and wire:
            working.extend(wire)
        else:
            working.append(message)
    return working
