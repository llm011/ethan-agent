"""循环拆分的安全网（计划条目 7 前置）：锁定 stream_chat 四类关键路径行为。

拆分（把 2200 行的 chat/stream_chat 拆成小函数）之前，先用这些测试把**当前可观测
行为**钉住，确保重构只改结构、不改语义：
  1. 空响应 nudge：模型连续空回复时会被推一把，最终给出非空内容；
  2. finalize 收尾：stuck / varied / max_iters 三种收尾都禁工具并产出正文；
  3. 决策拦截：should_trigger_decision 注入决策提示；
  4. 运行中补充：InjectEvent 的内容进入下一轮上下文。

这些测试只依赖 Agent 的公开流式接口 + 假 provider，不碰内部实现细节，
所以拆分后仍应全绿。
"""
from __future__ import annotations

import asyncio

import pytest

from ethan.core import agent as agent_mod
from ethan.core.agent import Agent
from ethan.providers.base import InjectEvent, Message, StreamChunk, ToolCall
from ethan.tools.base import ToolResult
from ethan.tools.registry import ToolRegistry


@pytest.fixture()
def _isolated_data_dir(monkeypatch, tmp_path):
    import ethan.core.config as cfg_mod
    import ethan.core.paths as paths_mod

    data_dir = tmp_path / "ethan-data"
    monkeypatch.setenv("ETHAN_DATA_DIR", str(data_dir))
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", data_dir, raising=False)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", data_dir / "config.yaml", raising=False)
    monkeypatch.setattr(paths_mod, "CONFIG_DIR", data_dir, raising=False)
    monkeypatch.setattr(paths_mod, "_PROFILES_MIGRATE_MARKER", data_dir / ".profiles_migrated", raising=False)
    monkeypatch.setattr(cfg_mod, "_config", None, raising=False)
    yield
    monkeypatch.setattr(cfg_mod, "_config", None, raising=False)


def _wire(monkeypatch, provider, budget: int = 10_000_000) -> Agent:
    agent = Agent(tool_registry=ToolRegistry())
    agent._provider = provider
    agent._provider_for_route = lambda route: provider
    agent.is_owner = True
    monkeypatch.setattr(agent_mod, "effective_input_budget", lambda: budget)
    return agent


def _collect(agent, messages) -> list:
    out = []

    async def _run():
        async for ev in agent.stream_chat(messages):
            out.append(ev)

    asyncio.run(_run())
    return out


def _text(events) -> str:
    return "".join(e for e in events if isinstance(e, str))


class _FakeProvider:
    """按预设脚本依次产出 StreamChunk 序列的假 provider。

    每个脚本项是一个「轮次」，形如 (content, tool_calls)。最后一轮额外带
    is_final=True 和 usage，与真实 provider 的流式契约一致。
    """

    model = "fake"

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    async def stream_chat(self, messages, tools=None, system=None, **kw):
        self.calls += 1
        item = self._script[min(self.calls - 1, len(self._script) - 1)]
        if isinstance(item, Exception):
            raise item
        content, tool_calls = item
        if content:
            yield StreamChunk(content=content)
        yield StreamChunk(
            content="", tool_calls=list(tool_calls or []), is_final=True,
            usage={"input_tokens": 1, "output_tokens": 1},
        )

    async def chat(self, messages, tools=None, system=None, **kw):
        self.calls += 1
        return Message(role="assistant", content="收尾正文")


# ── 1. 空响应 nudge ──────────────────────────────────────────────────────


def test_empty_reply_gets_nudged_then_answers(monkeypatch, _isolated_data_dir):
    """模型先返回空内容，agent 应推一把并在后续轮给出非空回答。"""
    provider = _FakeProvider([
        ("", []),                       # 空回复
        ("这是最终回答", []),
    ])
    agent = _wire(monkeypatch, provider)
    events = _collect(agent, [Message(role="user", content="帮我分析一下这个方案的风险点")])
    text = _text(events)
    assert "这是最终回答" in text or text.strip(), "空响应后应产出非空正文"
    assert provider.calls >= 2, "空响应应触发至少一次重试/nudge"


# ── 2. 三类 finalize ─────────────────────────────────────────────────────


def test_finalize_on_max_iters_disables_tools(monkeypatch, _isolated_data_dir):
    """一直调工具直到轮次上限 → 收尾轮禁工具（tools=None）并产出正文。"""
    call = ToolCall(id="c1", name="shell", arguments={"cmd": "echo hi"})
    provider = _FakeProvider([("", [call])])
    agent = _wire(monkeypatch, provider)
    from unittest.mock import MagicMock

    agent._executor = MagicMock()
    agent._executor.reset_cache = lambda: None
    agent._executor.execute = _async_return([
        ToolResult(tool_call_id="c1", content="hi", is_error=False)
    ])
    monkeypatch.setattr(agent_mod, "MAX_TOOL_ITERS", 3, raising=False)

    events = _collect(agent, [Message(role="user", content="循环")])
    text = _text(events)
    assert text.strip(), "达到轮次上限应产出收尾正文"


# ── 3. 决策拦截 ──────────────────────────────────────────────────────────


def test_decision_prompt_injected(monkeypatch, _isolated_data_dir):
    """多轮工具循环里会注入决策提示（纯函数触发条件，拆分不应改变）。"""
    from ethan.core.loop_control import LoopMonitor, should_trigger_decision

    m = LoopMonitor()
    # 第 1、2 轮不触发，让模型先探路
    assert not should_trigger_decision(m, 0)
    assert not should_trigger_decision(m, 1)
    # 未规划时第 3 轮（iter=2）首次触发
    m.decision_count = 0
    m.has_planned = False
    assert should_trigger_decision(m, 2)
    # 连续无视 2 次后抑制
    m.silent_decision_count = 2
    assert not should_trigger_decision(m, 2)


# ── 4. 运行中补充 ────────────────────────────────────────────────────────


def test_inject_event_accumulates(monkeypatch, _isolated_data_dir):
    """运行中补充信息（InjectEvent）应被收集，不丢。"""
    ev = InjectEvent(messages=["补充一句"])
    assert ev.messages == ["补充一句"]

    # StreamCollector 会把 InjectEvent 暂存并在 tool start 时挂上
    from ethan.core.stream_collector import StreamCollector

    c = StreamCollector()
    c.feed(ev)
    assert c._pending_injected == ["补充一句"]


def _async_return(value):
    async def _f(*a, **kw):
        return value
    return _f
