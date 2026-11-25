r"""reasoning_content 回传回归测试（计划条目 4，对应 P3）。

核心契约：带 tools 的 thinking 模式请求，上一轮返回过 reasoning_content，
下一轮必须原样回传在 assistant 消息里，否则上游 400：
  「The reasoning_content in the thinking mode must be passed back to the API」

历史 bug：
  1. 流式 `_pump` 只把 reasoning 转成 ThinkingEvent 往外吐，不累积 → 回填
     assistant Message 丢 reasoning → `_transform` 回传分支空转。
  2. 非流式 `parse_choice` 不读 message.reasoning_content → Message.reasoning 总为 None。
  3. `_wants_reasoning` 只匹配 `deepseek-r1` / `deepseek-reasoner`，新模型
     （如 deepseek-v4.1-flash）匹配不上 → 历史 reasoning 不回传 → 400。

覆盖：
  - `parse_choice` 读取 reasoning_content 挂到 Message；
  - `_history_carries_reasoning`：最近一条 assistant 带 reasoning 即回传，
    切到普通模型后（最近一条无 reasoning）不回传；
  - provider 序列化：模型名不在表里但历史带 reasoning 时，outgoing messages
    仍含 reasoning_content（证据驱动，覆盖 deepseek-v4.1-flash）；
  - 缺回传即 400 的假客户端：修复后第二步工具调用不报 400。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from ethan.core.config import ProviderConfig
from ethan.providers._responses import parse_choice
from ethan.providers.base import Message, ToolDefinition
from ethan.providers.openai_compat import OpenAICompatProvider

_TOOLS = [ToolDefinition(name="x", description="d", parameters={"type": "object", "properties": {}})]


def _cfg():
    return ProviderConfig(api_key="k", base_url="https://relay.test/v1")


# ── parse_choice ──────────────────────────────────────────────────────────


def test_parse_choice_carries_reasoning_content():
    msg = SimpleNamespace(content="答案", tool_calls=[], reasoning_content="我先想想…")
    choice = SimpleNamespace(message=msg)
    m = parse_choice(choice)
    assert m.reasoning == "我先想想…"


def test_parse_choice_no_reasoning_when_absent():
    msg = SimpleNamespace(content="答案", tool_calls=[])
    m = parse_choice(SimpleNamespace(message=msg))
    assert m.reasoning is None


# ── _history_carries_reasoning ────────────────────────────────────────────


class TestHistoryCarriesReasoning:
    def test_recent_assistant_with_reasoning(self):
        msgs = [Message(role="user", content="hi"),
                Message(role="assistant", content="x", reasoning="思考")]
        assert OpenAICompatProvider._history_carries_reasoning(msgs) is True

    def test_no_reasoning(self):
        msgs = [Message(role="user", content="hi"), Message(role="assistant", content="x")]
        assert OpenAICompatProvider._history_carries_reasoning(msgs) is False

    def test_switched_to_plain_model_drops_backprop(self):
        """切到普通模型后，最近一条 assistant 无 reasoning → 不回传，避免污染新端点。"""
        msgs = [Message(role="assistant", content="x", reasoning="旧模型思考"),
                Message(role="assistant", content="普通模型回答")]
        assert OpenAICompatProvider._history_carries_reasoning(msgs) is False

    def test_empty_history(self):
        assert OpenAICompatProvider._history_carries_reasoning([]) is False


# ── provider 序列化：证据驱动回传 ──────────────────────────────────────────


def _fake_provider(model: str):
    """构造一个假客户端 provider，捕获每次 create 的 kwargs。"""
    p = OpenAICompatProvider(_cfg(), model)
    captured: list[dict] = []

    async def _create(**kw):
        captured.append(kw)
        # 返回一个带 reasoning_content 的非流式响应
        msg = SimpleNamespace(content="好的", tool_calls=[], reasoning_content="思考…")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=_create)
    p._client = client
    return p, captured


def test_unlisted_model_backprops_reasoning_via_history():
    """模型名不在 _REASONING_MODEL_PATTERNS（deepseek-v4.1-flash），但历史带 reasoning
    → outgoing messages 必须回传 reasoning_content，否则上游 400。"""
    p, captured = _fake_provider("deepseek-v4.1-flash")
    # 第一轮：历史无 reasoning（预热 captured，模拟模型返回了 reasoning）
    asyncio.run(p.chat([Message(role="user", content="帮我查天气")], tools=[]))
    # 第二轮：历史含上一轮带 reasoning 的 assistant 消息 → 必须回传
    history = [Message(role="user", content="帮我查天气"),
               Message(role="assistant", content="好的", reasoning="思考…")]
    asyncio.run(p.chat(history, tools=_TOOLS))
    outgoing = captured[-1]["messages"]
    asst = next(m for m in outgoing if m["role"] == "assistant")
    assert asst.get("reasoning_content") == "思考…", (
        "deepseek-v4.1-flash 历史带 reasoning 时未回传 reasoning_content，会触发 400"
    )


def test_plain_model_does_not_backprop():
    """普通模型（无 reasoning 历史）不回传 reasoning_content，避免污染端点。"""
    p, captured = _fake_provider("gpt-4o")
    history = [Message(role="user", content="hi"), Message(role="assistant", content="你好")]
    asyncio.run(p.chat(history, tools=[]))
    outgoing = captured[-1]["messages"]
    asst = next(m for m in outgoing if m["role"] == "assistant")
    assert "reasoning_content" not in asst


# DeepSeek thinking 模式缺 reasoning_content 回传的真实报错原文。
DEEPSEEK_400_MSG = (
    "Error code: 400 - {'error': {'message': "
    "'The reasoning_content in the thinking mode must be passed back to the API'}}"
)


def test_missing_backprop_would_400_with_tools():
    """带 tools 的请求：历史含上一轮 reasoning_content，若未回传，假客户端抛
    DeepSeek 400。修复（证据驱动回传）后不报 400。

    对照：把 _history_carries_reasoning 改为恒 False 时，此测试会抛 RuntimeError
    （含 DEEPSEEK_400_MSG），复现线上 bug。
    """
    p = OpenAICompatProvider(_cfg(), "deepseek-v4.1-flash")
    captured: list[list] = []

    async def _create(**kw):
        outgoing = kw["messages"]
        captured.append(outgoing)
        asst = next((m for m in outgoing if m["role"] == "assistant"), None)
        if not asst or not asst.get("reasoning_content"):
            raise RuntimeError(DEEPSEEK_400_MSG)
        msg = SimpleNamespace(content="好的", tool_calls=[], reasoning_content="思考…")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=_create)
    p._client = client

    history = [Message(role="user", content="查天气"),
               Message(role="assistant", content="好的", reasoning="思考…")]
    # 不应抛 400
    resp = asyncio.run(p.chat(history, tools=_TOOLS))
    assert resp.reasoning == "思考…"
    # outgoing 里确实回传了 reasoning_content
    asst = next(m for m in captured[-1] if m["role"] == "assistant")
    assert asst["reasoning_content"] == "思考…"
