"""端到端：整条 agent loop 跑一遍「文本型 invoke 工具调用」，确认不再停在半路。

线上故障形态：anthropic 格式代理 + deepseek 等非 Claude 模型，function calling
退化成把工具调用当正文下发。修复前这一轮无工具可执行、agent 静默停住。

这里用**真实的 OpenAICompatProvider** + 假 HTTP 流，所以会经过 provider 的缓冲分支
（真正负责不让 XML 漏给用户的地方）——用假 provider 直接吐 content 会绕过它，
测试就失去意义。覆盖三件事：
  1. 工具真的被调用（agent 没有停在半路，循环继续到第 2 轮）；
  2. XML 标记没有漏进用户可见文本；
  3. 参数按 schema 从字符串转成了工具期望的类型（count: "3" → int）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from ethan.core.agent import Agent
from ethan.core.config import ProviderConfig
from ethan.providers.base import Message
from ethan.providers.openai_compat import OpenAICompatProvider
from ethan.tools.base import BaseTool
from ethan.tools.registry import ToolRegistry


class EchoTool(BaseTool):
    name = "echo"
    description = "回显文本"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["text"],
    }

    async def run(self, text: str = "", count: int = 0) -> str:
        return f"echoed: {text} (count={count!r}, type={type(count).__name__})"


ROUND1 = (
    "我来帮你调用工具。\n"
    '<tool_calls>\n'
    '  <invoke name="echo">\n'
    '    <parameter name="text">hello</parameter>\n'
    '    <parameter name="count">3</parameter>\n'
    '  </invoke>\n'
    '</tool_calls>'
)


def _chunk(content="", finish_reason=None):
    delta = SimpleNamespace(content=content or None, tool_calls=None,
                            reasoning_content=None, model_extra={})
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)], usage=None)


def _usage():
    return SimpleNamespace(choices=[], usage=SimpleNamespace(
        prompt_tokens=1, completion_tokens=1, total_tokens=2))


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


def make_provider(responses):
    cfg = ProviderConfig(api_key="k", base_url="https://relay.test/v1")
    p = OpenAICompatProvider(cfg, "fake")
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=lambda **kw: responses.pop(0))
    p._client = client
    return p


def round1_stream():
    # 分片下发标记，模拟 gateway 的 delta 边界
    events = [_chunk(ROUND1[i:i + 11]) for i in range(0, len(ROUND1), 11)]
    events += [_chunk(finish_reason="stop"), _usage()]
    return FakeStream(events)


def round2_stream():
    return FakeStream([_chunk("工具执行完了。"), _chunk(finish_reason="stop"), _usage()])


async def _run_loop(responses):
    """跑一遍真实 agent loop，返回 (用户可见文本, 模型看到的工具结果)。"""
    registry = ToolRegistry()
    registry.register(EchoTool())
    agent = Agent(tool_registry=registry)
    provider = make_provider(responses)
    agent._provider = provider

    seen_tool_msgs: list[str] = []
    orig = provider.stream_chat

    async def spy(messages, tools=None, system=None):
        for m in messages:
            if m.role == "tool":
                seen_tool_msgs.append(m.content)
        async for c in orig(messages, tools=tools, system=system):
            yield c

    provider.stream_chat = spy

    chunks = []
    async for ev in agent.stream_chat([Message(role="user", content="帮我 echo hello")]):
        chunks.append(ev)
    return "".join(c for c in chunks if isinstance(c, str)), seen_tool_msgs


def test_agent_continues_after_text_invoke_toolcall():
    """核心回归：识别出文本型工具调用 → 执行工具 → 继续下一轮，不停在半路。"""
    text, tool_msgs = asyncio.run(_run_loop([round1_stream(), round2_stream()]))

    assert any("echoed" in m for m in tool_msgs), "工具未被调用（agent 停在半路了）"
    assert "工具执行完了" in text, "工具执行后循环没有继续到第 2 轮"


def test_markup_not_leaked_to_user():
    """序列化的工具调用不能当正文漏给用户。"""
    text, _ = asyncio.run(_run_loop([round1_stream(), round2_stream()]))

    assert "invoke" not in text
    assert "parameter" not in text
    assert "tool_calls" not in text
    # 标记之前的真正文要保留
    assert "我来帮你调用工具。" in text


def test_string_args_coerced_by_schema():
    """XML 只带字符串，count="3" 要按 schema 变成 int 才能喂给工具。"""
    _, tool_msgs = asyncio.run(_run_loop([round1_stream(), round2_stream()]))

    assert any("count=3, type=int" in m for m in tool_msgs), tool_msgs
