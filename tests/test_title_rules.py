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
    """无 PR/MR 链接（如 /review 分支名）交回模型按 naming.md 处理。"""
    assert _rule_title("/review feature/login") is None
    assert _rule_title("/review") is None
    # 裸域名 / 非 PR 路径都不算命中
    assert _rule_title("普通提问 github.com") is None
    assert _rule_title("看看 https://github.com/foo/bar") is None


def test_rule_title_url_anywhere_without_command_prefix():
    """PR 链接出现在任意位置即命中，不要求 /review 前缀、不要求行首。

    回归：用户实际输入「帮我 review 这个 PR <链接>」没走规则路径，落到 LLM 路径后
    因 URL 被脱敏成 [链接] 而拿不到 owner/repo，模型照抄 naming.md 示例占位符，
    再被 [:20] 截成 "#100 owner/repo code"。
    """
    got = _rule_title("帮我 review 这个 PR https://github.com/llm011/ethan-agent/pull/100")
    assert got == "#100 llm011/ethan-agent code review"
    # 无斜杠前缀
    assert _rule_title("review https://github.com/foo/bar/pull/7") == "#7 foo/bar code review"
    # 链接在句尾
    assert _rule_title("看看 https://github.com/foo/bar/pull/7") == "#7 foo/bar code review"


def test_rule_title_gitlab_url_mid_sentence():
    """GitLab MR 链接出现在中文句子中间也命中，且编号用 ! 前缀。"""
    got = _rule_title("https://gitlab.com/larksuite/cli/-/merge_requests/42 这个改得对吗")
    assert got == "!42 larksuite/cli code review"


def test_rule_title_not_truncated_to_20():
    """规则标题不做 20 字截断（模板天然更长，硬切会切出残句）。"""
    got = _rule_title("/review https://github.com/llm011/ethan-agent/pull/100")
    assert got == "#100 llm011/ethan-agent code review"
    assert len(got) > 20
    assert got.endswith("code review")


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


# --- 占位符泄漏护栏 ---------------------------------------------------------


class _FakeProvider:
    """按固定脚本返回内容的假 provider（不碰网络）。"""

    def __init__(self, outputs: list[str]):
        self._outputs = list(outputs)
        self.calls: list[str] = []

    async def chat(self, messages, system=None, disable_thinking=False):
        self.calls.append(system or "")

        class _Resp:
            content = self._outputs.pop(0) if self._outputs else ""

        return _Resp()


def _patch_title_provider(monkeypatch, provider):
    """把 _generate_smart_title 内部的 create_provider / get_config 换成假的。"""
    from ethan.providers import manager as manager_mod

    class _Defaults:
        model = "fake/model"
        lite_model = ""  # 空 → get_lite_model 按主模型推断

    class _Cfg:
        defaults = _Defaults()

    monkeypatch.setattr(manager_mod, "create_provider", lambda model: provider)
    monkeypatch.setattr("ethan.core.config.get_config", lambda: _Cfg())


def test_generate_title_rejects_leaked_placeholders(monkeypatch):
    """模型照抄 naming.md 示例时要判为失败，不能把占位符当标题存下来。

    回归：曾被 [:20] 截成 "#100 owner/repo code" 并成为真实会话标题。
    """
    from ethan.memory import session as S

    provider = _FakeProvider(["#100 owner/repo code review"] * 3)
    _patch_title_provider(monkeypatch, provider)
    msgs = [Message(role="user", content="帮我 review 这个 PR https://github.com/a/b/pull/1")]
    got = asyncio.run(S._generate_smart_title(msgs))
    assert got is None  # 重试后仍泄漏 → 放弃，不覆盖占位标题


def test_generate_title_rejects_angle_placeholder_but_accepts_retry(monkeypatch):
    """第一次泄漏占位符 → 重试；第二次给出正常标题 → 采用。"""
    from ethan.memory import session as S

    provider = _FakeProvider(["#100 <owner>/<repo> code review", "侧边栏标题不更新"])
    _patch_title_provider(monkeypatch, provider)
    msgs = [Message(role="user", content="帮我看看这个 PR https://github.com/a/b/pull/1")]
    got = asyncio.run(S._generate_smart_title(msgs))
    assert got == "侧边栏标题不更新"


def test_generate_title_accepts_legitimate_angle_brackets(monkeypatch):
    """护栏不能误杀含尖括号的合法技术标题。"""
    from ethan.memory import session as S

    provider = _FakeProvider(["支持 <T> 泛型"])
    _patch_title_provider(monkeypatch, provider)
    msgs = [Message(role="user", content="帮我给这个类加上泛型支持 https://github.com/a/b/pull/1")]
    got = asyncio.run(S._generate_smart_title(msgs))
    assert got == "支持 <T> 泛型"


def test_clean_keeps_pr_url_scrubs_other_links(monkeypatch):
    """端到端确认：喂给模型的文本里 PR 链接原样保留，其余外链变 [链接]。"""
    from ethan.memory import session as S

    captured: dict[str, str] = {}

    class _CapturingProvider(_FakeProvider):
        async def chat(self, messages, system=None, disable_thinking=False):
            captured["prompt"] = messages[0].content
            return await super().chat(messages, system=system, disable_thinking=disable_thinking)

    provider = _CapturingProvider(["正常标题"])
    _patch_title_provider(monkeypatch, provider)
    msgs = [
        Message(
            role="user",
            content="帮我看看 https://github.com/foo/bar/pull/7 并参考 https://example.com/doc",
        )
    ]
    asyncio.run(S._generate_smart_title(msgs))
    assert "https://github.com/foo/bar/pull/7" in captured["prompt"]
    assert "https://example.com/doc" not in captured["prompt"]
    assert "[链接]" in captured["prompt"]


def test_clean_keeps_pr_url_straddling_length_cap(monkeypatch):
    """第 100 字符正好落在 PR 链接中间时，链接仍要完整保留。

    回归：旧写法先 text[:100] 再匹配，半截 URL 匹配不到 _PR_URL_RE 被当普通外链
    脱敏，模型又拿不到 owner/repo。
    """
    from ethan.memory import session as S

    captured: dict[str, str] = {}

    class _CapturingProvider(_FakeProvider):
        async def chat(self, messages, system=None, disable_thinking=False):
            captured["prompt"] = messages[0].content
            return await super().chat(messages, system=system, disable_thinking=disable_thinking)

    provider = _CapturingProvider(["正常标题"])
    _patch_title_provider(monkeypatch, provider)
    msgs = [Message(role="user", content="y" * 70 + " https://github.com/a/b/pull/100")]
    asyncio.run(S._generate_smart_title(msgs))
    assert "https://github.com/a/b/pull/100" in captured["prompt"]


def test_clean_caps_plain_text_without_urls(monkeypatch):
    """没有 URL 的纯文本仍受 100 字预算约束，不能整段灌给模型。"""
    from ethan.memory import session as S

    captured: dict[str, str] = {}

    class _CapturingProvider(_FakeProvider):
        async def chat(self, messages, system=None, disable_thinking=False):
            captured["prompt"] = messages[0].content
            return await super().chat(messages, system=system, disable_thinking=disable_thinking)

    provider = _CapturingProvider(["正常标题"])
    _patch_title_provider(monkeypatch, provider)
    msgs = [Message(role="user", content="x" * 500)]
    asyncio.run(S._generate_smart_title(msgs))
    assert "x" * 100 in captured["prompt"]
    assert "x" * 101 not in captured["prompt"]
