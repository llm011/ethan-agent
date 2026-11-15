r"""外部内核的「简报表」注入测试（`ethan/kernel/briefing.py`）。

## 为什么要这份测试

用户报的现象：切到 DSH 后，之前让 Ethan 记住的东西它不会主动用。

根因不是工具没共享（`/kernel-tools` 连 `recall_memory` 都给过去了），而是
`a8923c15` 把记忆召回改成了「模型按需调 recall_memory」，替代自动注入的正是
系统提示词里的 `<memory_recall_hint>` —— 而外部内核走的是自己的系统提示词，
一个字都收不到。技能同理（`<available_skills>` 缺失 → 手上有 skill_list
却不知道自己有什么）。

所以这里锁三件事：

1. 共享了 Ethan 工具的内核，prompt 里必须带技能索引 + 记忆召回/写入提示
2. 没共享工具的内核（Codex/OpenCode/Pi）**不能**带 —— 不能教模型调它没有的工具
3. `_build_prompt` 的语义不变（只压历史），简报由 `_compose_prompt` 拼
"""
from __future__ import annotations

import pytest

from ethan.kernel.briefing import build_kernel_briefing, clear_briefing_cache
from ethan.kernel.runtime import KernelRequest
from ethan.providers.base import Message


@pytest.fixture(autouse=True)
def _fresh_cache():
    """简报按 (mode, 技能目录 mtime) 缓存，用例之间必须隔离。"""
    clear_briefing_cache()
    yield
    clear_briefing_cache()


@pytest.fixture
def fake_skills(monkeypatch):
    """种一批受控技能，不依赖跑测试这台机器上装了什么。

    conftest 把 CONFIG_DIR 隔离到 tmp，技能目录天然是空的；直接断言
    `<available_skills>` 存在会变成「看运气」的测试。
    """
    from ethan.skills.loader import Skill

    def _skill(name, desc="", trigger=None, fast_path=False, category="default", modes=None):
        return Skill(
            name=name,
            description=desc,
            trigger=trigger or [],
            content="",
            source=__import__("pathlib").Path("/tmp") / name,
            fast_path=fast_path,
            category=category,
            modes=modes or [],
        )

    skills = [
        _skill("hot-skill", "热门技能，命中率高", fast_path=True),
        _skill("cold-skill", "冷门技能"),
        _skill("disc-skill", "按需技能", trigger=["触发甲", "触发乙"], category="discoverable"),
        _skill("legal-assistant", "法律专家", fast_path=True, modes=["法律"]),
    ]

    import ethan.kernel.briefing as mod

    monkeypatch.setattr(mod, "_skills_dir_signature", lambda: "fixed-for-test")
    monkeypatch.setattr(mod, "_visible_skills", lambda mode: mod_filter(skills, mode))
    return skills


def mod_filter(skills, mode):
    """与 `_visible_skills` 相同的模式过滤口径（测试里独立实现一遍，避免自证）。"""
    if mode == "法律":
        return skills
    return [s for s in skills if not s.modes]


# ── 简报内容 ─────────────────────────────────────────────────


def test_briefing_carries_skills_and_memory_hints(fake_skills):
    text = build_kernel_briefing(mode="")

    assert "<available_skills>" in text, "技能索引缺失 → DSH 不知道自己有什么技能"
    assert "hot-skill" in text
    assert "<memory_recall_hint>" in text, "缺召回提示 → 记忆等于被撤掉了自动注入"
    assert "<memory_write_hint>" in text
    # 工具都带 ethan_ 前缀（见 tool_bridge），提示里的名字必须跟着带，
    # 否则模型会去调一个 MCP 上不存在的 "recall_memory"
    assert "ethan_recall_memory" in text
    assert "ethan_memory_write" in text


def test_briefing_does_not_inject_persona(fake_skills):
    """人格/画像仍然不注入 —— `ethan_context=False` 的取舍不变。

    塞进去会和外部 agent 自己的系统提示词打架（两份人格谁优先），
    这是本模块刻意不碰的部分。
    """
    text = build_kernel_briefing(mode="")
    for forbidden in ("<soul>", "<identity>", "<user_profile>", "<behavioral_guidelines>"):
        assert forbidden not in text


