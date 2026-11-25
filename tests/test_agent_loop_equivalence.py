"""Characterize both legacy transports before sharing their orchestration."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ethan.core import agent as agent_mod
from ethan.core.agent import Agent, UsageStats
from ethan.core.context import set_inject_drainer
from ethan.providers.base import InjectEvent, Message, StreamChunk, ToolCall, ToolDefinition, ToolEvent
from ethan.tools.base import ToolResult
from ethan.tools.registry import ToolRegistry


class ScriptProvider:
    model = "script"

    def __init__(self, script, on_call=None):
        self.script = list(script)
        self.requests = []
        self.on_call = on_call

    def next(self, mode, messages, tools, system):
        self.requests.append((mode, deepcopy(messages), tools, system))
        if self.on_call:
            self.on_call(len(self.requests))
        item = self.script[min(len(self.requests) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    async def chat(self, messages, tools=None, system=None):
        return self.next("chat", messages, tools, system)

    async def stream_chat(self, messages, tools=None, system=None):
        msg = self.next("stream", messages, tools, system)
        if msg.reasoning:
            yield StreamChunk(content="", reasoning=msg.reasoning)
        if msg.content:
            yield StreamChunk(content=msg.content)
        yield StreamChunk(content="", tool_calls=msg.tool_calls, is_final=True, usage=msg.usage,
                          truncated=getattr(msg, "truncated", False))


class Executor:
    def __init__(self, error=False, inject=None):
        self.calls = []
        self.error = error
        self.inject = inject

    def reset_cache(self):
        pass

    async def execute(self, calls):
        self.calls.extend(deepcopy(calls))
        if self.inject:
            self.inject()
        return [ToolResult(tool_call_id=c.id, content="result", is_error=self.error) for c in calls]


def wire(monkeypatch, provider, max_iters=30, error=False):
    a = Agent.__new__(Agent)
    a._provider = provider
    a._lite_provider = None
    a._registry = ToolRegistry()
    a._executor = Executor(error)
    a.usage = UsageStats()
    a.session_id = ""
    a.last_matched_skills = []
    a._skills = None
    a._system_files = {}
    a._mode = ""
    a.is_owner = False
    a._select_route = lambda msgs: ("full", "SYSTEM", [], max_iters)
    a._provider_for_route = lambda route: provider
    a._broadcast_tools = lambda ts: [ToolDefinition("work", "work", {})]
    a._build_extended_memory = async_value("memory")
    a._build_all_tools_brief = lambda: "tools"
    a._build_all_skills_brief = lambda: "skills"
    monkeypatch.setattr(agent_mod, "effective_input_budget", lambda: 10_000_000)
    return a


def async_value(value):
    async def fn(*args, **kwargs):
        return value
    return fn


def run(a, mode):
    async def go():
        set_inject_drainer(getattr(a, "drainer", lambda: []))
        try:
            if mode == "chat":
                return await a.chat([Message("user", "analyze project")])
            return [ev async for ev in a.stream_chat([Message("user", "analyze project")])]
        finally:
            set_inject_drainer(None)
    return asyncio.run(go())


def tool(n, name="work", args=None):
    return Message("assistant", f"step{n}", tool_calls=[ToolCall(f"c{n}", name, args or {"n": n})],
                   reasoning=f"reason{n}", usage={"input": 2, "output": 1, "cache": 1})


def terminal(text="answer"):
    return Message("assistant", text, reasoning="terminal-reason", usage={"input": 3, "output": 2},
                   images=[{"data": "image"}])


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_terminal_and_usage_are_transport_specific(monkeypatch, mode):
    end = terminal()
    p = ScriptProvider([tool(1), end])
    a = wire(monkeypatch, p)
    a.usage.add({"input": 10})
    result = run(a, mode)
    assert a.usage.input_tokens == 15
    assert a.usage.output_tokens == 3
    assert a.usage.cache_tokens == 1
    assert p.requests[1][1][-2].reasoning == "reason1"
    if mode == "chat":
        assert result is end
        assert result.reasoning == "terminal-reason" and result.images
        assert result.content == "answer"
    else:
        assert "".join(e for e in result if isinstance(e, str)) == "step1answer"
        assert [(e.tool_call_id, e.state) for e in result if isinstance(e, ToolEvent)] == [
            ("c1", "start"), ("c1", "done")]


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_nudge_uses_expected_provider(monkeypatch, mode):
    route = ScriptProvider([Message("assistant", ""), terminal("route-answer")])
    main = ScriptProvider([terminal("main-answer")])
    a = wire(monkeypatch, route)
    a._provider = main
    result = run(a, mode)
    if mode == "chat":
        assert result.content == "route-answer"
        assert len(route.requests) == 2 and not main.requests
    else:
        assert "main-answer" in result
        assert len(route.requests) == 1 and len(main.requests) == 1
    req = route.requests[-1] if mode == "chat" else main.requests[-1]
    assert "继续。" in req[1][-1].content
    assert req[2] is not None


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_max_iters_really_disables_tools(monkeypatch, mode):
    p = ScriptProvider([tool(1), tool(2), terminal("bounded")])
    a = wire(monkeypatch, p, max_iters=3)
    result = run(a, mode)
    assert len(p.requests) == 3
    assert p.requests[-1][2] is None
    assert "步数已经比较多" in p.requests[-1][3]
    assert len(a._executor.calls) == 2
    assert result.content == "bounded" if mode == "chat" else "bounded" in result


@pytest.mark.parametrize("mode", ["chat", "stream"])
@pytest.mark.parametrize("reason", ["varied", "stuck"])
def test_real_monitor_finalize(monkeypatch, mode, reason):
    script = [tool(n, args={"n": n} if reason == "varied" else {"n": 0}) for n in range(1, 15)]
    route = ScriptProvider(script)
    main = ScriptProvider([terminal("main-final")])
    a = wire(monkeypatch, route)
    a._provider = main
    run(a, mode)
    requests = route.requests if mode == "chat" else main.requests
    assert requests[-1][2] is None
    expected = "批量操作" if reason == "varied" else "多种策略仍未突破"
    assert expected in requests[-1][3]
    assert len(a._executor.calls) == (8 if reason == "varied" else 7)
    if reason == "stuck":
        assert any("执行停滞警告" in req[3] for req in route.requests)
        assert any("没有采纳" in req[3] for req in route.requests)


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_real_decide_interception_and_enhancement(monkeypatch, mode):
    choice = Message("assistant", "", tool_calls=[ToolCall("decision", "decide", {"choice": "C"})])
    p = ScriptProvider([tool(1), tool(2), tool(3), choice, terminal()])
    a = wire(monkeypatch, p)
    memory_calls = []
    async def recall(query, max_items):
        memory_calls.append((query, max_items))
        return "enhanced memory"
    a._build_extended_memory = recall
    run(a, mode)
    assert memory_calls == [("analyze project", 30)]
    # Legacy pops its temporary prompt before dispatch, but awaits the choice.
    assert not any(c.name == "decide" for c in a._executor.calls)
    assert len(a._executor.calls) == 3
    assert not any(m.tool_calls and any(c.name == "decide" for c in m.tool_calls)
                   for m in p.requests[-1][1])


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_late_injection_is_processed(monkeypatch, mode):
    inbox = []
    p = ScriptProvider([terminal("first"), terminal("second")],
                       on_call=lambda n: inbox.append("extra requirements") if n == 1 else None)
    a = wire(monkeypatch, p, max_iters=1)
    def drain():
        out = inbox[:]
        inbox.clear()
        return out
    a.drainer = drain
    result = run(a, mode)
    assert len(p.requests) == 2
    assert "extra requirements" in p.requests[1][1][-1].content
    if mode == "chat":
        assert result.content == "second"
    else:
        assert "first" in result and "second" in result
        assert any(isinstance(e, InjectEvent) and e.messages == ["extra requirements"] for e in result)


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_finalize_disobedient_tool_compatibility(monkeypatch, mode):
    p = ScriptProvider([tool(n, args={"n": n}) for n in range(1, 10)])
    a = wire(monkeypatch, p, max_iters=1)
    run(a, mode)
    assert len(a._executor.calls) == (6 if mode == "chat" else 0)


def test_chat_does_not_use_instant_or_stream_policy(monkeypatch):
    monkeypatch.setattr(agent_mod, "classify_instant", lambda text: SimpleNamespace(kind="math", answer="42"))
    p = ScriptProvider([terminal()])
    a = wire(monkeypatch, p)
    assert run(a, "chat").content == "answer"
    assert run(a, "stream") == ["42"]
    assert len(p.requests) == 1


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_stream_only_lite_error_fallback(monkeypatch, mode):
    route = ScriptProvider([RuntimeError("unavailable lite")])
    main = ScriptProvider([terminal("main fallback")])
    a = wire(monkeypatch, route)
    a._provider = main
    if mode == "chat":
        with pytest.raises(RuntimeError, match="unavailable lite"):
            run(a, mode)
        assert not main.requests
    else:
        assert "main fallback" in run(a, mode)
        assert a._lite_provider is main


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_stream_only_ssl_continuation(monkeypatch, mode):
    first = terminal("partial")
    first.truncated = True
    p = ScriptProvider([first, terminal("continued")])
    a = wire(monkeypatch, p)
    out = run(a, mode)
    if mode == "chat":
        assert out is first and len(p.requests) == 1
    else:
        assert out[0] != "continued"
        assert "partial" in out and "continued" in out
        assert "网络中断" in p.requests[1][1][-1].content


@pytest.mark.parametrize("mode", ["chat", "stream"])
def test_chat_does_not_apply_stream_channel_policy(monkeypatch, mode):
    import ethan.core.consent as consent
    policy = SimpleNamespace(policy_check=lambda *args: "denied by channel policy")
    monkeypatch.setattr(consent, "get_consent_provider", lambda: policy)
    p = ScriptProvider([tool(1), terminal()])
    a = wire(monkeypatch, p)
    out = run(a, mode)
    assert len(a._executor.calls) == (1 if mode == "chat" else 0)
    if mode == "stream":
        assert not any(isinstance(e, ToolEvent) for e in out)
        assert p.requests[1][1][-1].content == "denied by channel policy"


def test_chat_empty_finalize_drains_supplement_before_minimal_retry(monkeypatch):
    inbox = []
    answer = terminal("answer incorporating supplement")
    p = ScriptProvider(
        [Message("assistant", ""), answer],
        on_call=lambda n: inbox.append("IMPORTANT supplement") if n == 1 else None,
    )
    a = wire(monkeypatch, p, max_iters=1)

    def drain():
        out = inbox[:]
        inbox.clear()
        return out

    a.drainer = drain
    assert run(a, "chat") is answer
    assert len(p.requests) == 2
    assert "IMPORTANT supplement" in p.requests[1][1][-1].content
    assert p.requests[1][3].startswith("SYSTEM")
    assert a.usage.input_tokens == 3 and a.usage.output_tokens == 2


def test_agent_owned_consent_extra_survives_multiple_tools(monkeypatch):
    import ethan.core.consent as consent
    from ethan.core.consent import ConsentResult
    from ethan.providers.base import ToolDefinition

    class TestTool:
        name = "work"
        side_effect = False
        def consent_check(self, **kwargs):
            return "request"
        def consent_scope(self, **kwargs):
            return str(kwargs["n"])
        def consent_always(self, **kwargs):
            return True
        def to_definition(self):
            return ToolDefinition(self.name, "", {})

    class Provider:
        streamed = True
        auto_approve = False
        session_id = ""
        def policy_check(self, *args):
            return None
        def create(self, *args, **kwargs):
            future = asyncio.get_running_loop().create_future()
            future.set_result(ConsentResult(True, "extra"))
            return "consent-event", future

    monkeypatch.setattr(consent, "get_consent_provider", lambda: Provider())
    provider = ScriptProvider([Message("assistant", "", tool_calls=[
        ToolCall("a", "work", {"n": 1}), ToolCall("b", "work", {"n": 2})]), terminal()])
    a = wire(monkeypatch, provider)
    a._registry.register(TestTool())
    run(a, "stream")
    results = [m.content for m in provider.requests[1][1] if m.role == "tool"]
    assert results == ["[用户在授权时补充]：extra\n\nresult", "[用户在授权时补充]：extra\n\nresult"]
