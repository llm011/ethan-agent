r"""Tests for Agent 循环层的 consent 拒绝路径（PR #222 review 回归）。

背景：拒绝文案的误标根因在 stream_chat 的 consent 分支——Provider 层
（test_shell_consent.py）与正则层测试覆盖不到这里。本文件直接驱动真实的
stream_chat 循环（fake LLM provider + fake 授权工具），分别触发四条路径：

1. 用户拒绝（Web 弹窗点「拒绝」）→ reject_preview="用户拒绝"
2. 授权超时（5 分钟无响应）→ reject_preview="授权超时"，且请求从注册表摘除，
   迟到的「允许」resolve 返回 False
3. 高危·自动拒绝（AutoConsentProvider + always=True）→ reject_preview="高危命令·自动拒绝"
4. 生成取消（「停止生成」→ CancelledError）→ reject_preview="已取消"

断言两层：ToolEvent.result_preview（UI 展示）+ 下一轮传给 LLM 的 tool 消息
内容（模型看到的 reject_text）。
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from ethan.core.agent import Agent, UsageStats
from ethan.core.consent import (
    AutoConsentProvider,
    ConsentEvent,
    SuperConsentProvider,
    WebConsentProvider,
    set_consent_provider,
)
from ethan.providers.base import Message, StreamChunk, ToolCall, ToolEvent
from ethan.tools.base import BaseTool
from ethan.tools.registry import ToolRegistry

# ── 测试工具/Provider 脚手架 ─────────────────────────────────────

class SecretTool(BaseTool):
    """consent_check 恒命中 → 每次调用都进 consent 分支。"""

    def __init__(self, always: bool = False, destructive: bool | None = None):
        self._always = always
        # 默认跟随 always（BaseTool.consent_destructive 的保守默认）；
        # 显式传 False 模拟「高危但非破坏性」（如 sudo / env dump）。
        self._destructive = always if destructive is None else destructive

    @property
    def name(self) -> str:
        return "fake_get_secret"

    @property
    def description(self) -> str:
        return "读取密钥（测试用）"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def consent_check(self, **kwargs) -> str | None:
        return "读取密钥 API_KEY"

    def consent_always(self, **kwargs) -> bool:
        return self._always

    def consent_destructive(self, **kwargs) -> bool:
        return self._destructive

    async def run(self, **kwargs) -> str:
        return "sk-test"


class CancelledConsentProvider(WebConsentProvider):
    """create 后立即取消 fut → await wait_for(fut) 抛 CancelledError。

    模拟「停止生成」时外层取消正在等待授权的 await（取消发生在 fut 上，
    与外层 task 取消在该挂起点抛 CancelledError 等价）。
    """

    def create(self, description: str, tool: str = "", detail: str = "", always: bool = False):
        event, fut = super().create(description, tool, detail, always=always)
        fut.cancel()
        return event, fut


class FakeProvider:
    """按脚本回放的假 LLM：第 1 轮发 tool_call，之后轮发纯文本收尾。

    记录每轮收到的 messages，供断言「拒绝文案作为 tool 消息回传给模型」。
    """

    def __init__(self, tool_call: ToolCall):
        self.tool_call = tool_call
        self.seen_rounds: list[list[Message]] = []

    async def stream_chat(self, messages, tools=None, system=""):
        self.seen_rounds.append(list(messages))
        if len(self.seen_rounds) == 1:
            yield StreamChunk(content="", tool_calls=[self.tool_call], is_final=True)
        else:
            yield StreamChunk(content="好的，不执行了。", is_final=True)


class FakeExecutor:
    def reset_cache(self) -> None: ...

    async def execute(self, calls):
        return []


def _make_agent(tool: BaseTool, provider: FakeProvider, session_id: str) -> Agent:
    """最小化 Agent：绕过重 init，只装配 stream_chat 循环需要的字段。"""
    with patch.object(Agent, "__init__", lambda self, *a, **kw: None):
        agent = Agent()
    registry = ToolRegistry()
    registry.register(tool)
    agent._registry = registry
    agent._provider = provider
    agent._lite_provider = None
    agent.usage = UsageStats()
    agent.session_id = session_id
    agent.last_matched_skills = []
    agent._skills = {}
    agent._system_files = {}
    agent._executor = FakeExecutor()
    # 路由/工具广播/文本工具调用解析全部走桩，避免触达真实配置与网络
    agent._select_route = lambda working: ("full", "You are a test agent.", [tool.to_definition()], 6)
    agent._provider_for_route = lambda route: provider
    agent._broadcast_tools = lambda tools: tools or []
    agent._parse_stream_text_tool_calls = lambda content: []
    return agent


def _tool_events(events: list) -> list[ToolEvent]:
    return [e for e in events if isinstance(e, ToolEvent)]


def _tool_message_of_second_round(provider: FakeProvider) -> str:
    """第 2 轮 LLM 调用收到的 tool 消息内容（即拒绝文案回传给模型的原文）。"""
    tool_msgs = [m for m in provider.seen_rounds[1] if m.role == "tool"]
    assert tool_msgs, "第 2 轮应包含 tool 消息（拒绝文案）"
    return tool_msgs[0].content


QUERY = [Message(role="user", content="请读取 API_KEY 的值")]


def _drive(agent: Agent, on_event=None) -> list:
    """消费 stream_chat；on_event 在每个事件产出后同步回调（用于中途 resolve）。"""

    async def run() -> list:
        events = []
        async for ev in agent.stream_chat(QUERY):
            events.append(ev)
            if on_event is not None:
                on_event(ev)
        return events

    return asyncio.run(run())


# ── 1. 用户拒绝 ─────────────────────────────────────────────────

def test_user_reject_label():
    """Web 弹窗点「拒绝」→ 用户拒绝文案，非超时/自动拒绝。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(SecretTool(), provider_llm, session_id="t-user-reject")
    consent = WebConsentProvider(session_id="t-user-reject")
    set_consent_provider(consent)

    def on_event(ev):
        if isinstance(ev, ConsentEvent):
            consent.resolve(ev.request_id, allowed=False)  # 用户点「拒绝」

    events = _drive(agent, on_event)
    previews = [e.result_preview for e in _tool_events(events) if e.state == "error"]
    assert previews == ["用户拒绝"]
    assert "[用户拒绝此操作]" in _tool_message_of_second_round(provider_llm)
    assert "超时" not in _tool_message_of_second_round(provider_llm)


