"""验证所有 LLM Provider 请求按 ETHAN_SESSION_ID 自动注入 x-session-id 请求头。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ethan.core.config import ProviderConfig
from ethan.core.context import ETHAN_SESSION_ID, set_session_id
from ethan.providers.anthropic import AnthropicProvider
from ethan.providers.base import Message
from ethan.providers.openai_compat import OpenAICompatProvider


@pytest.fixture(autouse=True)
def _reset_session_ctx():
    tok = ETHAN_SESSION_ID.set("")
    try:
        yield
    finally:
        ETHAN_SESSION_ID.reset(tok)


def test_openai_compat_injects_x_session_id_and_isolates_concurrency():
    captured: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append((request.url.path, request.headers.get("x-session-id")))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "glm-5.3",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            },
        )

    async def _run():
        cfg = ProviderConfig(base_url="http://127.0.0.1:8787/v1", api_key="test-key")
        prov = OpenAICompatProvider(cfg, model="glm-5.3")
        prov._client._client._transport = httpx.MockTransport(handler)
        try:
            # 1) 无 session_id 时不注入
            await prov.chat([Message(role="user", content="hi")])
            assert captured[-1][1] is None

            # 2) 并发两个不同会话，各自注入自己的 x-session-id，互不串号
            async def run_for(sid: str):
                set_session_id(sid)
                await asyncio.sleep(0.01)
                await prov.chat([Message(role="user", content=sid)])

            await asyncio.gather(run_for("sess-alpha"), run_for("sess-beta"))
            sids = sorted(h for _, h in captured[1:] if h is not None)
            assert sids == ["sess-alpha", "sess-beta"]
        finally:
            await prov.close()

    asyncio.run(_run())


def test_anthropic_injects_x_session_id_and_preserves_clean_headers():
    captured_headers: list[httpx.Headers] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers)
        body = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return httpx.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"})

    async def _run():
        cfg = ProviderConfig(base_url="http://127.0.0.1:8787", api_key="test-key")
        prov = AnthropicProvider(cfg, model="claude-sonnet-4-6")
        prov._client._client._transport = httpx.MockTransport(handler)
        try:
            # 无 session_id
            await prov.chat([Message(role="user", content="hi")])
            assert captured_headers[-1].get("x-session-id") is None
            assert captured_headers[-1].get("user-agent") == "python-httpx/0.28.1"
            assert not any(k.lower().startswith("x-stainless") for k in captured_headers[-1].keys())

            # 有 session_id
            set_session_id("sess-claude-1")
            await prov.chat([Message(role="user", content="hi")])
            assert captured_headers[-1].get("x-session-id") == "sess-claude-1"
            assert captured_headers[-1].get("user-agent") == "python-httpx/0.28.1"
        finally:
            await prov.close()

    asyncio.run(_run())
