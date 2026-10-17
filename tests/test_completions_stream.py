# -*- coding: utf-8 -*-
"""`/v1/chat/completions` 的流式分支端到端（假 agent 驱动）。

回归点：`_stream_completions` 里曾经有一条指向 `routers.chat` 的过期延迟导入，
它在生成器第一行就抛 ImportError。此时响应头（200 + text/event-stream）已经发出，
body 一个字节都没有——客户端看到的就是「流式返回 200 和 SSE 头，但 body 一直是空的」。
这个测试把整条生成器跑到底，任何中途异常都会让它失败。
"""
from __future__ import annotations

import json

import pytest

from ethan.interface.routers import completions as completions_mod


class _Usage:
    input_tokens = 3
    output_tokens = 2
    cache_tokens = 0


class _Provider:
    model = "fake-model"


class _Agent:
    """够用的假 agent：产出两段文本 + 一个被过滤掉的 ThinkingEvent。"""

    def __init__(self, chunks):
        self._chunks = chunks
        self._provider = _Provider()
        self.usage = _Usage()

    async def stream_chat(self, messages):
        for c in self._chunks:
            yield c


class _Store:
    def __init__(self):
        self.saved = []
        self.updated = []

    async def save_message(self, session_id, msg):
        self.saved.append(msg)
        return len(self.saved)

    async def update_message(self, msg_id, session_id, msg):
        self.updated.append((msg_id, msg))
        return True

    async def touch(self, session_id):
        return None


def _data_events(chunks) -> list[dict | str]:
    out = []
    for line in chunks:
        assert line.startswith("data: "), line
        payload = line[len("data: "):].strip()
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


@pytest.mark.anyio
async def test_stream_completions_yields_text_and_finishes(monkeypatch):
    """正常走完：有内容分片、有 finish_reason、有 [DONE]，且回复已落库。"""
    from ethan.providers.base import ThinkingEvent

    async def _noop(*a, **k):
        return None

    # 任务类副作用全部短路，避免测试碰真实记忆库
    monkeypatch.setattr(completions_mod, "_maybe_regen_title", _noop)
    monkeypatch.setattr(completions_mod, "_maybe_consolidate", _noop)
    monkeypatch.setattr(completions_mod, "_maybe_generate_skill", _noop)

    agent = _Agent(["你好", ThinkingEvent(delta="思考中"), "，世界"])
    store = _Store()

    chunks = [
        c async for c in completions_mod._stream_completions(
            agent, [{"role": "user", "content": "hi"}], store, "s_test_1234", "fake-model"
        )
    ]

    events = _data_events(chunks)
    assert events[-1] == "[DONE]"
    text = "".join(
        e["choices"][0]["delta"].get("content", "")
        for e in events
        if isinstance(e, dict)
    )
    assert text == "你好，世界"
    # 思考过程不暴露给客户端
    assert "思考中" not in text
    assert any(
        e.get("choices", [{}])[0].get("finish_reason") == "stop"
        for e in events
        if isinstance(e, dict)
    )
    assert store.saved and store.saved[0].content == "你好，世界"


@pytest.mark.anyio
async def test_stream_completions_passes_mode_to_consolidate(monkeypatch):
    """mode 必须透传给 _maybe_consolidate，否则精简模式会被当成默认模式抽取记忆。"""
    seen = {}

    async def _noop(*a, **k):
        return None

    async def _capture(session_id, model, user_id="", mode=""):
        seen["mode"] = mode

    monkeypatch.setattr(completions_mod, "_maybe_regen_title", _noop)
    monkeypatch.setattr(completions_mod, "_maybe_consolidate", _capture)
    monkeypatch.setattr(completions_mod, "_maybe_generate_skill", _noop)

    store = _Store()
    _ = [
        c async for c in completions_mod._stream_completions(
            _Agent(["hi"]), [], store, "s_test_1234", "fake-model", "u1", "minimal"
        )
    ]
    import asyncio

    await asyncio.sleep(0)  # 让 create_task 跑起来
    assert seen.get("mode") == "minimal"


@pytest.mark.anyio
async def test_stream_completions_reports_error_in_band(monkeypatch):
    """agent 中途抛错时：已产出内容保留，错误以 data 事件下发，不静默空 body。"""

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(completions_mod, "_maybe_regen_title", _noop)
    monkeypatch.setattr(completions_mod, "_maybe_consolidate", _noop)
    monkeypatch.setattr(completions_mod, "_maybe_generate_skill", _noop)

    class _Boom(_Agent):
        async def stream_chat(self, messages):
            yield "前半段"
            raise RuntimeError("provider exploded")

    store = _Store()
    chunks = [
        c async for c in completions_mod._stream_completions(
            _Boom([]), [], store, "s_test_1234", "fake-model"
        )
    ]
    events = _data_events(chunks)
    assert any(isinstance(e, dict) and "error" in e for e in events), events
    assert store.saved, "错误回复也应落库"