def test_briefing_empty_when_tools_not_shared(fake_skills):
    """Codex / OpenCode / Pi 拿不到 Ethan 工具，教它调只会让它失败一轮再绕路。"""
    assert build_kernel_briefing(mode="", shares_tools=False) == ""


def test_briefing_empty_when_share_tools_off(fake_skills):
    """`share_tools=off` 时 `_build_mcp_servers()` 返回空列表，一个工具都没挂。

    这时再发简报就是让模型去调不存在的东西 —— 与 shares_tools=False 同一条原则。
    只有 shares_ethan_tools 一个门控会漏掉这种情况（review 时发现的）。
    """
    from ethan.core.config import get_config
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    old = get_config().defaults.kernel.share_tools
    get_config().defaults.kernel.share_tools = "off"
    try:
        clear_briefing_cache()
        assert build_kernel_briefing(mode="", share="off") == ""
        k = DshAcpKernel()
        # 内核能力仍是「能共享」，但配置把它关了 → 简报必须跟着消失
        assert k.capabilities.shares_ethan_tools is True
        assert k._build_mcp_servers() == [], "前提：off 下确实没注入任何 MCP server"
        prompt = k._compose_prompt(
            KernelRequest(messages=[Message(role="user", content="hi")])
        )
        assert not prompt.startswith("<ethan_briefing>")
    finally:
        get_config().defaults.kernel.share_tools = old
        clear_briefing_cache()


def test_readonly_mode_skips_write_hint(fake_skills):
    """readonly 白名单里没有 `memory_write`，所以不能发 write hint。

    `recall_memory` / `skill_list` / `skill_read` 在 readonly 下都有，照发。
    """
    from ethan.kernel.tool_bridge import build_mcp_tools

    readonly_tools = {t.name for t in build_mcp_tools(share="readonly")}
    assert "memory_write" not in readonly_tools, "前提变了：readonly 现在含 memory_write"
    assert "recall_memory" in readonly_tools

    text = build_kernel_briefing(mode="", share="readonly")
    assert "<memory_recall_hint>" in text
    assert "<memory_write_hint>" not in text, "readonly 下教模型调 memory_write 会失败一轮"


def test_all_mode_ships_write_hint(fake_skills):
    text = build_kernel_briefing(mode="", share="all")
    assert "<memory_write_hint>" in text


def test_briefing_cache_does_not_leak_across_users(monkeypatch):
    """缓存 key 必须含 user_id —— 技能目录是 per-profile 的。

    review 时发现的原实现只有 (mode, mtime)：两个 profile 的技能目录都不存在时
    指纹都是 "missing"，后一个用户会直接吃到前一个用户的技能简表。

    **不要在两次渲染之间 clear_briefing_cache()** —— 那样永远命中不了缓存，
    测的就变成「两次独立构造」，原 bug 照样绿。这里刻意留着缓存不丢。
    """
    import ethan.core.context as ctx
    import ethan.kernel.briefing as mod

    # 两个 profile 的指纹刻意相同（都不存在的目录就是这种情形）
    monkeypatch.setattr(mod, "_skills_dir_signature", lambda: "missing")
    monkeypatch.setattr(
        mod,
        "_build_skills_block",
        lambda names: "<available_skills>\n- " + " | ".join(names) + "\n</available_skills>",
    )

    current: dict = {"skills": []}
    monkeypatch.setattr(mod, "_visible_skills", lambda mode: list(current["skills"]))

    clear_briefing_cache()

    ctx.set_user_id("alice")
    current["skills"] = ["alice-only-skill"]
    alice = mod.build_kernel_briefing(mode="")

    ctx.set_user_id("bob")  # 不清缓存，让 bob 去读 alice 写下的条目
    current["skills"] = ["bob-only-skill"]
    bob = mod.build_kernel_briefing(mode="")

    ctx.set_user_id("")
    assert "alice-only-skill" in alice
    assert "bob-only-skill" in bob, "bob 读到了 alice 的缓存（串用户）"
    assert "alice-only-skill" not in bob, "缓存串用户了：bob 拿到了 alice 的技能简表"


