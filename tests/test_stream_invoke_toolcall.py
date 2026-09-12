"""流式端到端回归：网关把工具调用当正文分片下发时，ethan 应解析成 ToolCall 且不漏 XML。

复现线上问题（anthropic 格式代理 + deepseek 等非 Claude 模型）：function calling
退化成正文文本，模型开始吐

    <tool_calls>
      <invoke name="browser_page">
        <parameter name="action">mouse</parameter>
        <parameter name="x">608</parameter>

然后 agent 就停在半路不再运行。两个原因：
  1. 解析器不认这种（无 DSML 前缀的）形状 → 这一轮没有工具可执行；
  2. 标记是**分片**到达的，中途已闭合/未闭合的块若走了普通文本分支，
     半截 XML 会被当正文 yield 给用户。
本测试锁死：分片下也要缓冲到 finish，最终解析出工具调用、正文只剩真 prose。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx

from ethan.core.config import ProviderConfig
from ethan.providers.base import Message
from ethan.providers.openai_compat import OpenAICompatProvider

# 模拟中转提前关连接（与 test_midstream_break.py 同一形态）
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
    def __init__(self, events):
        self._events = list(events)

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
        pass


def _usage_chunk():
    """独立的 usage 收尾 chunk（真实流带 stream_options.include_usage 时必然出现），
    choices 为空 —— stream_chat 在此处才发真正 is_final 的 StreamChunk。"""
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


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


MARKUP = (
    '<tool_calls>\n'
    '  <invoke name="browser_page">\n'
    '    <parameter name="action">mouse</parameter>\n'
    '    <parameter name="x">608</parameter>\n'
    '    <parameter name="y">412</parameter>\n'
    '  </invoke>\n'
    '</tool_calls>'
)


class TestStreamInvokeToolCall:
    def test_split_markup_parsed_at_finish(self):
        """标记被切成多片下发：中途不得漏 XML，finish 时解析出工具调用。"""
        # 按字符切成不规则分片，模拟真实的 delta 边界
        pieces = [MARKUP[i:i + 17] for i in range(0, len(MARKUP), 17)]
        events = [_chunk(p) for p in pieces]
        events.append(_chunk(finish_reason="stop"))
        events.append(_usage_chunk())
        p = _make_provider([FakeStream(events)])
        out = _collect(p)

        visible = "".join(c.content for c in out if c.content)
        assert "invoke" not in visible
        assert "parameter" not in visible
        assert "tool_calls" not in visible

        finals = [c for c in out if c.is_final]
        assert finals, "finish 时必须给出 final chunk"
        calls = finals[-1].tool_calls
        assert len(calls) == 1
        assert calls[0].name == "browser_page"
        # 参数一律字符串（XML 不带类型），类型转换交给 tool registry
        assert calls[0].arguments == {"action": "mouse", "x": "608", "y": "412"}

    def test_prose_kept_markup_stripped(self):
        """模型先写一句话再跟标记：正文要保留那句话，标记要剥掉。"""
        events = [
            _chunk("我来帮你操作浏览器。\n"),
            _chunk(MARKUP),
            _chunk(finish_reason="stop"),
            _usage_chunk(),
        ]
        p = _make_provider([FakeStream(events)])
        out = _collect(p)

        visible = "".join(c.content for c in out if c.content)
        assert visible.strip() == "我来帮你操作浏览器。"
        assert "invoke" not in visible

        calls = [c for c in out if c.is_final][-1].tool_calls
        assert [c.name for c in calls] == ["browser_page"]

    def test_truncated_stream_does_not_leak_markup(self, monkeypatch):
        """流中途断连（闭合标签永远没到）：salvage flush 的半截标记也不能漏给用户。

        这是真实故障形态——网关吐到一半 <invoke> 就断连，走的是 salvage 分支
        （_salvaged=True），而不是正常的 finish 分支。
        """
        async def _no_sleep(_t):
            pass

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)
        partial = '<tool_calls>\n  <invoke name="browser_page">\n    <parameter name="action">mouse'
        events = [_chunk("先看下\n"), _chunk(partial), BREAK_ERR]
        p = _make_provider([FakeStream(events)])
        out = _collect(p)

        visible = "".join(c.content for c in out if c.content)
        assert "invoke" not in visible
        assert "parameter" not in visible
        assert visible.strip() == "先看下"
        assert [c for c in out if c.is_final][-1].truncated is True

    def test_plain_text_unaffected(self):
        """普通文本回复行为不变：原样流出，不产生 tool_calls。"""
        events = [_chunk("你好"), _chunk("，有什么可以帮你？"), _chunk(finish_reason="stop"), _usage_chunk()]
        p = _make_provider([FakeStream(events)])
        out = _collect(p)

        assert "".join(c.content for c in out if c.content) == "你好，有什么可以帮你？"
        assert not [c for c in out if c.is_final][-1].tool_calls

    def test_prose_mentioning_invoke_is_not_eaten(self):
        """模型讲解 <invoke> 用法时，正文不能被当工具调用剥掉。

        回归：`contains_invoke` 若退化成 `"<invoke" in content` 的子串判断，
        剥除兜底正则会从该点截到字符串末尾，把后半段讲解整段吃掉。
        """
        prose = '你需要使用 <invoke name="x"> 标签来调用工具，它就会执行。'
        events = [_chunk(prose), _chunk(finish_reason="stop"), _usage_chunk()]
        p = _make_provider([FakeStream(events)])
        out = _collect(p)

        visible = "".join(c.content for c in out if c.content)
        assert visible == prose, f"讲解性正文被吃掉：{visible!r}"
        assert not [c for c in out if c.is_final][-1].tool_calls

    def test_mixed_markup_parses_and_strips_both(self):
        """同一段 content 混排 <tool_call>{json} 与 <invoke> 时，两者都要解析并剥离。

        回归：finish 分支原是互斥 if/elif 链，marked 命中后 invoke 块既不解析也不剥离
        ——工具静默丢失、XML 原样漏给用户，且 tool_calls 非空让 agent 兜底被跳过。
        """
        mixed = (
            '正文A。<tool_call>{"name":"shell","arguments":{"command":"ls"}}</tool_call>'
            '中间。<tool_calls><invoke name="browser_page">'
            '<parameter name="action">mouse</parameter></invoke></tool_calls>尾部。'
        )
        events = [_chunk(mixed), _chunk(finish_reason="stop"), _usage_chunk()]
        p = _make_provider([FakeStream(events)])
        out = _collect(p)

        visible = "".join(c.content for c in out if c.content)
        assert "<invoke" not in visible, f"invoke XML 漏给用户：{visible!r}"
        assert "<tool_call>" not in visible, f"marked XML 漏给用户：{visible!r}"
        assert visible == "正文A。中间。尾部。", visible

        calls = [c for c in out if c.is_final][-1].tool_calls
        names = sorted(tc.name for tc in calls)
        assert names == ["browser_page", "shell"], f"混排时漏解析工具：{names}"
