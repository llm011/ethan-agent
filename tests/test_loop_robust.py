r"""循环健壮性：按状态补偿 + 已输出去重（计划条目 5，对应 P4）。

覆盖：
  - tool_error_hint：单次工具失败的轻量提醒文案（非空、含失败原因引导）；
  - agent 主循环：单次 had_error（未到 is_stuck）时下一轮 system 带上失败提醒，
    连续失败触发 is_stuck 时由 reflection 接管（不重复注入弱提示）；
  - StreamCollector 去重：与最近窗口内完全相同的短过渡语不再累积/展示，
    长文本 / 不同短文本不受影响。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ethan.core import agent as agent_mod
from ethan.core.agent import Agent
from ethan.core.config import ProviderConfig
from ethan.core.loop_control import tool_error_hint
from ethan.core.stream_collector import StreamCollector
from ethan.providers.base import Message, ToolCall
from ethan.providers.openai_compat import OpenAICompatProvider
from ethan.tools.base import ToolResult
from ethan.tools.registry import ToolRegistry

# ── tool_error_hint 文案 ──────────────────────────────────────────────────


class TestToolErrorHint:
    def test_non_empty_and_guides_root_cause(self):
        txt = tool_error_hint("FileNotFoundError: /tmp/x", "file_read")
        assert txt
        assert "失败原因" in txt or "原因" in txt
        assert "file_read" in txt

    def test_no_tool_name(self):
        txt = tool_error_hint("boom")
        assert "boom" in txt  # 错误节选带上了

    def test_long_result_truncated(self):
        txt = tool_error_hint("x" * 1000)
        assert len(txt) < 1300  # 节选限 200 字 + 固定文案


# ── StreamCollector 去重 ──────────────────────────────────────────────────


class TestCollectorDedup:
    def test_duplicate_short_transition_suppressed(self):
        """工具失败后模型重说同一句过渡语：第二遍不再累积到 full，也不返回展示。"""
        c = StreamCollector()
        first = c.feed("好的，我来检查一下文件。")
        assert first == "好的，我来检查一下文件。"
        # 模拟一段工具执行后又吐同一句
        second = c.feed("好的，我来检查一下文件。")
        assert second is None, "完全相同的短过渡语应被去重，不返回展示"
        assert c.full == "好的，我来检查一下文件。", "full 不应包含重复块"

    def test_different_short_text_not_suppressed(self):
        c = StreamCollector()
        a = c.feed("我先读文件。")
        b = c.feed("然后改配置。")
        assert a and b
        assert c.full == "我先读文件。然后改配置。"

    def test_long_text_not_deduplicated(self):
        """长正文（> 阈值）即使内容相同也不去重——避免误删合法的重复段落。"""
        c = StreamCollector()
        long = "y" * 500
        assert c.feed(long) == long
        assert c.feed(long) == long  # 长文本不碰
        assert c.full.count("y") == 1000

    def test_whitespace_variants_treated_same(self):
        """strip 后相同即视为重复（前后空白不影响去重判定），但保留首份原文本。"""
        c = StreamCollector()
        c.feed("  好的  \n")
        assert c.feed("好的") is None
        assert c.full == "  好的  \n"  # 保留首份原始文本

    def test_window_evicts_old_entries(self):
        """超过窗口大小的旧块不再阻止其重现（窗口=5：喂 6 个不同块后 unique_0 被挤出）。"""
        c = StreamCollector()
        for i in range(6):
            c.feed(f"unique_{i}")
        # 窗口保留最后 5 个（unique_1..unique_5），unique_0 已被挤出；再喂应放行
        out = c.feed("unique_0")
        assert out == "unique_0", "窗口外的旧块重现应放行"


# ── agent 主循环：单次失败注入提醒 ────────────────────────────────────────


@pytest.fixture()
def _isolated_data_dir(monkeypatch, tmp_path):
    """隔离 ETHAN_DATA_DIR，避免 ~/.ethan 真实数据膨胀 system prompt。"""
    import ethan.core.config as cfg_mod
    import ethan.core.paths as paths_mod

    data_dir = tmp_path / "ethan-data"
    monkeypatch.setenv("ETHAN_DATA_DIR", str(data_dir))
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", data_dir, raising=False)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", data_dir / "config.yaml", raising=False)
    monkeypatch.setattr(paths_mod, "CONFIG_DIR", data_dir, raising=False)
    monkeypatch.setattr(paths_mod, "_PROFILES_MIGRATE_MARKER", data_dir / ".profiles_migrated", raising=False)
    monkeypatch.setattr(cfg_mod, "_config", None, raising=False)
    yield
    monkeypatch.setattr(cfg_mod, "_config", None, raising=False)


def test_single_tool_error_injects_hint_next_round(monkeypatch, _isolated_data_dir):
    """单次工具失败（未到 is_stuck）→ 下一轮 system 带上 tool_error_hint 文案。"""
    cfg = ProviderConfig(api_key="k", base_url="https://relay.test/v1")
    provider = OpenAICompatProvider(cfg, "fake")
    captured_systems: list[str] = []

    async def _chat(messages, tools=None, system=None, **kw):
        captured_systems.append(system or "")
        if len(captured_systems) == 1:
            # 第一轮：调一个工具
            return Message(
                role="assistant", content="",
                tool_calls=[ToolCall(id="c1", name="shell", arguments={"cmd": "ls /bad"})],
            )
        # 第二轮（失败后）：直接收尾
        return Message(role="assistant", content="那个路径不存在。")

    provider.chat = AsyncMock(side_effect=_chat)

    agent = Agent(tool_registry=ToolRegistry())
    agent._provider = provider
    agent._provider_for_route = lambda route: provider
    agent.is_owner = True
    monkeypatch.setattr(agent_mod, "effective_input_budget", lambda: 10_000_000)

    # executor 返回错误
    agent._executor = MagicMock()
    agent._executor.reset_cache = MagicMock()
    agent._executor.execute = AsyncMock(return_value=[
        ToolResult(tool_call_id="c1", content="ls: /bad: No such file or directory", is_error=True),
    ])

    asyncio.run(agent.chat([Message(role="user", content="列出 /bad")]))

    assert len(captured_systems) >= 2, "应至少发了两轮请求"
    # 第一轮 system 不含失败提醒，第二轮（失败后）应含
    assert "失败原因" not in captured_systems[0] or "上一步工具调用" not in captured_systems[0]
    assert any("上一步工具调用" in s for s in captured_systems[1:]), (
        "单次工具失败后下一轮 system 未注入失败提醒"
    )
