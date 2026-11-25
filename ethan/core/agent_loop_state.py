"""Request-owned state and inbound context (loop steps one and six)."""
from dataclasses import dataclass, field

from ethan.core import loop_control as control
from ethan.core.context import get_injected_messages
from ethan.providers.base import Message

MAX_INJECT_EXTRA_ROUNDS = 5


@dataclass
class LoopState:
    working: list
    system: str
    tools_list: list
    max_iters: int
    provider: object
    history_len: int
    monitor: object = field(default_factory=control.LoopMonitor)
    iteration: int = 0
    extra_rounds: int = 0
    pending_suffix: str = ""
    decision_injected: bool = False
    enhanced_injected: bool = False
    need_enhanced: bool = False
    image_stripped: bool = False
    length_trimmed: bool = False
    ssl_continue_used: bool = False
    same_model_retried: bool = False
    empty_retried: bool = False
    response: Message | None = None
    final_chunk: object = None
    gen_ms: int = 0
    results: list = field(default_factory=list)
    generated_wire: Message | None = None
    wire_transcript: list = field(default_factory=list)

    @property
    def finalize(self):
        return (self.iteration >= self.max_iters - 1 + self.extra_rounds
                or self.extra_rounds >= MAX_INJECT_EXTRA_ROUNDS)

    def append_injection(self, injected):
        text = "\n\n".join(f"[用户运行中补充]：{m}" for m in injected)
        self.wire_transcript.append(Message("user", text))
        if self.working and self.working[-1].role == "user":
            msg = self.working[-1]
            self.working[-1] = Message("user", (msg.content or "") + "\n\n" + text, images=msg.images)
        else:
            self.working.append(Message("user", text))

    def begin_round(self):
        # These flags deliberately preserve legacy temporary-message removal.
        if self.decision_injected and self.working and self.working[-1].role == "user":
            self.working.pop()
            self.decision_injected = False
        if self.enhanced_injected and self.working and self.working[-1].role == "user":
            self.working.pop()
            self.enhanced_injected = False
        injected = get_injected_messages()
        if injected:
            self.append_injection(injected)
            if self.finalize and self.extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                self.extra_rounds += 1
        return injected

    def late_injection(self, response=None, append_response=False):
        injected = get_injected_messages()
        if not injected or self.extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
            return []
        if append_response and response and response.content:
            self.working.append(Message("assistant", response.content))
        self.append_injection(injected)
        self.extra_rounds += 1
        self.decision_injected = self.enhanced_injected = False
        return injected

    async def checkpoint(self, agent, kind, **extra):
        callback = getattr(agent, "_checkpoint_callback", None)
        if callback:
            payload = {"kind": kind, "iter": self.iteration + 1, "max_iters": self.max_iters,
                       "history_len": self.history_len, "messages": list(agent._wire_transcript)}
            payload.update(extra)
            await callback(payload)


async def inject_decision_context(agent, state):
    monitor = state.monitor
    calls = state.response.tool_calls
    if any(tc.name == "plan_write" for tc in calls):
        monitor.has_planned = True
    if state.need_enhanced:
        memory = await agent._build_extended_memory(agent._get_last_user_text(state.working) or "", max_items=30)
        state.working.append(Message("user", control.enhanced_context_message(
            agent._build_all_skills_brief(), memory, agent._build_all_tools_brief())))
        state.enhanced_injected = True
        state.need_enhanced = False
    if control.should_trigger_decision(monitor, state.iteration):
        state.working.append(Message("user", control.decision_prompt_message(monitor.has_planned)))
        state.decision_injected = True
        monitor.decision_count += 1
        monitor.awaiting_decision_response = True


def intercept_decision(state):
    response, monitor = state.response, state.monitor
    if control.is_decision_call(response.tool_calls):
        choice = control.extract_decision_choice(response.tool_calls)
        # Legacy interception replaces Message and drops reasoning/images.
        state.response = Message(response.role, response.content,
                                 tool_calls=[tc for tc in response.tool_calls if tc.name != "decide"],
                                 usage=response.usage)
        state.working[-1] = state.response
        if monitor.awaiting_decision_response and choice == "C":
            state.need_enhanced = True
        monitor.awaiting_decision_response = False
    elif monitor.awaiting_decision_response:
        implicit = control.detect_implicit_decision(response.tool_calls)
        if implicit == "C":
            state.need_enhanced = True
        elif implicit == "A":
            monitor.silent_decision_count += 1
        monitor.awaiting_decision_response = False
