r"""输入长度越界防护（ethan/core/context_limit.py）的单元与接线测试。

覆盖 issue 场景：会话历史累积超过上游硬限制（DashScope
`Range of input length should be [1, 997952]`）时请求直接 400。

四层验证：
  1. 预算配置：默认留 5% 余量、环境变量覆盖、0 关闭、非法值回落；
  2. trim_to_limit：超限裁剪保留最近历史、user 边界切割不拆散
     tool_call/tool 配对、单条超限尽力而为、原列表不被 mutate；
  3. is_input_length_error：识别 DashScope / OpenAI / Anthropic 三系文案；
  4. agent 接线（stream_chat / chat 两条主循环）：
     - proactive：发送前超预算直接裁剪，首个请求就带裁剪后的消息；
     - reactive：上游 400 越界 → 裁剪重试一次，用户看到可见提示，
       第二次请求的消息数变少；裁不动时抛用户可读的中文错误。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ethan.core import agent as agent_mod
from ethan.core.agent import Agent
from ethan.core.config import ProviderConfig
from ethan.core.context_limit import (
    DEFAULT_MARGIN_PCT,
    TRIM_NOTICE_PREFIX,
    UPSTREAM_INPUT_LENGTH_LIMIT,
    effective_input_budget,
    is_input_length_error,
    msg_chars,
    total_input_chars,
    trim_for_retry,
    trim_to_limit,
)
from ethan.interface.routers.helpers import _friendly_error
from ethan.providers.base import Message, StreamChunk, ToolCall
from ethan.providers.openai_compat import OpenAICompatProvider
from ethan.tools.registry import ToolRegistry

DASHSCOPE_400 = (
    "Error code: 400 - {'error': {'code': 'InternalError.Algo.InvalidParameter', "
    "'message': 'Range of input length should be [1, 997952]'}}"
)


# ---------------------------------------------------------------------------
# 预算配置
# ---------------------------------------------------------------------------


class TestBudgetConfig:
    def test_default_budget_reserves_margin(self, monkeypatch):
        """默认：上限 997952 留 5% 余量 → int(997952 * 0.95) = 948054。"""
        monkeypatch.delenv("ETHAN_MAX_INPUT_CHARS", raising=False)
        monkeypatch.delenv("ETHAN_INPUT_LIMIT_MARGIN_PCT", raising=False)
        assert UPSTREAM_INPUT_LENGTH_LIMIT == 997952
        assert DEFAULT_MARGIN_PCT == 5
        assert effective_input_budget() == int(997952 * 0.95)

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ETHAN_MAX_INPUT_CHARS", "1000")
        monkeypatch.setenv("ETHAN_INPUT_LIMIT_MARGIN_PCT", "10")
        assert effective_input_budget() == 900

    def test_zero_disables(self, monkeypatch):
        """ETHAN_MAX_INPUT_CHARS=0 显式关闭预检（预算为 0，调用方跳过）。"""
        monkeypatch.setenv("ETHAN_MAX_INPUT_CHARS", "0")
        assert effective_input_budget() == 0

    def test_invalid_env_falls_back(self, monkeypatch):
        """非法环境变量值回落默认，不抛异常（配置错误不该弄挂对话）。"""
        monkeypatch.setenv("ETHAN_MAX_INPUT_CHARS", "abc")
        monkeypatch.setenv("ETHAN_INPUT_LIMIT_MARGIN_PCT", "oops")
        assert effective_input_budget() == int(997952 * 0.95)

    def test_non_positive_margin_returns_full_limit(self, monkeypatch):
        monkeypatch.setenv("ETHAN_MAX_INPUT_CHARS", "1000")
        monkeypatch.setenv("ETHAN_INPUT_LIMIT_MARGIN_PCT", "0")
        assert effective_input_budget() == 1000


# ---------------------------------------------------------------------------
# 长度估算
# ---------------------------------------------------------------------------


class TestMsgChars:
    def test_counts_content_toolcalls_reasoning_images(self):
        m = Message(
            role="assistant",
            content="正文",
            tool_calls=[ToolCall(id="t1", name="shell", arguments={"cmd": "ls -la"})],
            reasoning="思考过程",
            images=[{"data": "base64...", "media_type": "image/png"}],
        )
        n = msg_chars(m)
        assert n > len("正文") + len("思考过程") + len("shell") + len('"cmd": "ls -la"')
        # 图片按固定估算计入（不按 base64 实长）
        assert n >= len("正文") + len("思考过程") + 4000

    def test_total_includes_system(self):
        msgs = [Message(role="user", content="hi")]
        assert total_input_chars(msgs, system="SYS") == len("SYS") + 2
        assert total_input_chars([]) == 0


# ---------------------------------------------------------------------------
# trim_to_limit
# ---------------------------------------------------------------------------


class TestTrim:
    def test_under_budget_returns_same_list(self):
        msgs = [Message(role="user", content="短消息")]
        out, omitted = trim_to_limit(msgs, system="sys", budget=1000)
        assert out is msgs
        assert omitted == 0

    def test_over_budget_keeps_recent_and_inserts_notice(self):
        msgs = [
            Message(role="user", content="x" * 5000),
            Message(role="assistant", content="y" * 100),
            Message(role="user", content="最新问题"),
        ]
        out, omitted = trim_to_limit(msgs, system="S" * 200, budget=1000)
        assert omitted >= 5100
        # 开头是截断提示（user 角色），其后保留最新的 user 消息
        assert out[0].role == "user"
        assert out[0].content.startswith(TRIM_NOTICE_PREFIX)
        assert out[1] is msgs[2]
        # 裁剪后（含 system 与提示）回到预算内
        assert total_input_chars(out, system="S" * 200) <= 1000

    def test_cut_never_splits_tool_pairing(self):
        """切割对齐到 user 边界：assistant(tool_calls) 与其 tool result 同进同退。"""
        pair_assistant = Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="shell", arguments={})],
        )
        msgs = [
            Message(role="user", content="x" * 5000),
            pair_assistant,
            Message(role="tool", content="result", tool_call_id="c1"),
            Message(role="user", content="继续"),
        ]
        out, omitted = trim_to_limit(msgs, system="", budget=800)
        # 保留区间从 user 消息开始：不会以孤儿 tool 消息开头
        assert out[0].content.startswith(TRIM_NOTICE_PREFIX)
        assert all(m.role != "tool" for m in out)
        assert out[-1] is msgs[3]
        assert omitted >= 5000

    def test_single_oversized_user_message_best_effort(self):
        """首条 user 消息本身就超预算：没有可丢的前缀，原样返回（omitted=0），
        由调用方 reactive 兜底转译为用户可读错误。"""
        msgs = [Message(role="user", content="x" * 99999)]
        out, omitted = trim_to_limit(msgs, system="sys", budget=1000)
        assert out is msgs
        assert omitted == 0

    def test_all_tool_messages_degrades_to_notice_only(self):
        """保留区间里没有 user 边界（连续 tool 链）：退回到第一条 user——
        没有则只留提示，保证请求协议合法（首条非 system 是 user）。"""
        msgs = [
            Message(role="tool", content="a" * 5000, tool_call_id="c1"),
            Message(role="tool", content="b" * 10, tool_call_id="c2"),
        ]
        out, omitted = trim_to_limit(msgs, system="", budget=800)
        assert len(out) == 1
        assert out[0].content.startswith(TRIM_NOTICE_PREFIX)
        assert omitted >= 5010

    def test_original_list_and_messages_not_mutated(self):
        """裁剪只换 working 里的引用，session 共享的原列表/Message 不受影响。"""
        u1 = Message(role="user", content="x" * 5000)
        u2 = Message(role="user", content="最新问题")
        msgs = [u1, Message(role="assistant", content="y" * 100), u2]
        snapshot = [(m.role, m.content) for m in msgs]
        trim_to_limit(msgs, system="", budget=1000)
        assert [(m.role, m.content) for m in msgs] == snapshot
        assert u1.content == "x" * 5000

    def test_zero_budget_returns_unchanged(self):
        msgs = [Message(role="user", content="x" * 100)]
        out, omitted = trim_to_limit(msgs, system="", budget=0)
        assert out is msgs and omitted == 0

    def test_trim_for_retry_halves_budget(self):
        """reactive 重试用减半预算：同一输入，正常预检不裁、减半后裁。"""
        msgs = [
            Message(role="user", content="x" * 800),
            Message(role="user", content="最新问题"),
        ]
        _, omitted_full = trim_to_limit(msgs, system="", budget=1000)
        _, omitted_half = trim_for_retry(msgs, system="", budget=1000)
        assert omitted_full == 0  # 预检预算下放得下
        assert omitted_half > 0  # 减半后触发裁剪


# ---------------------------------------------------------------------------
# is_input_length_error
# ---------------------------------------------------------------------------


class TestIsInputLengthError:
    @pytest.mark.parametrize(
        "text",
        [
            DASHSCOPE_400,
            "Error code: 400 - {'error': {'code': 'context_length_exceeded', 'message': 'maximum context length is 8192 tokens'}}",
            "Invalid request: prompt is too long: 250000 tokens > 200000 maximum",
            "input tokens exceed the model limit",
        ],
    )
    def test_matches_major_providers(self, text):
        assert is_input_length_error(RuntimeError(text))

    @pytest.mark.parametrize(
        "text",
        [
            "Error in upstream response | code=provider_error | <400> image_dimension_exceeded",
            "peer closed connection without sending complete message body",
            "Could not resolve authentication method",
        ],
    )
    def test_does_not_match_other_errors(self, text):
        assert not is_input_length_error(RuntimeError(text))


# ---------------------------------------------------------------------------
# _friendly_error 兜底转译
# ---------------------------------------------------------------------------


class TestFriendlyError:
    def test_length_error_translated_to_actionable_hint(self):
        err = _friendly_error(RuntimeError(DASHSCOPE_400), agent=None)
        assert "会话内容过长" in err
        assert "新开会话" in err  # 可操作建议，不透传 provider_error 原文
        assert "997952" not in err

    def test_other_errors_unaffected(self):
        assert _friendly_error(RuntimeError("Connection reset by peer"), agent=None)


# ---------------------------------------------------------------------------
# agent 主循环接线（proactive + reactive）
# ---------------------------------------------------------------------------


def _chunk(content="", finish_reason=None):
    delta = SimpleNamespace(content=content or None, tool_calls=None,
                            reasoning_content=None, model_extra={})
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)], usage=None)


def _usage():
    return SimpleNamespace(choices=[], usage=SimpleNamespace(
        prompt_tokens=1, completion_tokens=1, total_tokens=2))


class FakeStream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        ev = self._events.pop(0)
        if isinstance(ev, BaseException):
            raise ev
        return ev

    async def aclose(self):
        pass


def _long_history():
    # 旧轮次 4.5 万字：预检预算（mock 10 万，扣除 system 后）下放得下，减半预算
    # （5 万，扣除 system 后仅余约 3.8 万）放不下——匹配真实 badcase「预检没拦住、
    # 400 后才有可裁空间」的形态。
    return [
        Message(role="user", content="旧" * 45000),
        Message(role="assistant", content="好的，已了解。"),
        Message(role="user", content="帮我总结一下上面的内容要点"),
    ]


def _make_stream_provider(side_effects):
    """stream_chat 用：create 依序消费 side_effects（异常实例则抛出）。"""
    cfg = ProviderConfig(api_key="k", base_url="https://relay.test/v1")
    p = OpenAICompatProvider(cfg, "fake")
    calls: list[list[dict]] = []

    async def _create(**kw):
        calls.append(kw["messages"])
        ev = side_effects.pop(0)
        if isinstance(ev, BaseException):
            raise ev
        return ev

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=_create)
    p._client = client
    p.create_calls = calls
    return p


def _final_stream(text="已根据保留的上下文完成总结。"):
    return FakeStream([_chunk(text), _chunk(finish_reason="stop"), _usage()])


@pytest.fixture()
def _isolated_data_dir(monkeypatch, tmp_path):
    """隔离 ETHAN_DATA_DIR：Agent 初始化会读 ~/.ethan（system/*.md、记忆等），
    本机真实数据（如被心跳写大的 tools.md）会让 system prompt 膨胀到百万字级，
    既拖慢测试也干扰预算断言——全部指向临时目录。

    CONFIG_DIR 在模块导入时就固化了环境变量，setenv 之后再 patch 模块属性；
    paths.py 以 `from ethan.core.config import CONFIG_DIR` 拿到的是值拷贝，
    需一并 patch。"""
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


def _wire_agent(provider, monkeypatch, budget: int) -> Agent:
    agent = Agent(tool_registry=ToolRegistry())
    agent._provider = provider
    agent._provider_for_route = lambda route: provider  # 绕开 lite 档建真 provider
    monkeypatch.setattr(agent_mod, "effective_input_budget", lambda: budget)
    return agent


def _collect_stream(agent, messages) -> tuple[str, list]:
    chunks = []

    async def run():
        async for ev in agent.stream_chat(messages):
            chunks.append(ev)

    asyncio.run(run())
    return "".join(c for c in chunks if isinstance(c, str)), chunks


def test_stream_chat_trims_proactively_before_first_call(monkeypatch, _isolated_data_dir):
    """proactive：预算很小 → 首个请求发出前就裁剪，无需等 400。"""
    provider = _make_stream_provider([_final_stream()])
    agent = _wire_agent(provider, monkeypatch, budget=100)
    text, _ = _collect_stream(agent, _long_history())
    assert provider.create_calls, "应发出请求"
    first_msgs = provider.create_calls[0]
    assert len(first_msgs) < len(_long_history()), "首个请求就应携带裁剪后的消息"


def test_stream_chat_retries_once_after_length_400(monkeypatch, _isolated_data_dir):
    """reactive：预检没拦住 → 400 越界后裁剪重试一次，用户看到可见提示。"""
    provider = _make_stream_provider(
        [RuntimeError(DASHSCOPE_400), _final_stream()]
    )
    agent = _wire_agent(provider, monkeypatch, budget=100000)  # 预检不触发
    text, _ = _collect_stream(agent, _long_history())
    assert "已根据保留的上下文完成总结" in text, "重试应成功产出回复"
    assert "会话过长" in text and "截断" in text, "应向用户提示已自动截断重试"
    assert len(provider.create_calls) == 2, "应恰好重试一次"
    # 裁剪后条数可能不变（截断提示占一位），但携带的内容总量必须变小
    size = lambda msgs: sum(len(str(m.get("content") or "")) for m in msgs)
    assert size(provider.create_calls[1]) < size(provider.create_calls[0]), "重试时内容总量应变小"


def test_stream_chat_raises_readable_error_when_untrimmable(monkeypatch, _isolated_data_dir):
    """reactive：预算内裁不动（减半后仍容不下任何前缀）→ 抛用户可读错误。"""
    provider = _make_stream_provider([RuntimeError(DASHSCOPE_400)])
    agent = _wire_agent(provider, monkeypatch, budget=2)  # 减半后为 1，无历史可裁

    async def run():
        async for _ in agent.stream_chat([Message(role="user", content="问题")]):
            pass

    with pytest.raises(RuntimeError, match="会话内容过长"):
        asyncio.run(run())
    assert len(provider.create_calls) == 1, "裁不动时不应盲目重试"


def test_chat_retries_once_after_length_400(monkeypatch, _isolated_data_dir):
    """非流式 chat()：同样 400 → 裁剪重试一次。"""
    provider = MagicMock()
    provider.model = "fake"
    calls: list[list[dict]] = []

    async def _chat(messages, tools=None, system=None, **kw):
        # 存快照而非引用：agent 层 working[:] = trimmed 是原地替换，
        # 存引用会让「第一次请求」的记录也被裁剪后的内容覆盖
        calls.append([Message(role=m.role, content=m.content) for m in messages])
        ev = _side_effects.pop(0)
        if isinstance(ev, BaseException):
            raise ev
        return ev

    _side_effects = [RuntimeError(DASHSCOPE_400), Message(role="assistant", content="总结好了")]
    provider.chat = AsyncMock(side_effect=_chat)
    agent = _wire_agent(provider, monkeypatch, budget=100000)

    resp = asyncio.run(agent.chat(_long_history()))
    assert resp.content == "总结好了"
    assert len(calls) == 2
    size = lambda msgs: sum(len(m.content or "") for m in msgs)
    assert size(calls[1]) < size(calls[0])  # 裁剪生效：重试携带的内容总量变小