# ── 2. 授权超时 + 迟到响应失效 ──────────────────────────────────

def test_timeout_label_and_late_resolve_rejected():
    """等待超时 → 授权超时文案；注册表已摘除，迟到的「允许」resolve 返回 False。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(SecretTool(), provider_llm, session_id="t-timeout")
    consent = WebConsentProvider(session_id="t-timeout")
    set_consent_provider(consent)

    request_ids: list[str] = []

    def on_event(ev):
        if isinstance(ev, ConsentEvent):
            request_ids.append(ev.request_id)

    real_wait_for = asyncio.wait_for

    async def fast_wait_for(aw, timeout):
        return await real_wait_for(aw, 0.01)  # 把 300s 超时压到瞬时

    with patch.object(asyncio, "wait_for", fast_wait_for):
        events = _drive(agent, on_event)

    previews = [e.result_preview for e in _tool_events(events) if e.state == "error"]
    assert previews == ["授权超时"]
    assert "等待超时" in _tool_message_of_second_round(provider_llm)

    # 超时后注册表已摘除：迟到的「允许」不再被接受（前端会收到 ok=false 标记卡片失效）
    assert request_ids, "应产出 ConsentEvent"
    assert consent.resolve(request_ids[0], allowed=True) is False
    assert consent._pending == {}


# ── 3. 高危·自动拒绝（无人值守） ────────────────────────────────

def test_auto_provider_high_risk_reject_label():
    """AutoConsentProvider + always=True → 高危命令·自动拒绝，而非「用户拒绝」。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(SecretTool(always=True), provider_llm, session_id="t-auto")
    set_consent_provider(AutoConsentProvider(session_id="t-auto"))

    events = _drive(agent)
    previews = [e.result_preview for e in _tool_events(events) if e.state == "error"]
    assert previews == ["高危命令·自动拒绝"]
    assert "自动授权模式" in _tool_message_of_second_round(provider_llm)
    assert "用户拒绝" not in _tool_message_of_second_round(provider_llm)


