r"""Tests for agent 层 mid-stream timeout fallback（PR #302 review 回归）。

覆盖两块新逻辑：
1. FallbackProvider.get_next_provider()——超时后取链上下一个可用 provider，
   并给超时的那个记一次熔断失败；
2. Agent._get_timeout_fallback()——优先走 FallbackProvider 链，链上没有时
   回退 defaults.fallback_model 配置（同模型不回退、创建失败返回 None）。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ethan.core import agent as agent_mod
from ethan.core.agent import Agent
from ethan.providers.circuit_breaker import (
    _FAILURE_THRESHOLD,
    get_circuit_breaker,
)
from ethan.providers.fallback import FallbackProvider


def _provider(model: str) -> MagicMock:
    p = MagicMock()
    p.model = model
    return p


class _Defaults:
    def __init__(self, fallback_model: str = ""):
        self.fallback_model = fallback_model


class _Cfg:
    def __init__(self, fallback_model: str = ""):
        self.defaults = _Defaults(fallback_model)


def _make_agent() -> Agent:
    with patch.object(Agent, "__init__", lambda self, *a, **kw: None):
        return Agent()


@pytest.fixture()
def breaker():
    cb = get_circuit_breaker()
    for key in list(cb._providers.keys()):
        cb.reset(key)
    yield cb
    for key in list(cb._providers.keys()):
        cb.reset(key)


# ---------------------------------------------------------------------------
# FallbackProvider.get_next_provider
# ---------------------------------------------------------------------------

class TestGetNextProvider:
    def test_returns_next_after_last_used(self, breaker):
        p1, p2, p3 = _provider("m1"), _provider("m2"), _provider("m3")
        fp = FallbackProvider([("k1", p1), ("k2", p2), ("k3", p3)])
        fp._last_used = p2
        assert fp.get_next_provider() is p3

    def test_records_failure_for_last_used(self, breaker):
        p1, p2 = _provider("m1"), _provider("m2")
        fp = FallbackProvider([("k1", p1), ("k2", p2)])
        fp._last_used = p2
        fp.get_next_provider()
        assert breaker._providers["k2"].failures == 1
        # p3 之后的候选若被熔断打开则跳过
        assert fp.get_next_provider() is None  # p2 后面没有别的 provider

    def test_skips_open_circuit(self, breaker):
        p1, p2, p3 = _provider("m1"), _provider("m2"), _provider("m3")
        fp = FallbackProvider([("k1", p1), ("k2", p2), ("k3", p3)])
        fp._last_used = p2
        for _ in range(_FAILURE_THRESHOLD):
            breaker.record_failure("k3")
        assert fp.get_next_provider() is None

    def test_none_when_last_used_is_last(self, breaker):
        p1, p2 = _provider("m1"), _provider("m2")
        fp = FallbackProvider([("k1", p1), ("k2", p2)])
        fp._last_used = p2
        assert fp.get_next_provider() is None

    def test_none_when_never_used(self, breaker):
        p1 = _provider("m1")
        fp = FallbackProvider([("k1", p1)])
        assert fp.get_next_provider() is None


# ---------------------------------------------------------------------------
# Agent._get_timeout_fallback
# ---------------------------------------------------------------------------

class TestGetTimeoutFallback:
    def test_prefers_fallback_chain_next(self, monkeypatch, breaker):
        p1, p2 = _provider("m1"), _provider("m2")
        fp = FallbackProvider([("k1", p1), ("k2", p2)])
        fp._last_used = p1

        called = False

        def _no_create(model):
            nonlocal called
            called = True
            return _provider(model)

        monkeypatch.setattr(agent_mod, "get_config", lambda: _Cfg("cfg/fallback"))
        monkeypatch.setattr(agent_mod, "create_provider", _no_create)
        agent = _make_agent()
        assert agent._get_timeout_fallback(fp) is p2
        assert not called  # 链上有下一个就不会去建配置里的 fallback

    def test_falls_back_to_config_model(self, monkeypatch, breaker):
        p1 = _provider("m1")
        fp = FallbackProvider([("k1", p1)])  # 链上只有超时的这个，无下一个
        fp._last_used = p1

        created = _provider("cfg/fallback")
        monkeypatch.setattr(agent_mod, "get_config", lambda: _Cfg("cfg/fallback"))
        monkeypatch.setattr(agent_mod, "create_provider", lambda m: created)
        agent = _make_agent()
        assert agent._get_timeout_fallback(fp) is created

    def test_config_model_same_as_current_returns_none(self, monkeypatch, breaker):
        p1 = _provider("m1")
        fp = FallbackProvider([("k1", p1)])
        fp._last_used = p1
        monkeypatch.setattr(agent_mod, "get_config", lambda: _Cfg("m1"))
        monkeypatch.setattr(agent_mod, "create_provider", lambda m: _provider(m))
        agent = _make_agent()
        assert agent._get_timeout_fallback(fp) is None

    def test_no_fallback_model_returns_none(self, monkeypatch, breaker):
        p1 = _provider("m1")
        monkeypatch.setattr(agent_mod, "get_config", lambda: _Cfg(""))
        monkeypatch.setattr(agent_mod, "create_provider", lambda m: _provider(m))
        agent = _make_agent()
        assert agent._get_timeout_fallback(p1) is None

    def test_create_provider_failure_returns_none(self, monkeypatch, breaker):
        p1 = _provider("m1")

        def _boom(model):
            raise RuntimeError("bad model config")

        monkeypatch.setattr(agent_mod, "get_config", lambda: _Cfg("cfg/fallback"))
        monkeypatch.setattr(agent_mod, "create_provider", _boom)
        agent = _make_agent()
        assert agent._get_timeout_fallback(p1) is None