def test_briefing_hides_mode_specific_skills(fake_skills):
    """模式专属技能（legal-assistant）不进普通模式的简报。

    这是「法律技能零污染」的硬保证，外部内核不能破例。
    """
    assert "legal-assistant" not in build_kernel_briefing(mode="")
    clear_briefing_cache()
    assert "legal-assistant" in build_kernel_briefing(mode="法律")


def test_briefing_is_cached(fake_skills):
    """同一 (mode, 技能目录) 下重复构造应命中缓存 —— 每条消息重建一遍太浪费。"""
    a = build_kernel_briefing(mode="")
    b = build_kernel_briefing(mode="")
    assert a is b, "相同输入应返回缓存对象本身"


def test_briefing_degrades_without_skills(monkeypatch):
    """技能索引构建失败时仍给记忆提示：两者互相独立，不能一起沉掉。"""
    import ethan.kernel.briefing as mod

    monkeypatch.setattr(mod, "_skills_dir_signature", lambda: "fixed-for-test")
    monkeypatch.setattr(
        mod, "_visible_skills", lambda mode: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    text = mod.build_kernel_briefing(mode="")
    assert "<memory_recall_hint>" in text
    assert "<available_skills>" not in text


# ── 内核侧接线 ───────────────────────────────────────────────


def test_dsh_prompt_prepends_briefing(fake_skills):
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    k = DshAcpKernel()
    req = KernelRequest(messages=[Message(role="user", content="你还记得我住哪吗")])
    prompt = k._compose_prompt(req)

    assert prompt.startswith("<ethan_briefing>")
    assert "你还记得我住哪吗" in prompt
    assert "<memory_recall_hint>" in prompt


def test_build_prompt_stays_history_only():
    """`_build_prompt` 保持纯粹语义：测试和其它调用方都依赖它只压历史。"""
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    k = DshAcpKernel()
    req = KernelRequest(messages=[Message(role="user", content="修个 bug")])
    assert k._build_prompt(req) == "修个 bug"
    assert "<ethan_briefing>" not in k._build_prompt(req)


def test_pi_prompt_has_no_briefing():
    """Pi 没有 MCP 支持，不能拿到「你有 xx 工具」的简报。"""
    from ethan.kernel.pi_kernel import PiKernel

    k = PiKernel()
    req = KernelRequest(messages=[Message(role="user", content="hi")])
    assert k._compose_prompt(req) == "hi"


def test_briefing_gate_follows_shares_ethan_tools(fake_skills):
    """简报只跟 `shares_ethan_tools` 走，与 `ethan_context` 无关。

    这张表是本次改动的核心断言：能共享工具的必须拿到简报，不能共享的必须拿不到。
    新增内核时若忘了声明 `shares_ethan_tools`，这里会立刻暴露。

    别把它写成「外部内核一律 False」——#464 之后 OpenCode 也能共享了，
    这类能力是会变的，表要跟着真实声明走。
    """
    from ethan.kernel.acp_client_kernel import AntigravityAcpKernel, DshAcpKernel
    from ethan.kernel.acp_kernel import CodexKernel, OpenCodeKernel
    from ethan.kernel.claude_kernel import ClaudeCodeKernel
    from ethan.kernel.pi_kernel import PiKernel

    req = KernelRequest(messages=[Message(role="user", content="hi")])
    expected = {
        DshAcpKernel: True,
        ClaudeCodeKernel: True,
        OpenCodeKernel: True,
        AntigravityAcpKernel: True,
        CodexKernel: False,
        PiKernel: False,
    }
    for cls, want in expected.items():
        k = cls()
        assert k.capabilities.shares_ethan_tools is want, f"{cls.__name__} 的 shares_ethan_tools 声明变了"
        got = k._compose_prompt(req).startswith("<ethan_briefing>")
        assert got is want, f"{cls.__name__}: 期望 briefing={want}，实际 {got}"


def test_empty_request_yields_empty_prompt():
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    k = DshAcpKernel()
    assert k._compose_prompt(KernelRequest(messages=[])) == ""
