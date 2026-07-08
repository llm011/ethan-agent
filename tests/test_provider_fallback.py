"""Tests for provider circuit breaker and fallback logic."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ethan.providers.base import Message, StreamChunk
from ethan.providers.circuit_breaker import (
    _BACKOFF_BASE,
    _FAILURE_THRESHOLD,
    CircuitBreaker,
    ProviderState,
)
from ethan.providers.fallback import FallbackProvider, _is_retriable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(model: str = "test-model") -> MagicMock:
    p = MagicMock()
    p.model = model
    p.chat = AsyncMock(return_value=Message(role="assistant", content="ok"))

    async def _stream(*args, **kwargs):
        yield StreamChunk(content="hello", is_final=True)

    p.stream_chat = _stream
    return p


def _make_failing_provider(error: Exception, model: str = "test-model") -> MagicMock:
    p = MagicMock()
    p.model = model
    p.chat = AsyncMock(side_effect=error)

    async def _stream(*args, **kwargs):
        raise error
        yield  # noqa: unreachable — makes this a generator

    p.stream_chat = _stream
    return p


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_initially_available(self):
        cb = CircuitBreaker()
        assert cb.is_available("p1") is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker()
        for _ in range(_FAILURE_THRESHOLD):
            cb.record_failure("p1")
        assert cb.is_available("p1") is False

    def test_does_not_open_before_threshold(self):
        cb = CircuitBreaker()
        for _ in range(_FAILURE_THRESHOLD - 1):
            cb.record_failure("p1")
        assert cb.is_available("p1") is True

    def test_success_resets_failures(self):
        cb = CircuitBreaker()
        cb.record_failure("p1")
        cb.record_failure("p1")
        cb.record_success("p1")
        cb.record_failure("p1")  # back to 1, not 3 — should not open
        assert cb.is_available("p1") is True

    def test_half_open_after_backoff(self, monkeypatch):
        import time as _time
        cb = CircuitBreaker()
        for _ in range(_FAILURE_THRESHOLD):
            cb.record_failure("p1")
        assert cb._providers["p1"].state == ProviderState.OPEN

        # Simulate backoff elapsed
        monkeypatch.setattr(_time, "monotonic", lambda: 10_000_000.0)
        assert cb.is_available("p1") is True
        assert cb._providers["p1"].state == ProviderState.HALF_OPEN

    def test_backoff_doubles(self):
        cb = CircuitBreaker()
        for _ in range(_FAILURE_THRESHOLD):
            cb.record_failure("p1")
        first_backoff = _BACKOFF_BASE
        assert cb._providers["p1"].backoff == first_backoff * 2

    def test_reset_clears_state(self):
        cb = CircuitBreaker()
        for _ in range(_FAILURE_THRESHOLD):
            cb.record_failure("p1")
        cb.reset("p1")
        assert cb.is_available("p1") is True


# ---------------------------------------------------------------------------
# is_retriable
# ---------------------------------------------------------------------------

class TestIsRetriable:
    def test_connection_keyword(self):
        assert _is_retriable(RuntimeError("connection refused"))

    def test_timeout_keyword(self):
        assert _is_retriable(RuntimeError("timeout waiting for server"))

    def test_502_keyword(self):
        assert _is_retriable(RuntimeError("upstream returned 502"))

    def test_non_retriable(self):
        assert not _is_retriable(ValueError("invalid request"))

    def test_httpx_connect_error(self):
        import httpx
        assert _is_retriable(httpx.ConnectError("refused"))

    def test_httpx_4xx_non_retriable(self):
        import httpx
        req = httpx.Request("POST", "http://x")
        resp = httpx.Response(400, request=req)
        assert not _is_retriable(httpx.HTTPStatusError("bad", request=req, response=resp))

    def test_httpx_429_retriable(self):
        import httpx
        req = httpx.Request("POST", "http://x")
        resp = httpx.Response(429, request=req)
        assert _is_retriable(httpx.HTTPStatusError("rate", request=req, response=resp))


# ---------------------------------------------------------------------------
# FallbackProvider — chat
# ---------------------------------------------------------------------------

class TestFallbackProviderChat:
    def test_primary_success_no_fallback(self):
        primary = _make_provider("m1")
        fp = FallbackProvider([("p1", primary)])
        result = asyncio.run(fp.chat([Message(role="user", content="hi")]))
        assert result.content == "ok"
        primary.chat.assert_awaited_once()

    def test_falls_back_on_retriable_error(self):
        primary = _make_failing_provider(RuntimeError("connection failed"))
        backup = _make_provider("m2")
        fp = FallbackProvider([("p1", primary), ("p2", backup)])
        result = asyncio.run(fp.chat([Message(role="user", content="hi")]))
        assert result.content == "ok"
        backup.chat.assert_awaited_once()

    def test_raises_on_non_retriable_error(self):
        primary = _make_failing_provider(ValueError("bad request"))
        backup = _make_provider("m2")
        fp = FallbackProvider([("p1", primary), ("p2", backup)])
        with pytest.raises(ValueError, match="bad request"):
            asyncio.run(fp.chat([Message(role="user", content="hi")]))
        backup.chat.assert_not_awaited()

    def test_all_providers_fail_raises_last(self):
        e1 = RuntimeError("connection p1")
        e2 = RuntimeError("connection p2")
        fp = FallbackProvider([
            ("p1", _make_failing_provider(e1)),
            ("p2", _make_failing_provider(e2)),
        ])
        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(fp.chat([Message(role="user", content="hi")]))
        assert "connection p2" in str(exc_info.value)

    def test_skips_open_circuit(self):
        primary = _make_failing_provider(RuntimeError("connection p1"))
        backup = _make_provider("m2")
        fp = FallbackProvider([("p1", primary), ("p2", backup)])
        from ethan.providers.circuit_breaker import get_circuit_breaker
        breaker = get_circuit_breaker()
        breaker.reset("p1")
        breaker.reset("p2")

        # Open p1 manually
        for _ in range(_FAILURE_THRESHOLD):
            breaker.record_failure("p1")

        result = asyncio.run(fp.chat([Message(role="user", content="hi")]))
        assert result.content == "ok"
        primary.chat.assert_not_awaited()  # skipped because circuit is open

    def setup_method(self):
        from ethan.providers.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        for key in list(cb._providers.keys()):
            cb.reset(key)


# ---------------------------------------------------------------------------
# FallbackProvider — stream_chat
# ---------------------------------------------------------------------------

class TestFallbackProviderStream:
    async def _collect(self, provider, messages):
        chunks = []
        async for c in provider.stream_chat(messages):
            chunks.append(c)
        return chunks

    def test_primary_stream_success(self):
        primary = _make_provider()
        fp = FallbackProvider([("p1", primary)])
        chunks = asyncio.run(self._collect(fp, [Message(role="user", content="hi")]))
        assert len(chunks) == 1
        assert chunks[0].content == "hello"

    def test_stream_falls_back_before_first_chunk(self):
        primary = _make_failing_provider(RuntimeError("connection failed"))
        backup = _make_provider()
        fp = FallbackProvider([("p1", primary), ("p2", backup)])
        chunks = asyncio.run(self._collect(fp, [Message(role="user", content="hi")]))
        assert any(c.content == "hello" for c in chunks)

    def setup_method(self):
        from ethan.providers.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        for key in list(cb._providers.keys()):
            cb.reset(key)
