"""流式中途断连（peer closed / incomplete chunked read）的 salvage 与重试行为。

复现线上问题：中转服务提前关闭连接时，
1. 已产出内容 → 应 salvage（truncated 收尾，不重试、不重复输出）；
2. 未产出内容 → 带退避重试（最多 _MAX_STREAM_BREAK_RETRIES 次），仍失败才抛错；
3. _friendly_error 应把这类错误归类为"中途断开（发「继续」补全）"，
   而非被通用 connection 分支误判成"中转不可达（切换 model）"。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx

from ethan.core.config import ProviderConfig
from ethan.providers.base import Message
from ethan.providers.openai_compat import OpenAICompatProvider

BREAK_ERR = httpx.RemoteProtocolError(
    "peer closed connection without sending complete message body (incomplete chunked read)"
)


def _chunk(content: str = "", finish_reason: str | None = None):
    delta = SimpleNamespace(
        content=content or None, tool_calls=None,
        reasoning_content=None, model_extra={},
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


class FakeStream:
    """依序产出 events：chunk 正常返回，Exception 抛出，耗尽后 StopAsyncIteration。"""

    def __init__(self, events):
        self._events = list(events)
        self.closed = False

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
        self.closed = True


def _make_provider(streams: list):
    cfg = ProviderConfig(api_key="test-key", base_url="https://relay.test/v1")
    p = OpenAICompatProvider(cfg, "test-model")
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=lambda **kw: streams.pop(0))
    p._client = client
    return p


def _collect(provider) -> list:
    async def run():
        out = []
        async for c in provider.stream_chat([Message(role="user", content="hi")]):
            out.append(c)
        return out

    return asyncio.run(run())


class TestStreamBreakHandling:
    def test_break_after_content_salvages_without_retry(self, monkeypatch):
        """已流出正文后断连：保留内容、truncated 收尾、不重发请求（避免重复输出）。"""
        async def _no_sleep(_t):
            pass

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)
        streams = [FakeStream([_chunk("Hello "), _chunk("world"), BREAK_ERR])]
        p = _make_provider(streams)
        out = _collect(p)

        assert "".join(c.content for c in out if c.content) == "Hello world"
        finals = [c for c in out if c.is_final]
        assert finals and finals[-1].truncated is True
        p._client.chat.completions.create.assert_awaited_once()

    def test_break_with_no_content_retries_then_succeeds(self, monkeypatch):
        """未产出内容即断连：退避重试，第二次请求成功则正常返回。"""
        async def _no_sleep(_t):
            pass

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)
        streams = [
            FakeStream([BREAK_ERR]),
            FakeStream([_chunk("World"), _chunk(finish_reason="stop")]),
        ]
        p = _make_provider(streams)
        out = _collect(p)

        assert "".join(c.content for c in out if c.content) == "World"
        assert not any(c.truncated for c in out)
        assert p._client.chat.completions.create.await_count == 2

    def test_break_with_no_content_exhausts_retries_and_raises(self, monkeypatch):
        """未产出内容且重试耗尽：共 3 次尝试后抛出原始错误。"""
        async def _no_sleep(_t):
            pass

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)
        streams = [FakeStream([BREAK_ERR]) for _ in range(3)]
        p = _make_provider(streams)
        try:
            _collect(p)
            raise AssertionError("should have raised")
        except httpx.RemoteProtocolError:
            pass
        assert p._client.chat.completions.create.await_count == 3


class TestFriendlyErrorClassification:
    def test_midstream_break_gets_continue_hint(self):
        from ethan.interface.routers.helpers import _friendly_error

        msg = _friendly_error(BREAK_ERR, None)
        assert "继续" in msg
        assert "中转服务不可达" not in msg

    def test_connection_reset_gets_continue_hint(self):
        from ethan.interface.routers.helpers import _friendly_error

        msg = _friendly_error(RuntimeError("Connection reset by peer"), None)
        assert "继续" in msg
        assert "中转服务不可达" not in msg

    def test_setup_connection_error_keeps_relay_hint(self):
        from ethan.interface.routers.helpers import _friendly_error

        msg = _friendly_error(RuntimeError("Connection error."), None)
        assert "中转服务不可达" in msg
