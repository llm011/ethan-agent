"""Tests for empty-reply fallback text and retry logic."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ethan.core.agent import (
    Agent,
    UsageStats,
    _empty_reply_fallback_text,
)
from ethan.providers.base import Message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(model: str = "test-model") -> MagicMock:
    """Create a mock provider with async chat method."""
    p = MagicMock()
    p.model = model
    p.chat = AsyncMock(return_value=Message(role="assistant", content="ok"))
    return p


def _make_agent(provider: MagicMock | None = None) -> Agent:
    """Create an Agent with mock provider, bypassing __init__."""
    agent = Agent.__new__(Agent)
    agent._provider = provider or _make_provider()
    agent.usage = UsageStats()
    return agent


# ---------------------------------------------------------------------------
# _empty_reply_fallback_text
# ---------------------------------------------------------------------------


class TestFallbackText:
    """Unit tests for the fallback text generator."""

    def test_stuck_with_tool_calls(self):
        text = _empty_reply_fallback_text("stuck", 5)
        assert "尝试了多种策略仍未突破" in text
        assert "已执行 5 轮工具调用" in text
        assert "超出当前步数限制" not in text
        assert "建议" in text

    def test_stuck_without_tool_calls(self):
        text = _empty_reply_fallback_text("stuck", 0)
        assert "尝试了多种策略仍未突破" in text
        assert "轮工具调用" not in text

    def test_nudge_exhausted_with_tool_calls(self):
        text = _empty_reply_fallback_text("nudge_exhausted", 3)
        assert "模型多次返回空回复" in text
        assert "已执行 3 轮工具调用" in text
        assert "超出当前步数限制" not in text
        assert "建议" in text

    def test_nudge_exhausted_without_tool_calls(self):
        text = _empty_reply_fallback_text("nudge_exhausted", 0)
        assert "模型多次返回空回复" in text
        assert "轮工具调用" not in text
        assert "可能上下文过大或模型异常" in text

    def test_varied(self):
        text = _empty_reply_fallback_text("varied", 10)
        assert "批量操作" in text
        assert "先到这里" in text
        assert "10" in text

    def test_varied_without_tool_calls(self):
        # n==0 时 varied 不应报 "0 轮批量操作"——零工具调用报轮数无意义
        text = _empty_reply_fallback_text("varied", 0)
        assert "0 轮" not in text
        assert "批量操作" not in text

    def test_finalize_with_tool_calls(self):
        text = _empty_reply_fallback_text("finalize", 20)
        assert "最大执行步数限制" in text
        assert "20" in text

    def test_finalize_without_tool_calls(self):
        text = _empty_reply_fallback_text("finalize", 0)
        assert "任务执行完毕但未生成回复" in text

    @pytest.mark.parametrize("reason", ["stuck", "nudge_exhausted", "varied"])
    @pytest.mark.parametrize("n", [0, 5])
    def test_non_finalize_never_mentions_step_limit(self, reason: str, n: int):
        """stuck/nudge_exhausted/varied should never claim step limit,
        under either the old ('超出当前步数限制') or new ('最大执行步数限制') phrasing."""
        text = _empty_reply_fallback_text(reason, n)
        assert "步数限制" not in text


# ---------------------------------------------------------------------------
# _minimal_retry
# ---------------------------------------------------------------------------


class TestMinimalRetry:
    """Unit tests for the minimal-prompt retry helper."""

    def test_returns_content_on_success(self):
        provider = _make_provider()
        provider.chat = AsyncMock(
            return_value=Message(role="assistant", content="  Hello!  ")
        )
        agent = _make_agent(provider)
        working = [
            Message(role="user", content="test"),
            Message(role="assistant", content="", tool_calls=[MagicMock()]),
        ]

        result = asyncio.run(
            agent._minimal_retry(working)
        )
        assert result == "Hello!"
        provider.chat.assert_called_once()
        # Verify tools=None and only last user message
        call_args = provider.chat.call_args
        assert call_args.kwargs.get("tools") is None
        assert len(call_args.args[0]) == 1  # only last_user

    def test_returns_none_on_empty_response(self):
        provider = _make_provider()
        provider.chat = AsyncMock(
            return_value=Message(role="assistant", content="")
        )
        agent = _make_agent(provider)

        result = asyncio.run(
            agent._minimal_retry([Message(role="user", content="test")])
        )
        assert result is None

    def test_returns_none_on_exception(self):
        provider = _make_provider()
        provider.chat = AsyncMock(side_effect=RuntimeError("api error"))
        agent = _make_agent(provider)

        result = asyncio.run(
            agent._minimal_retry([Message(role="user", content="test")])
        )
        assert result is None

    def test_injected_supplement_not_solo(self):
        """复现真实 bug（s_20260902_1727_2a9e）：运行中补充信息 append 成
        最后一条 user 消息后触发空回复兜底，重试必须带上原始任务，
        不能只发那条孤立的注入指令。"""
        provider = _make_provider()
        provider.chat = AsyncMock(return_value=Message(role="assistant", content="ok"))
        agent = _make_agent(provider)
        working = [
            Message(role="user", content="深度review PR #284 和 #255"),
            Message(role="assistant", content="", tool_calls=[MagicMock()]),
            Message(role="tool", content="diff...", tool_call_id="t1"),
            Message(role="user", content="[用户运行中补充]：别弄混了，你要评论到对应的PR上"),
        ]

        asyncio.run(agent._minimal_retry(working))
        sent = provider.chat.call_args.args[0]
        contents = [m.content for m in sent]
        # 原始任务必须在场（首条 + 末条真实消息；注入消息被过滤后真实消息只剩一条）
        assert "深度review PR #284 和 #255" in contents
        assert len(sent) == 1

    def test_first_and_last_real_user_sent(self):
        """多条真实 user 消息：发首条（原始任务）+ 末条（最新指令）。"""
        provider = _make_provider()
        provider.chat = AsyncMock(return_value=Message(role="assistant", content="ok"))
        agent = _make_agent(provider)
        working = [
            Message(role="user", content="帮我调研 A"),
            Message(role="assistant", content="done A"),
            Message(role="user", content="再看下 B"),
            Message(role="assistant", content="", tool_calls=[MagicMock()]),
            Message(role="user", content="[用户运行中补充]：注意对比两者"),
        ]

        asyncio.run(agent._minimal_retry(working))
        sent = provider.chat.call_args.args[0]
        assert [m.content for m in sent] == ["帮我调研 A", "再看下 B"]

    def test_nudge_not_solo(self):
        """nudge 合成消息同样不能独占重试上下文。"""
        provider = _make_provider()
        provider.chat = AsyncMock(return_value=Message(role="assistant", content="ok"))
        agent = _make_agent(provider)
        working = [
            Message(role="user", content="跑一下测试"),
            Message(role="assistant", content="", tool_calls=[MagicMock()]),
            Message(role="user", content="[继续。请根据已有信息回答问题，或继续使用工具完成任务。]"),
        ]

        asyncio.run(agent._minimal_retry(working))
        sent = provider.chat.call_args.args[0]
        assert [m.content for m in sent] == ["跑一下测试"]

    def test_all_synthetic_falls_back_to_last_user(self):
        """全是合成消息的极端情况：退回旧行为，发最后一条 user。"""
        provider = _make_provider()
        provider.chat = AsyncMock(return_value=Message(role="assistant", content="ok"))
        agent = _make_agent(provider)
        working = [
            Message(role="user", content="[用户运行中补充]：快一点"),
            Message(role="user", content="[继续。请根据已有信息回答问题。]"),
        ]

        asyncio.run(agent._minimal_retry(working))
        sent = provider.chat.call_args.args[0]
        assert len(sent) == 1
        assert sent[0].content.startswith("[继续。")

    def test_merged_injection_still_kept(self):
        """注入文本合并进原 user 消息时（前缀在中间），该消息仍视为真实消息。"""
        provider = _make_provider()
        provider.chat = AsyncMock(return_value=Message(role="assistant", content="ok"))
        agent = _make_agent(provider)
        merged = "review PR #284\n\n[用户运行中补充]：别弄混了"
        working = [
            Message(role="user", content=merged),
            Message(role="assistant", content="", tool_calls=[MagicMock()]),
        ]

        asyncio.run(agent._minimal_retry(working))
        sent = provider.chat.call_args.args[0]
        assert [m.content for m in sent] == [merged]

    def test_calls_usage_add(self):
        provider = _make_provider()
        provider.chat = AsyncMock(
            return_value=Message(role="assistant", content="ok", usage={"input": 10, "output": 5})
        )
        agent = _make_agent(provider)

        asyncio.run(
            agent._minimal_retry([Message(role="user", content="test")])
        )
        # usage dict 折算进 agent.usage（非 tautology：mock 带 usage，断言计数器真的增长）
        assert agent.usage.input_tokens == 10
        assert agent.usage.output_tokens == 5


# ---------------------------------------------------------------------------
# _is_synthetic_user_msg
# ---------------------------------------------------------------------------


class TestIsSyntheticUserMsg:
    """Unit tests for synthetic user-message detection."""

    @pytest.mark.parametrize(
        "content",
        [
            "[用户运行中补充]：别弄混了",
            "[System 决策提示] 基于以上工具结果",
            "[System 增强上下文] 你在上一轮提到需要更多信息",
            "[继续。请根据已有信息回答问题，或继续使用工具完成任务。]",
            "[继续执行任务。请直接调用工具完成下一步]",
            "[网络中断，请从断点继续你的回复]",
            "  [用户运行中补充]：带前导空格",
        ],
    )
    def test_synthetic(self, content: str):
        from ethan.core.agent import _is_synthetic_user_msg

        assert _is_synthetic_user_msg(content) is True

    @pytest.mark.parametrize(
        "content",
        [
            "深度review PR #284",
            "review PR #284\n\n[用户运行中补充]：合并进正文的注入不算独立合成消息",
            "继续帮我看看",  # 恰好以「继续」开头的真实用户输入
            "",
        ],
    )
    def test_real(self, content: str):
        from ethan.core.agent import _is_synthetic_user_msg

        assert _is_synthetic_user_msg(content) is False


# ---------------------------------------------------------------------------
# _ensure_non_empty
# ---------------------------------------------------------------------------


class TestEnsureNonEmpty:
    """Tests for the sync-path empty-reply handler."""

    def test_non_empty_response_returned_unchanged(self):
        provider = _make_provider()
        agent = _make_agent(provider)
        response = Message(role="assistant", content="I have an answer")
        working = [Message(role="user", content="test")]

        result = asyncio.run(
            agent._ensure_non_empty(response, working, MagicMock(), "finalize")
        )
        assert result.content == "I have an answer"
        provider.chat.assert_not_called()

    def test_empty_response_triggers_retry_success(self):
        provider = _make_provider()
        provider.chat = AsyncMock(
            return_value=Message(role="assistant", content="Retry worked!")
        )
        agent = _make_agent(provider)
        response = Message(role="assistant", content="")
        working = [Message(role="user", content="test")]

        result = asyncio.run(
            agent._ensure_non_empty(response, working, MagicMock(), "stuck")
        )
        assert result.content == "Retry worked!"

    def test_empty_response_retry_fallback(self):
        provider = _make_provider()
        provider.chat = AsyncMock(
            return_value=Message(role="assistant", content="")
        )
        agent = _make_agent(provider)
        response = Message(role="assistant", content="")
        working = [
            Message(role="user", content="test"),
            Message(role="assistant", content="", tool_calls=[MagicMock()]),
        ]

        result = asyncio.run(
            agent._ensure_non_empty(response, working, MagicMock(), "nudge_exhausted")
        )
        # nudge_exhausted should NOT contain misleading step-limit text
        assert "超出当前步数限制" not in result.content
        assert "模型多次返回空回复" in result.content

    def test_finalize_fallback_mentions_step_limit(self):
        provider = _make_provider()
        provider.chat = AsyncMock(
            return_value=Message(role="assistant", content="")
        )
        agent = _make_agent(provider)
        response = Message(role="assistant", content="")
        working = [
            Message(role="user", content="test"),
            Message(role="assistant", content="", tool_calls=[MagicMock()]),
        ]

        result = asyncio.run(
            agent._ensure_non_empty(response, working, MagicMock(), "finalize")
        )
        assert "最大执行步数限制" in result.content
