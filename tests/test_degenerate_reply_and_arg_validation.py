"""收尾轮退化回复检测 + 工具必填参数预校验。

badcase（会话 s_20260903_1935_42ff）：模型在工具成功后的收尾轮只吐了字面工具名
"recall_memory"，ethan 视为正常非空回复直接结束 turn；同轮 recall_memory 首次调用
漏传 query，run() 抛裸 TypeError。本文件覆盖两处的修复。
"""
from __future__ import annotations

import asyncio
from typing import Any

from ethan.core.agent import _is_degenerate_reply
from ethan.providers.base import ToolCall
from ethan.tools.base import BaseTool
from ethan.tools.registry import ToolExecutor, ToolRegistry

# ---------------------------------------------------------------------------
# _is_degenerate_reply
# ---------------------------------------------------------------------------


def _defs(*names: str):
    from ethan.providers.base import ToolDefinition

    return [ToolDefinition(name=n, description="", parameters={"type": "object", "properties": {}}) for n in names]


class TestDegenerateReply:
    def test_exact_tool_name(self):
        tools = _defs("recall_memory", "shell")
        assert _is_degenerate_reply("recall_memory", tools) is True

    def test_markdown_wrapped(self):
        tools = _defs("recall_memory")
        assert _is_degenerate_reply("**recall_memory**", tools) is True
        assert _is_degenerate_reply("`recall_memory`", tools) is True

    def test_whitespace_padded(self):
        tools = _defs("recall_memory")
        assert _is_degenerate_reply("  recall_memory\n", tools) is True

    def test_normal_text_not_flagged(self):
        tools = _defs("recall_memory")
        assert _is_degenerate_reply("recall_memory 查过了，没有异常记录。", tools) is False
        assert _is_degenerate_reply("好的", tools) is False
        assert _is_degenerate_reply("Done", tools) is False  # 不是工具名

    def test_empty_and_none(self):
        tools = _defs("recall_memory")
        assert _is_degenerate_reply(None, tools) is False
        assert _is_degenerate_reply("", tools) is False
        assert _is_degenerate_reply("   ", tools) is False

    def test_no_tools(self):
        assert _is_degenerate_reply("recall_memory", None) is False
        assert _is_degenerate_reply("recall_memory", []) is False


# ---------------------------------------------------------------------------
# ToolExecutor 必填参数预校验
# ---------------------------------------------------------------------------


class _RecallLikeTool(BaseTool):
    @property
    def name(self) -> str:
        return "recall_memory"

    @property
    def description(self) -> str:
        return "test tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询词"},
                "intent": {"type": "string", "description": "调用意图"},
            },
            "required": ["query"],
        }

    async def run(self, **kwargs) -> str:
        return f"recalled:{kwargs.get('query', '')}"


class TestRequiredArgValidation:
    def _executor(self) -> ToolExecutor:
        registry = ToolRegistry()
        registry.register(_RecallLikeTool())
        return ToolExecutor(registry)

    def test_missing_required_param_returns_friendly_error(self):
        executor = self._executor()
        tc = ToolCall(id="t1", name="recall_memory", arguments={"input": 'query "用户最近的问题"'})
        results = asyncio.run(executor.execute([tc]))
        r = results[0]
        assert r.is_error is True
        assert "query" in r.content
        assert "recall_memory" in r.content
        # 裸 TypeError 不会出现
        assert "positional argument" not in r.content

    def test_valid_args_pass_through(self):
        executor = self._executor()
        tc = ToolCall(id="t1", name="recall_memory", arguments={"query": "最近的异常", "intent": "查异常"})
        results = asyncio.run(executor.execute([tc]))
        r = results[0]
        assert r.is_error is False
        assert r.content == "recalled:最近的异常"

    def test_intent_alone_not_enough(self):
        executor = self._executor()
        tc = ToolCall(id="t1", name="recall_memory", arguments={"intent": "查记忆"})
        results = asyncio.run(executor.execute([tc]))
        assert results[0].is_error is True
        assert "missing required argument(s) query" in results[0].content
