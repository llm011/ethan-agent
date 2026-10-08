"""Tests for openai_compat connect-phase retry behavior.

建连阶段（create()）对瞬态连接类错误的有界重试：
- 第一次 APIConnectionError、第二次成功 → 流正常产出
- 重试耗尽仍失败 → 抛出最后异常
- 非连接类错误（如鉴权）→ 不重试直接抛
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ethan.providers.base import Message
from ethan.providers.openai_compat import (
    OpenAICompatProvider,
    _is_transient_connect_error,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider() -> OpenAICompatProvider:
    cfg = MagicMock()
    cfg.api_key = "test-key"
    cfg.base_url = "http://127.0.0.1:59999/v1"
    cfg.proxy = None
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider._client = MagicMock()
    provider._model = "test-model"
    provider._base_url = cfg.base_url.lower()
    provider._vision = None
    return provider


def _fake_stream_response(chunks: list[str]) -> MagicMock:
    """构造一个带 __aiter__ 的伪流式响应。"""

    async def _aiter():
        for c in chunks:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock()
            chunk.choices[0].delta.content = c
            chunk.choices[0].delta.reasoning_content = None
            chunk.choices[0].delta.tool_calls = None
            chunk.usage = None
            yield chunk
        final = MagicMock()
        final.choices = [MagicMock()]
        final.choices[0].delta = MagicMock()
        final.choices[0].delta.content = None
        final.choices[0].delta.reasoning_content = None
        final.choices[0].delta.tool_calls = None
        final.usage = None
        final.choices[0].finish_reason = "stop"
        yield final

    resp = MagicMock()
    resp.__aiter__ = lambda self: _aiter()
    return resp


# ---------------------------------------------------------------------------
# _is_transient_connect_error
# ---------------------------------------------------------------------------

def test_connection_error_is_transient():
    from openai import APIConnectionError

    httpx_req = MagicMock()
    err = APIConnectionError(request=httpx_req)
    assert _is_transient_connect_error(err) is True


def test_auth_error_is_not_transient():
    from openai import AuthenticationError

    resp = MagicMock()
    resp.status_code = 401
    err = AuthenticationError("Invalid API key", response=resp, body=None)
    assert _is_transient_connect_error(err) is False


def test_keyword_matches_server_disconnected():
    err = RuntimeError("Server disconnected without sending a response")
    assert _is_transient_connect_error(err) is True


def test_plain_runtime_error_is_not_transient():
    assert _is_transient_connect_error(RuntimeError("something exploded")) is False


# ---------------------------------------------------------------------------
# _create_stream_with_retry
# ---------------------------------------------------------------------------

def test_retry_then_success():
    provider = _make_provider()
    good = _fake_stream_response(["hello"])

    provider._client.chat.completions.create = AsyncMock(
        side_effect=[ConnectionError("Connection error."), good]
    )

    kwargs = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    resp = asyncio.run(provider._create_stream_with_retry(kwargs))
    assert resp is good
    assert provider._client.chat.completions.create.await_count == 2


def test_retries_exhausted_raises():
    provider = _make_provider()

    provider._client.chat.completions.create = AsyncMock(
        side_effect=ConnectionError("Connection error.")
    )

    kwargs = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(ConnectionError):
        asyncio.run(provider._create_stream_with_retry(kwargs))
    # 初始 + _MAX_CONNECT_RETRIES 次重试
    assert provider._client.chat.completions.create.await_count == 1 + 2


def test_non_transient_error_no_retry():
    provider = _make_provider()

    provider._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("Invalid API key provided")
    )

    kwargs = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(RuntimeError, match="Invalid API key"):
        asyncio.run(provider._create_stream_with_retry(kwargs))
    assert provider._client.chat.completions.create.await_count == 1


# ---------------------------------------------------------------------------
# stream_chat 端到端（mock client）
# ---------------------------------------------------------------------------

def test_stream_chat_recovers_from_connect_error():
    provider = _make_provider()
    good = _fake_stream_response(["你好", "！"])

    provider._client.chat.completions.create = AsyncMock(
        side_effect=[ConnectionError("Connection error."), good]
    )

    async def _run():
        out = []
        async for chunk in provider.stream_chat([Message(role="user", content="hi")]):
            if chunk.content:
                out.append(chunk.content)
        return "".join(out)

    assert asyncio.run(_run()) == "你好！"
    assert provider._client.chat.completions.create.await_count == 2


# ---------------------------------------------------------------------------
# 非流式 chat() 建连重试（schedule/标题压缩等后台任务路径）
# ---------------------------------------------------------------------------

def test_non_stream_chat_recovers_from_connect_error():
    provider = _make_provider()
    good = MagicMock()
    good.choices = [MagicMock()]
    # parse_choice 会读 message.content / message.tool_calls 做解析，须给真值
    good.choices[0].message.content = "ok"
    good.choices[0].message.tool_calls = None
    good.choices[0].finish_reason = "stop"
    good.usage = None

    provider._client.chat.completions.create = AsyncMock(
        side_effect=[ConnectionError("Connection error."), good]
    )

    resp = asyncio.run(provider.chat([Message(role="user", content="hi")]))
    assert resp.content == "ok"
    assert provider._client.chat.completions.create.await_count == 2


def test_non_stream_chat_no_retry_on_auth_error():
    provider = _make_provider()

    provider._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("Invalid API key provided")
    )

    with pytest.raises(RuntimeError, match="Invalid API key"):
        asyncio.run(provider.chat([Message(role="user", content="hi")]))
    assert provider._client.chat.completions.create.await_count == 1
