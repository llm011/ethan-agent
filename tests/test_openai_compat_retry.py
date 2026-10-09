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


def test_api_timeout_error_is_not_transient():
    """APITimeoutError 是 APIConnectionError 的子类，必须排除出连接类重试：
    挂着不响应的网关要等满 120s 才抛超时，与连接类同享 2 次重试会把最坏情况
    放大到 3×120s。超时走专属路径（_is_first_request_timeout，最多 1 次）。"""
    from openai import APITimeoutError

    httpx_req = MagicMock()
    err = APITimeoutError(request=httpx_req)
    assert _is_transient_connect_error(err) is False


def test_timeout_message_is_not_transient():
    """文案层面的超时（"Request timed out."）也不进连接类重试。"""
    assert _is_transient_connect_error(RuntimeError("Request timed out.")) is False


def test_first_request_timeout_detection():
    """_is_first_request_timeout：SDK 类型 + 文案两条路径都要接住。"""
    from openai import APITimeoutError

    from ethan.providers.openai_compat import _is_first_request_timeout

    assert _is_first_request_timeout(APITimeoutError(request=MagicMock())) is True
    assert _is_first_request_timeout(RuntimeError("Request timed out.")) is True
    assert _is_first_request_timeout(RuntimeError("Connection error.")) is False
    assert _is_first_request_timeout(RuntimeError("Invalid API key")) is False


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


@pytest.mark.parametrize("code", [500, 501, 502, 503, 504, 599])
def test_http_5xx_is_transient(code):
    """建连阶段收到 5xx（含裸 500，截图里那个 badcase）要重试，不能直接冒泡
    中断会话。此前只把连接类异常判为瞬态，网关回 500 时会当场失败。"""
    from openai import APIStatusError

    resp = MagicMock()
    resp.status_code = code
    err = APIStatusError(f"Error code: {code}", response=resp, body=None)
    assert _is_transient_connect_error(err) is True


def test_http_500_internal_server_error_is_transient():
    from openai import InternalServerError

    resp = MagicMock()
    resp.status_code = 500
    err = InternalServerError("Error code: 500", response=resp, body=None)
    assert _is_transient_connect_error(err) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413, 422])
def test_http_4xx_except_429_not_transient(code):
    """4xx（鉴权/参数/上下文超限）重试没有意义，必须立即抛出——
    400 另有裁剪历史/剥图的专门兜底路径。"""
    from openai import APIStatusError

    resp = MagicMock()
    resp.status_code = code
    err = APIStatusError(f"Error code: {code}", response=resp, body=None)
    assert _is_transient_connect_error(err) is False


def test_http_429_is_transient():
    from openai import APIStatusError

    resp = MagicMock()
    resp.status_code = 429
    err = APIStatusError("rate limited", response=resp, body=None)
    assert _is_transient_connect_error(err) is True


def test_500_text_keyword_is_transient():
    # 网关把 5xx 压成纯文本、拿不到 status_code 时的兜底识别
    assert _is_transient_connect_error(RuntimeError("500 Internal Server Error")) is True


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


def test_real_api_connection_error_retried():
    """用真实 APIConnectionError（isinstance 路径）验证重试循环。"""
    from openai import APIConnectionError

    provider = _make_provider()
    good = _fake_stream_response(["ok"])

    provider._client.chat.completions.create = AsyncMock(
        side_effect=[APIConnectionError(request=MagicMock()), good]
    )

    kwargs = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    resp = asyncio.run(provider._create_stream_with_retry(kwargs))
    assert resp is good
    assert provider._client.chat.completions.create.await_count == 2


def test_api_timeout_error_retried_once():
    """首请求超时（APITimeoutError）重试 1 次后仍失败才抛。

    线上事故（s_202609… 手机端发送后 loading 2 分钟整轮失败）：上游偶发
    120s 内不吐首字节，同配置相邻请求时好时坏。此前不重试直接冒泡，
    现在重试 1 次（最坏 2×120s≈4 分钟，不会像连接类错误那样放大到 3×120s）。
    """
    from openai import APITimeoutError

    provider = _make_provider()
    good = _fake_stream_response(["ok"])

    provider._client.chat.completions.create = AsyncMock(
        side_effect=[APITimeoutError(request=MagicMock()), good]
    )

    kwargs = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    resp = asyncio.run(provider._create_stream_with_retry(kwargs))
    assert resp is good
    assert provider._client.chat.completions.create.await_count == 2


def test_api_timeout_error_exhausts_retry():
    """首请求超时重试 1 次后仍超时：抛出（不再重试，交给 agent 层兜底）。"""
    from openai import APITimeoutError

    provider = _make_provider()

    provider._client.chat.completions.create = AsyncMock(
        side_effect=APITimeoutError(request=MagicMock())
    )

    kwargs = {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(Exception):
        asyncio.run(provider._create_stream_with_retry(kwargs))
    # 初始 + _MAX_TIMEOUT_RETRIES（1）次
    assert provider._client.chat.completions.create.await_count == 2


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
