"""命名规则 `_rule_title` 与 naming.md 注入的单元测试。

背景：新对话命名此前无规则，/review 会话标题格式不统一（`PR #70 owner/repo`
且不含 code review）。现在规则外置到 ~/.ethan/system/naming.md，并把确定性的
URL 解析短路进 `_rule_title`，零 LLM 成本即时命名。

同时覆盖及时性修复：已成功命名的标题不再被反复改动，占位标题则允许继续补生成。
"""

import asyncio

from ethan.memory.session import (
    _auto_title,
    _build_title_system_prompt,
    _is_placeholder_title,
    _rule_title,
)
from ethan.providers.base import Message


def test_rule_title_github_pr():
    got = _rule_title("/review https://github.com/llm011/ethan-agent/pull/100")
    assert got == "#100 llm011/ethan-agent code review"


def test_rule_title_gitlab_mr():
    got = _rule_title("/review https://gitlab.com/larksuite/cli/-/merge_requests/42")
    assert got == "!42 larksuite/cli code review"


def test_rule_title_url_embedded_in_text():
    """URL 不一定要在行首，命令后带说明文字也应命中。"""
    got = _rule_title("/review 帮我看看 https://github.com/foo/bar/pull/7 这个改动")
    assert got == "#7 foo/bar code review"


def test_rule_title_no_url_returns_none():
    """无链接（如 /review 分支名）交回模型按 naming.md 处理。"""
    assert _rule_title("/review feature/login") is None
    assert _rule_title("/review") is None
    assert _rule_title("普通提问 github.com") is None


def test_rule_title_only_for_review_command():
    """非 /review 命令即使带 PR 链接也不短路（避免误吞普通对话）。"""
    assert _rule_title("看看 https://github.com/foo/bar/pull/7") is None


def test_is_placeholder_title():
    msgs = [Message(role="user", content="帮我看看这个 PR 的改动")]
    auto = _auto_title(msgs)
    assert _is_placeholder_title("", msgs) is True
    assert _is_placeholder_title("新对话", msgs) is True
    assert _is_placeholder_title(auto, msgs) is True
    # 已成功命名的标题不算占位
    assert _is_placeholder_title("#100 foo/bar code review", msgs) is False


def test_build_title_system_prompt_includes_rules(monkeypatch):
    monkeypatch.setattr(
        "ethan.memory.session._load_naming_rules",
        lambda: "## 规则\nreview PR → #N owner/repo code review",
    )
    prompt = _build_title_system_prompt()
    assert "命名规则（必须遵守）" in prompt
    assert "#N owner/repo code review" in prompt


def test_build_title_system_prompt_without_rules(monkeypatch):
    """没有 naming.md 时退化到基础 prompt，不报错。"""
    monkeypatch.setattr("ethan.memory.session._load_naming_rules", lambda: "")
    prompt = _build_title_system_prompt()
    assert "命名规则" not in prompt
    assert "标题生成助手" in prompt


def test_decide_title_rule_shortcircuit(monkeypatch):
    """首轮 /review 链接：直接返回规则标题，不调用模型。"""
    from ethan.memory import session as S

    async def _boom(*a, **k):
        raise AssertionError("命中规则时不应调用智能标题模型")

    monkeypatch.setattr(S, "_generate_smart_title", _boom)
    msgs = [Message(role="user", content="/review https://github.com/llm011/ethan-agent/pull/100")]
    title = asyncio.run(S.decide_title(msgs, current_title="新对话"))
    assert title == "#100 llm011/ethan-agent code review"


def test_decide_title_retries_placeholder_past_round2(monkeypatch):
    """及时性修复：第 3 轮仍是占位标题时继续补生成，而不是永久卡住。"""
    from ethan.memory import session as S

    calls = {"n": 0}

    async def _fake(*a, **k):
        calls["n"] += 1
        return "补生成的成功标题"

    monkeypatch.setattr(S, "_generate_smart_title", _fake)
    msgs = [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好，有什么可以帮你？"),
        Message(role="user", content="再问个事"),
        Message(role="assistant", content="请讲"),
        Message(role="user", content="第三轮了"),
    ]
    # 当前仍是占位（首条太短 → _auto_title = "你好"）
    cur = _auto_title(msgs)
    title = asyncio.run(S.decide_title(msgs, current_title=cur))
    assert title == "补生成的成功标题"
    assert calls["n"] == 1


def test_decide_title_keeps_good_title_past_round2(monkeypatch):
    """已有成功标题后，第 3 轮起不再自动改动（避免标题突然变）。"""
    from ethan.memory import session as S

    async def _boom(*a, **k):
        raise AssertionError("已有好标题不应再调用模型")

    monkeypatch.setattr(S, "_generate_smart_title", _boom)
    msgs = [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好"),
        Message(role="user", content="x"),
        Message(role="assistant", content="y"),
        Message(role="user", content="z"),
    ]
    title = asyncio.run(S.decide_title(msgs, current_title="侧边栏标题不更新"))
    assert title is None


def test_decide_title_respects_protected_prefix():
    from ethan.memory import session as S

    msgs = [Message(role="user", content="/review https://github.com/a/b/pull/1")]
    assert asyncio.run(S.decide_title(msgs, current_title="[定时] 每日摘要")) is None
