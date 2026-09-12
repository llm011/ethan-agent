"""_direct_stream 出错时也要落库。

背景：direct 模式（浏览器插件的翻译/摘要）过去只在 `not saw_error and full`
时才存助手消息。provider 失败时这条会话在库里只剩用户那句（甚至因 save_user
失败而全丢），刷新后整轮对话消失。现在：出错也存，带 interrupted 状态 +
错误原因；连一个字都没产出也存一条 assistant 行。
"""
from __future__ import annotations

import asyncio

from ethan.interface.routers.chat import _direct_stream
from ethan.providers.base import Message, StreamChunk


class _FakeProvider:
    """前两块正常产出，随后抛错，模拟「回复到一半 provider 挂了」。"""

    model = "fake-model"

    def __init__(self, chunks_before_error=2, fail=True):
        self._n = chunks_before_error
        self._fail = fail

    async def stream_chat(self, messages, tools=None, system=None):
        for i in range(self._n):
            yield StreamChunk(content=f"块{i}")
        if self._fail:
            raise RuntimeError("upstream exploded")


class _FakeAgent:
    def __init__(self, provider):
        self._provider = provider


async def _collect(agen):
    out = []
    async for item in agen:
        out.append(item)
    return out


def _drain(agen):
    return asyncio.run(_collect(agen))


def test_direct_stream_saves_partial_output_and_error():
    """出错时：已产出的部分要落库，并带上 interrupted + 错误原因。"""
    agent = _FakeAgent(_FakeProvider(chunks_before_error=2, fail=True))
    saved = {}

    async def save_user():
        saved["user"] = True

    async def save_assistant(text, err=None):
        saved["assistant"] = (text, err)

    _drain(_direct_stream(agent, [Message(role="user", content="翻译这段")],
                          save_user=save_user, save_assistant=save_assistant))

    assert saved.get("user") is True
    assert "assistant" in saved, "出错时也必须落库助手消息"
    text, err = saved["assistant"]
    assert text == "块0块1"
    assert err == "upstream exploded"


def test_direct_stream_saves_error_even_with_no_output():
    """一个字都没产出就报错：仍要落一条带 error 的 assistant 行。"""
    agent = _FakeAgent(_FakeProvider(chunks_before_error=0, fail=True))
    saved = {}

    async def save_user():
        saved["user"] = True

    async def save_assistant(text, err=None):
        saved["assistant"] = (text, err)

    _drain(_direct_stream(agent, [Message(role="user", content="翻译这段")],
                          save_user=save_user, save_assistant=save_assistant))

    assert "assistant" in saved, "零产出也应有可回看的错误行"
    text, err = saved["assistant"]
    assert text == ""
    assert err == "upstream exploded"


def test_direct_stream_success_saves_without_error():
    """成功路径行为不变：存全文、不附带 error。"""
    agent = _FakeAgent(_FakeProvider(chunks_before_error=3, fail=False))
    saved = {}

    async def save_assistant(text, err=None):
        saved["assistant"] = (text, err)

    _drain(_direct_stream(agent, [Message(role="user", content="翻译这段")],
                          save_assistant=save_assistant))

    text, err = saved["assistant"]
    assert text == "块0块1块2"
    assert err is None