# ── 4. 生成取消（停止生成） ──────────────────────────────────────

def test_cancelled_not_labeled_user_reject():
    """等待授权期间生成被取消 → 「已取消」，不得标成「用户拒绝」。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(SecretTool(), provider_llm, session_id="t-cancel")
    set_consent_provider(CancelledConsentProvider(session_id="t-cancel"))

    events = _drive(agent)
    previews = [e.result_preview for e in _tool_events(events) if e.state == "error"]
    assert previews == ["已取消"]
    msg = _tool_message_of_second_round(provider_llm)
    assert "已取消" in msg
    assert "用户拒绝" not in msg


# ── 5. 超级权限分级（2026-08-22 调整） ─────────────────────────
# 超级权限（SuperConsentProvider.auto_approve）只对 consent_destructive=True
# 的调用保留强制弹窗；其余高危自动放行。普通 web / 无人值守模式口径不变。

def test_super_mode_risky_auto_approved():
    """Super + always=True 但非破坏性 → 不弹窗直接放行。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(
        SecretTool(always=True, destructive=False), provider_llm, session_id="t-super-risky"
    )
    set_consent_provider(SuperConsentProvider(session_id="t-super-risky"))

    events = _drive(agent)
    # 自动放行：不产出 ConsentEvent，无 error，工具照常 start
    assert not [e for e in events if isinstance(e, ConsentEvent)]
    assert not [e for e in _tool_events(events) if e.state == "error"]
    assert any(e.state == "start" for e in _tool_events(events))


def test_super_mode_destructive_still_popups():
    """Super + 破坏性 → 仍弹 ConsentEvent（always=True），用户批准后执行。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(
        SecretTool(always=True, destructive=True), provider_llm, session_id="t-super-destructive"
    )
    consent = SuperConsentProvider(session_id="t-super-destructive")
    set_consent_provider(consent)

    def on_event(ev):
        if isinstance(ev, ConsentEvent):
            consent.resolve(ev.request_id, allowed=True)  # 用户点「允许」

    events = _drive(agent, on_event)
    consent_events = [e for e in events if isinstance(e, ConsentEvent)]
    assert consent_events and consent_events[0].always is True
    assert not [e for e in _tool_events(events) if e.state == "error"]


def test_web_mode_always_still_popups():
    """普通 web 模式口径不变：always=True（即使非破坏性）仍每次弹窗。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(
        SecretTool(always=True, destructive=False), provider_llm, session_id="t-web-always"
    )
    consent = WebConsentProvider(session_id="t-web-always")
    set_consent_provider(consent)

    def on_event(ev):
        if isinstance(ev, ConsentEvent):
            consent.resolve(ev.request_id, allowed=False)

    events = _drive(agent, on_event)
    assert [e for e in events if isinstance(e, ConsentEvent)]
    previews = [e.result_preview for e in _tool_events(events) if e.state == "error"]
    assert previews == ["用户拒绝"]


def test_auto_mode_always_still_rejected():
    """无人值守模式口径不变：always=True（即使非破坏性）仍自动拒绝。"""
    provider_llm = FakeProvider(ToolCall(id="call_1", name="fake_get_secret", arguments={}))
    agent = _make_agent(
        SecretTool(always=True, destructive=False), provider_llm, session_id="t-auto-always"
    )
    set_consent_provider(AutoConsentProvider(session_id="t-auto-always"))

    events = _drive(agent)
    previews = [e.result_preview for e in _tool_events(events) if e.state == "error"]
    assert previews == ["高危命令·自动拒绝"]
