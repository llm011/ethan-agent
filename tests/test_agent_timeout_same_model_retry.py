"""Agent 层超时/连接失败兜底链的端到端回归。

线上事故（s_20261009_1653_abce，手机端发送后 loading 2 分钟整轮失败）：
- 上游 LLM（buddy-proxy/glm-5.3-flash）首请求 120s 未吐首字节 → APITimeoutError；
- provider 层 max_retries=0 直接冒泡；agent 层 _get_timeout_fallback 因
  未配 fallback_model 返回 None → 直接 raise，整轮失败，用户只看到
  「任务已中断：Request timed out.」。

修复后的兜底链（每层都有界）：
1. provider 层首请求超时重试 1 次（_MAX_TIMEOUT_RETRIES）；
2. agent 层有备选模型 → 切换备选模型重试（既有行为）；
3. agent 层无备选模型 → 同模型重发一次（本文件覆盖的新行为）；
4. 仍失败才冒泡 → interrupted + 错误落库。

用真实 Agent + 假 provider（Memory 型 mock）走完整 stream_chat 循环，
确保新分支真的被走到，而不是只测 _get_timeout_fallback 单元逻辑。
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from ethan.core.agent import Agent
from ethan.providers.base import Message, StreamChunk


def _make_agent(provider) -> Agent:
    """构造最小 Agent：绕过 __init__ 的磁盘/网络副作用，只挂测试需要的字段。"""
    agent = Agent.__new__(Agent)
    agent._provider = provider
    agent._lite_provider = None
    agent.usage = MagicMock()
    agent.usage.add = MagicMock()
    agent._registry = MagicMock()
    agent._registry.all.return_value = []
    agent._skills = None
    agent._channel = ""
    agent._mode = ""
    agent._system_files = {}
    agent.session_id = ""
    agent.is_owner = False
    agent.last_matched_skills = []
    agent.runtime_context = ""
    agent._executor = MagicMock()
    agent._procedures = MagicMock()
    agent._max_iterations = 5
    agent._trim_input_if_needed = MagicMock()
    return agent


class _TimeoutProvider:
    """第一次 stream_chat 抛超时，之后正常产出。模拟「同模型重发就能过」。"""

    model = "buddy-proxy/glm-5.3-flash"

    def __init__(self, fail_with):
        self._fail_with = fail_with
        self.calls: list[list[Message]] = []

    async def stream_chat(self, messages, tools=None, system=None):
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            raise self._fail_with
        yield StreamChunk(content="重试成功")
        yield StreamChunk(content="", is_final=True)


async def _collect(agen):
    out = []
    async for ev in agen:
        out.append(ev)
    return out


def _run(fail_with: Exception):
    provider = _TimeoutProvider(fail_with)
    agent = _make_agent(provider)
    # _get_timeout_fallback 返回 None：模拟「未配 fallback_model、非 FallbackProvider」
    with patch.object(Agent, "_get_timeout_fallback", return_value=None):
        out = asyncio.run(
            _collect(agent.stream_chat([Message(role="user", content="手机豆包给飞书群发消息")]))
        )
    return provider, out


class TestSameModelRetry:
    def test_openai_api_timeout_retried_same_model(self):
        """openai.APITimeoutError（不继承内置 TimeoutError）+ 无备选模型 →
        同模型重发一次，整轮成功。这是本次事故的直接回归用例。"""
        import openai

        e = openai.APITimeoutError(request=MagicMock())
        provider, out = _run(e)

        assert len(provider.calls) == 2, "应当重发了一次"
        text = "".join(c for c in out if isinstance(c, str))
        assert "重试成功" in text

    def test_builtin_timeout_retried_same_model(self):
        """内置 TimeoutError（openai_compat 流式 chunk 超时抛的）同样走同模型重试。"""
        provider, out = _run(TimeoutError("模型响应超时：超过 120 秒未收到新数据"))

        assert len(provider.calls) == 2
        text = "".join(c for c in out if isinstance(c, str))
        assert "重试成功" in text

    def test_connection_error_retried_same_model(self):
        """连接类错误（Connection error.）同样兜底：fallback._is_retriable 能接住。"""
        provider, out = _run(RuntimeError("Connection error."))

        assert len(provider.calls) == 2
        assert "重试成功" in "".join(c for c in out if isinstance(c, str))

    def test_second_failure_raises(self):
        """同模型重试后仍超时 → 冒泡（不能无限重试拖成分钟级挂起）。"""
        import openai

        class _AlwaysTimeout(_TimeoutProvider):
            async def stream_chat(self, messages, tools=None, system=None):
                self.calls.append(list(messages))
                raise openai.APITimeoutError(request=MagicMock())
                yield  # pragma: no cover

        provider = _AlwaysTimeout(openai.APITimeoutError(request=MagicMock()))
        agent = _make_agent(provider)
        with patch.object(Agent, "_get_timeout_fallback", return_value=None):
            with pytest.raises(openai.APITimeoutError):
                asyncio.run(
                    _collect(agent.stream_chat([Message(role="user", content="帮我 echo hello")]))
                )
        assert len(provider.calls) == 2

    def test_retry_only_once_across_iters(self):
        """重试只允许一次：后续迭代再超时直接冒泡，不循环。"""
        import openai

        class _TimeoutThenTimeout(_TimeoutProvider):
            async def stream_chat(self, messages, tools=None, system=None):
                self.calls.append(list(messages))
                raise openai.APITimeoutError(request=MagicMock())
                yield  # pragma: no cover

        provider = _TimeoutThenTimeout(openai.APITimeoutError(request=MagicMock()))
        agent = _make_agent(provider)
        with patch.object(Agent, "_get_timeout_fallback", return_value=None):
            with pytest.raises(openai.APITimeoutError):
                asyncio.run(
                    _collect(agent.stream_chat([Message(role="user", content="帮我 echo hello")]))
                )
        assert len(provider.calls) == 2

    def test_non_retriable_error_not_retried(self):
        """非瞬态错误（如鉴权失败）不进同模型重试，直接冒泡。"""

        class _AuthFail(_TimeoutProvider):
            async def stream_chat(self, messages, tools=None, system=None):
                self.calls.append(list(messages))
                raise RuntimeError("Invalid API key provided")
                yield  # pragma: no cover

        provider = _AuthFail(RuntimeError("Invalid API key provided"))
        agent = _make_agent(provider)
        with patch.object(Agent, "_get_timeout_fallback", return_value=None):
            with pytest.raises(RuntimeError, match="Invalid API key"):
                asyncio.run(
                    _collect(agent.stream_chat([Message(role="user", content="帮我 echo hello")]))
                )
        assert len(provider.calls) == 1

    def test_fallback_provider_still_preferred(self):
        """有备选模型时仍优先切换备选（既有行为不回退）。"""
        import openai

        class _GoodProvider(_TimeoutProvider):
            async def stream_chat(self, messages, tools=None, system=None):
                self.calls.append(list(messages))
                yield StreamChunk(content="from fallback")
                yield StreamChunk(content="", is_final=True)

        fb_provider = _GoodProvider(None)

        class _FirstCallTimeout(_TimeoutProvider):
            async def stream_chat(self, messages, tools=None, system=None):
                self.calls.append(list(messages))
                if len(self.calls) == 1:
                    raise openai.APITimeoutError(request=MagicMock())
                yield StreamChunk(content="from primary")
                yield StreamChunk(content="", is_final=True)

        provider = _FirstCallTimeout(None)
        agent = _make_agent(provider)
        with patch.object(Agent, "_get_timeout_fallback", return_value=fb_provider):
            out = asyncio.run(
                _collect(agent.stream_chat([Message(role="user", content="帮我 echo hello")]))
            )
        # 备选模型成功：主 provider 只被调用 1 次，备选产出直达用户
        assert len(provider.calls) == 1
        assert len(fb_provider.calls) == 1
        assert "from fallback" in "".join(c for c in out if isinstance(c, str))
