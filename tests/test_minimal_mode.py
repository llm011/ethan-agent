"""精简模式（minimal）的单元测试。

覆盖：
  - mode 解析（minimal / 精简 / 精简模式）
  - build_tool_registry 在 minimal 模式只注册 MINIMAL_TOOLS，且不含记忆/委派工具
  - build_system_prompt 在 minimal 模式剔除记忆/人格/技能/历史摘要，只留 soul+identity
  - _enrich_quote_for_minimal：引用消息时附上 tool 调用列表与产出文件路径（不带文件内容）
"""
from __future__ import annotations

from ethan.interface.routers.helpers import _enrich_quote_for_minimal, _with_quote
from ethan.providers.base import Message, ToolCall


def test_resolve_minimal_mode_and_aliases():
    from ethan.core.modes import DEFAULT_MODE, MINIMAL_TOOLS, MODES, resolve_mode

    m = resolve_mode("minimal")
    assert m.minimal is True
    assert m.label == "精简模式"
    assert resolve_mode("精简").key == "minimal"
    assert resolve_mode("精简模式").key == "minimal"
    assert DEFAULT_MODE.minimal is False
    # MINIMAL_TOOLS 是精简模式的固定工具白名单
    assert "file_read" in MINIMAL_TOOLS and "shell" in MINIMAL_TOOLS
    assert "recall_memory" not in MINIMAL_TOOLS
    assert any(mm.key == "minimal" for mm in MODES)


def test_minimal_tool_registry_only_registers_whitelist():
    from ethan.core.agent_factory import build_tool_registry
    from ethan.core.modes import MINIMAL_TOOLS

    reg = build_tool_registry(mode="minimal")
    names = {t.name for t in reg.all()}
    assert names == set(MINIMAL_TOOLS)
    # 不含记忆 / 委派 / 定时等长尾工具
    for forbidden in ("recall_memory", "memory_write", "deliver_file", "delegate_coding",
                      "schedule_create", "knowledge_search", "browser_page"):
        assert forbidden not in names, f"精简模式不应注册 {forbidden}"

    # 非精简模式不受影响
    reg_full = build_tool_registry(mode="", channel="web")
    names_full = {t.name for t in reg_full.all()}
    assert "recall_memory" in names_full


def test_minimal_system_prompt_is_stripped():
    from ethan.core.system_prompt import build_system_prompt

    msgs = [Message(role="user", content="看下 /tmp/a.txt")]
    sp = build_system_prompt(
        messages=msgs,
        fast=False,
        system_files={
            "soul": "base-soul",
            "identity": "base-id",
            "agent": "AGENT_X",
            "tools": "TOOLS_X",
            "user_profile": "PROFILE_X",
        },
        provider_model="claude-x",
        skills=None,
        procedures=None,
        registry=None,
        channel="web",
        mode="minimal",
        is_owner=True,
        runtime_context="RT_X",
        last_matched_skills_out=[],
    )
    # 保留基础原则 + 身份
    assert "base-soul" in sp and "base-id" in sp
    # 剔除记忆 / 人格 / 技能 / 历史摘要
    for removed in ("PROFILE_X", "AGENT_X", "TOOLS_X", "RT_X",
                    "recall_memory", "<previous_run_summary>", "<relevant_skills>",
                    "<behavioral_guidelines>", "<memory_signal>"):
        assert removed not in sp, f"精简 prompt 不应包含 {removed}"


def test_minimal_quote_enrichment_carries_tool_calls_and_file_paths():
    ref = Message(
        id=42,
        role="assistant",
        content="已生成报告",
        tool_calls=[
            ToolCall(id="c1", name="file_write", arguments={"path": "/tmp/report.md", "intent": "写报告"}),
            ToolCall(id="c2", name="shell", arguments={"command": "ls /tmp/report.md"}),
        ],
        tool_steps=[
            {"tool": "file_write", "args": {"path": "/tmp/report.md"}, "state": "done",
             "result_preview": "ok /tmp/report.md 123B"},
        ],
    )
    cur = Message(role="user", content="把报告删了")

    # 带 message_id：精确定位
    out = _enrich_quote_for_minimal([ref], {"role": "assistant", "content": "已生成报告", "message_id": 42}, cur)
    assert "已生成报告" in out.content
    assert "file_write" in out.content and "shell" in out.content  # tool 调用列表
    assert "/tmp/report.md" in out.content  # 文件路径
    # 不带文件正文内容
    assert "report content body" not in out.content
    # 当前消息追加在末尾
    assert "把报告删了" in out.content

    # 无 message_id：按内容兜底
    out2 = _enrich_quote_for_minimal([ref], {"role": "assistant", "content": "已生成报告"}, cur)
    assert "file_write" in out2.content


def test_minimal_quote_no_ref_falls_back_to_plain_quote():
    cur = Message(role="user", content="你好")
    out = _with_quote(cur, None)
    assert out.content == "你好"
    # 引用找不到对应历史消息时，仍保留引用正文
    out2 = _enrich_quote_for_minimal(
        [], {"role": "assistant", "content": "一段引用"}, Message(role="user", content="继续")
    )
    assert "一段引用" in out2.content and "继续" in out2.content
