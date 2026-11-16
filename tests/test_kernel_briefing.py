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
def _isolate_paths_dir(tmp_path, monkeypatch):
    """隔离 paths.CONFIG_DIR，避免测试读到开发者本机的 ~/.ethan/system/*.md 或画像。"""
    import ethan.core.paths as paths_mod

    monkeypatch.setattr(paths_mod, "CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _fresh_cache():
    """简报按 (mode, 技能目录 mtime, 上下文文件指纹) 缓存，用例之间必须隔离。"""
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


def test_briefing_inject_context_off_omits_persona_and_rules(fake_skills, tmp_path):
    """`inject_context="off"` 时不注入任何准则、画像与人格。"""
    (tmp_path / "system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "system" / "soul.md").write_text("SOUL_RULE", encoding="utf-8")
    (tmp_path / "system" / "identity.md").write_text("ID_PERSONA", encoding="utf-8")
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "user_profile.md").write_text("# 画像\n- 喜欢简洁", encoding="utf-8")

    text = build_kernel_briefing(mode="", inject_context="off")
    for forbidden in ("<ethan_context>", "<soul>", "<identity>", "<user_profile>", "<behavioral_guidelines>"):
        assert forbidden not in text
    assert "<ethan_briefing>" in text


def test_briefing_rules_profile_injects_soul_profile_and_guidelines(fake_skills, tmp_path):
    """默认 `rules_profile` 注入 soul.md + 非空画像 + 纠错准则，但不注入 identity 人设。"""
    from ethan.memory.procedures import ProcedureStore

    (tmp_path / "system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "system" / "soul.md").write_text("绝不泄露 .secrets/", encoding="utf-8")
    (tmp_path / "system" / "identity.md").write_text("我是小艺", encoding="utf-8")
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "user_profile.md").write_text("# 用户画像\n\n## 基础特征\n- 叫我阿凌", encoding="utf-8")
    ProcedureStore(path=tmp_path / "memory" / "playbook.json").add("回答尽量给出具体路径")

    text = build_kernel_briefing(mode="", inject_context="rules_profile")
    assert "<ethan_context>" in text
    assert "<soul>" in text and "绝不泄露 .secrets/" in text
    assert "<user_profile>" in text and "叫我阿凌" in text
    assert "<behavioral_guidelines>" in text and "回答尽量给出具体路径" in text
    assert "<identity>" not in text
    assert "我是小艺" not in text


def test_briefing_full_context_injects_identity_and_mode_identity(fake_skills, tmp_path):
    """`inject_context="full"` 在 rules_profile 基础上追加 identity.md 与模式身份。"""
    (tmp_path / "system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "system" / "soul.md").write_text("SOUL_CONTENT", encoding="utf-8")
    (tmp_path / "system" / "identity.md").write_text("我是小艺", encoding="utf-8")

    text_legal = build_kernel_briefing(mode="法律", inject_context="rules_profile")
    assert "<mode_identity>" in text_legal and "法律专家" in text_legal
    assert "<identity>" not in text_legal

    text = build_kernel_briefing(mode="法律", inject_context="full")
    assert "<soul>" in text
    assert "<identity>" in text and "我是小艺" in text
    assert "<mode_identity>" in text and "法律专家" in text


def test_briefing_skips_heading_only_user_profile(fake_skills, tmp_path):
    """仅有标题骨架、没有实际内容的 user_profile.md 不应占用 prompt。"""
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "user_profile.md").write_text(
        "# 用户画像\n\n## 基础特征\n\n## 心理与情绪\n",
        encoding="utf-8",
    )
    text = build_kernel_briefing(mode="", inject_context="rules_profile")
    assert "<user_profile>" not in text


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
        assert "<available_skills>" not in prompt
        assert "<memory_recall_hint>" not in prompt
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


def test_pi_and_codex_still_receive_soul_and_profile_when_configured(tmp_path):
    """即便不支持 MCP 工具共享（Codex / Pi），soul.md 与画像依然可以注入。"""
    from ethan.kernel.acp_kernel import CodexKernel
    from ethan.kernel.pi_kernel import PiKernel

    (tmp_path / "system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "system" / "soul.md").write_text("安全红线：禁止 rm -rf ~", encoding="utf-8")

    req = KernelRequest(messages=[Message(role="user", content="hi")])
    for cls in (CodexKernel, PiKernel):
        prompt = cls()._compose_prompt(req)
        assert "<ethan_context>" in prompt
        assert "禁止 rm -rf ~" in prompt
        assert "<ethan_briefing>" not in prompt
        assert "<memory_recall_hint>" not in prompt


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


# ── 附图：落盘 + 路径（不走 inline） ─────────────────────────


@pytest.fixture
def real_images(monkeypatch, tmp_path):
    """把附图目录指到 tmp，并提供一个「真的存在」的图片文件。

    为什么必须真造文件：`_image_paths()` 会校验文件是否存在（历史消息的 path
    可能指向已清理的会话资产，死路径交给内核等于让它去读不存在的文件）。
    用假路径的测试会被这道校验挡掉，测不到真正要测的东西。
    """
    import ethan.core.assets as assets

    monkeypatch.setattr(assets, "IMAGES_DIR", tmp_path)

    def make(rel_path: str) -> str:
        f = tmp_path / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        return rel_path

    return make


def test_image_only_message_is_not_dropped(real_images):
    """只发一张图、不打字的消息必须保留。

    原实现是 `if not text: continue`，把「只发图」整条丢掉——内核连图存在都
    不知道。用户报的「给 ethan 发图片，dsh 不知道图片存在」正是这个 + inline
    被拒两条一起造成的。
    """
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    rel = real_images("s1/img_0.png")
    k = DshAcpKernel()
    req = KernelRequest(
        messages=[Message(role="user", content="", images=[{"path": rel}])],
        session_id="s1",
    )
    prompt = k._build_prompt(req)
    assert prompt, "纯图片消息被整条丢掉了"
    assert "img_0.png" in prompt


def test_image_paths_are_absolute_and_readable(real_images):
    """给的是可直接读取的绝对路径，不是相对引用。

    外部 CLI 的 cwd 是 workspace，不是 ~/.ethan/assets；给相对路径它读不到。
    """
    import os

    from ethan.kernel.acp_client_kernel import DshAcpKernel

    rel = real_images("s2/a.png")
    k = DshAcpKernel()
    req = KernelRequest(
        messages=[Message(role="user", content="看图", images=[{"path": rel}])],
        session_id="s2",
    )
    prompt = k._build_prompt(req)
    line = next(ln for ln in prompt.splitlines() if "a.png" in ln)
    path_str = line.lstrip("- ").strip()
    assert os.path.isabs(path_str), f"应该是绝对路径，实际 {path_str!r}"
    assert os.path.exists(path_str), "给的路径必须真实存在，否则内核读到的是死链"


def test_stale_image_path_is_skipped(real_images):
    """失效的附图引用（会话资产已清理）不交给内核。

    把死路径写进 prompt 比不写更糟：内核会去读、读不到，然后把失败当工具有问题
    反复重试。
    """
    from ethan.kernel.acp_client_kernel import DshAcpKernel
    from ethan.kernel.runtime import KernelRequest as KR

    real_images("s5/ok.png")  # 只让 ok.png 存在
    k = DshAcpKernel()
    req = KR(
        messages=[
            Message(
                role="user",
                content="看图",
                images=[{"path": "s5/ok.png"}, {"path": "s5/gone.png"}],
            )
        ],
        session_id="s5",
    )
    prompt = k._build_prompt(req)
    assert "ok.png" in prompt
    assert "gone.png" not in prompt, "失效引用不该出现在 prompt 里"


def test_image_prompt_does_not_dictate_a_tool(real_images):
    """不要在提示里替内核指定用哪个工具读图。

    模型本身大多有识图能力；写「用 ocr_extract_text 读」既越权又可能在
    该内核没挂 OCR 工具时把它带偏。只给位置，怎么用交给它判断。
    """
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    rel = real_images("s3/b.png")
    k = DshAcpKernel()
    req = KernelRequest(
        messages=[Message(role="user", content="", images=[{"path": rel}])],
        session_id="s3",
    )
    prompt = k._build_prompt(req)
    for tool_name in ("ocr_extract_text", "file_read", "shell"):
        assert tool_name not in prompt, f"提示里不该指定工具 {tool_name}"


def test_text_and_image_both_preserved(real_images):
    from ethan.kernel.acp_client_kernel import DshAcpKernel

    rel = real_images("s4/e.png")
    k = DshAcpKernel()
    req = KernelRequest(
        messages=[Message(role="user", content="这个报错怎么修", images=[{"path": rel}])],
        session_id="s4",
    )
    prompt = k._build_prompt(req)
    assert "这个报错怎么修" in prompt
    assert "e.png" in prompt


# ── Skill frontmatter 每轮匹配与事件发射 ──────────────────────


def _make_skill_dir(tmp_path, name: str, frontmatter: str, body: str, refs: dict[str, str] | None = None):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter.strip()}\n---\n\n{body}\n", encoding="utf-8")
    if refs:
        ref_dir = d / "references"
        ref_dir.mkdir(exist_ok=True)
        for fname, content in refs.items():
            (ref_dir / fname).write_text(content, encoding="utf-8")


def test_per_turn_skill_frontmatter_matching_injects_default_and_discoverable(tmp_path):
    """外部内核每轮按 Skill frontmatter 匹配：default 注入全文，discoverable 提示 skill_read。"""
    from ethan.kernel.acp_client_kernel import DshAcpKernel
    from ethan.kernel.runtime import KernelContext
    from ethan.skills.registry import SkillRegistry

    _make_skill_dir(
        tmp_path,
        "qcc",
        'name: qcc\ntrigger: "企查查|工商信息"\ndescription: "企业工商查询"',
        "步骤：先查缓存，再调 qcc MCP。",
        refs={"api.md": "QCC API 参考说明"},
    )
    _make_skill_dir(
        tmp_path,
        "code-review",
        'name: code-review\ncategory: discoverable\ntrigger: "review代码|代码审查"\ndescription: "代码审查规范"',
        "完整审查流程正文...",
    )

    reg = SkillRegistry()
    reg.load()
    ctx = KernelContext(skill_registry=reg)

    k = DshAcpKernel()
    req = KernelRequest(
        messages=[Message(role="user", content="帮我用企查查并做一下review代码")],
    )
    prompt, matched = k._prepare_prompt(req, ctx)
    names = [s.name for s in matched]

    assert "qcc" in names
    assert "code-review" in names
    assert "<relevant_skills>" in prompt
    assert "步骤：先查缓存，再调 qcc MCP。" in prompt
    assert "api.md" in prompt
    assert "<matched_skills_brief>" in prompt
    assert "code-review" in prompt
    assert "ethan_skill_read" in prompt


def test_per_turn_skill_matching_respects_mode_and_channel_frontmatter(tmp_path):
    """frontmatter 的 modes / channels 隔离在外部内核同样生效。"""
    from ethan.kernel.acp_client_kernel import DshAcpKernel
    from ethan.kernel.runtime import KernelContext
    from ethan.skills.registry import SkillRegistry

    _make_skill_dir(
        tmp_path,
        "legal-assistant",
        'name: legal-assistant\nmodes: [legal]\ndescription: "法律专家技能"',
        "法律研判方法论。",
    )
    _make_skill_dir(
        tmp_path,
        "lark-only",
        'name: lark-only\nchannels: [lark]\ntrigger: "飞书卡片"\ndescription: "飞书专用"',
        "飞书专用内容。",
    )

    reg = SkillRegistry()
    reg.load()
    ctx = KernelContext(skill_registry=reg)
    k = DshAcpKernel()

    # 普通模式 web 渠道：两个都不该出现
    prompt_web, matched_web = k._prepare_prompt(
        KernelRequest(messages=[Message(role="user", content="帮我发飞书卡片")], channel="web", mode=""),
        ctx,
    )
    assert matched_web == []
    assert "法律研判方法论" not in prompt_web
    assert "飞书专用内容" not in prompt_web

    # 法律模式：mode 专属技能无条件命中；lark 渠道：channel 技能命中
    prompt_legal, matched_legal = k._prepare_prompt(
        KernelRequest(messages=[Message(role="user", content="帮我发飞书卡片")], channel="lark", mode="法律"),
        ctx,
    )
    assert {s.name for s in matched_legal} == {"legal-assistant", "lark-only"}
    assert "法律研判方法论" in prompt_legal
    assert "飞书专用内容" in prompt_legal


def test_per_turn_skill_matching_skipped_without_tools_or_in_minimal_mode(tmp_path):
    """Codex / Pi 无 MCP 工具，或 minimal 精简模式下不注入技能正文与提示。"""
    from ethan.kernel.acp_client_kernel import DshAcpKernel
    from ethan.kernel.pi_kernel import PiKernel
    from ethan.kernel.runtime import KernelContext
    from ethan.skills.registry import SkillRegistry

    _make_skill_dir(
        tmp_path,
        "qcc",
        'name: qcc\ntrigger: "企查查"\ndescription: "企业查询"',
        "QCC_SECRET_BODY",
    )
    reg = SkillRegistry()
    reg.load()
    ctx = KernelContext(skill_registry=reg)

    req = KernelRequest(messages=[Message(role="user", content="查下企查查")])
    pi_prompt, pi_matched = PiKernel()._prepare_prompt(req, ctx)
    assert pi_matched == []
    assert "QCC_SECRET_BODY" not in pi_prompt

    min_req = KernelRequest(messages=[Message(role="user", content="查下企查查")], mode="minimal")
    min_prompt, min_matched = DshAcpKernel()._prepare_prompt(min_req, ctx)
    assert min_matched == []
    assert "QCC_SECRET_BODY" not in min_prompt
    assert "<mode_note>" in min_prompt
    assert "<memory_recall_hint>" not in min_prompt


def test_external_kernel_emits_skills_matched_event_and_syncs_agent(monkeypatch, tmp_path):
    """外部内核运行前命中技能时应 emit SkillsMatchedEvent 并写入 agent.last_matched_skills。"""
    import asyncio
    import ethan.acp as acp_mod
    from ethan.acp.models import ACPResult
    from ethan.kernel.claude_kernel import ClaudeCodeKernel
    from ethan.kernel.runtime import KernelContext
    from ethan.providers.base import SkillsMatchedEvent
    from ethan.skills.registry import SkillRegistry

    _make_skill_dir(
        tmp_path,
        "qcc",
        'name: qcc\ntrigger: "企查查"\ndescription: "企业查询"',
        "QCC_BODY",
    )
    reg = SkillRegistry()
    reg.load()

    class _AgentStub:
        last_matched_skills: list[str] = []
        _skills = reg
        is_owner = True
        _system_files: dict[str, str] = {}

    agent = _AgentStub()
    ctx = KernelContext(agent=agent, skill_registry=reg)

    captured_prompt = {}

    async def fake_delegate(prompt, **kwargs):
        captured_prompt["text"] = prompt
        return ACPResult(success=True, output="完成", agent="claude")

    monkeypatch.setattr(acp_mod, "delegate", fake_delegate)

    async def collect():
        return [
            e
            async for e in ClaudeCodeKernel().run(
                KernelRequest(messages=[Message(role="user", content="用企查查查腾讯")]),
                ctx,
            )
        ]

    events = asyncio.run(collect())
    skill_events = [e for e in events if isinstance(e, SkillsMatchedEvent)]
    assert len(skill_events) == 1
    assert skill_events[0].skills[0]["name"] == "qcc"
    assert agent.last_matched_skills == ["qcc"]
    assert "QCC_BODY" in captured_prompt["text"]


def test_non_owner_skips_profile_and_memory_hints(fake_skills, tmp_path):
    """非主人请求（如飞书群外人）不得把主人画像和记忆召回提示注入外部内核。"""
    (tmp_path / "system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "system" / "soul.md").write_text("SOUL_SAFE", encoding="utf-8")
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "user_profile.md").write_text("# 画像\n- 主人秘密偏好", encoding="utf-8")

    text = build_kernel_briefing(
        mode="",
        inject_context="rules_profile",
        is_owner=False,
        runtime_context="当前发消息的人【不是主人】",
    )
    assert "<soul>" in text and "SOUL_SAFE" in text
    assert "<runtime_context>" in text and "不是主人" in text
    assert "<user_profile>" not in text
    assert "主人秘密偏好" not in text
    assert "<memory_recall_hint>" not in text
    assert "<memory_write_hint>" not in text


def test_cache_invalidates_when_soul_or_profile_changes(fake_skills, tmp_path):
    """修改 soul.md / user_profile.md 后无需手动清缓存即可在下轮生效。"""
    (tmp_path / "system").mkdir(parents=True, exist_ok=True)
    soul = tmp_path / "system" / "soul.md"
    soul.write_text("第一版准则", encoding="utf-8")

    first = build_kernel_briefing(mode="", inject_context="rules_profile")
    assert "第一版准则" in first

    soul.write_text("第二版安全准则（已更新）", encoding="utf-8")
    second = build_kernel_briefing(mode="", inject_context="rules_profile")
    assert "第二版安全准则（已更新）" in second
    assert "第一版准则" not in second


def test_kernels_context_mode_api_roundtrip(tmp_path, monkeypatch):
    """GET /api/kernels 返回 inject_context，POST /api/kernels/context-mode 持久化并校验。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ethan.interface.routers import settings as settings_router

    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api")
    app.dependency_overrides[settings_router.verify_token] = lambda: ""

    client = TestClient(app)

    r1 = client.get("/api/kernels")
    assert r1.status_code == 200
    assert r1.json()["inject_context"] == "rules_profile"

    r_bad = client.post("/api/kernels/context-mode", json={"inject_context": "invalid"})
    assert r_bad.status_code == 400

    for mode in ("full", "off", "rules_profile"):
        r_set = client.post("/api/kernels/context-mode", json={"inject_context": mode})
        assert r_set.status_code == 200
        assert r_set.json() == {"ok": True, "inject_context": mode}
        r_get = client.get("/api/kernels")
        assert r_get.status_code == 200
        assert r_get.json()["inject_context"] == mode


def test_match_kernel_skills_returns_only_injected_skills_when_capped(tmp_path):
    """超过 max_skills 被截断的技能不应混入返回的 matched 列表（避免误发事件/记命中）。"""
    from ethan.kernel.briefing import match_kernel_skills
    from ethan.skills.registry import SkillRegistry

    for i in range(4):
        _make_skill_dir(
            tmp_path,
            f"sk-{i}",
            f'name: sk-{i}\ntrigger: "测试词"\ndescription: "技能{i}"',
            f"正文 {i}",
        )
    _make_skill_dir(
        tmp_path,
        "disc-extra",
        'name: disc-extra\ncategory: discoverable\ntrigger: "测试词"\ndescription: "按需技能"',
        "按需正文",
    )

    reg = SkillRegistry()
    reg.load()
    block, used = match_kernel_skills(
        [Message(role="user", content="触发测试词")],
        skill_registry=reg,
        max_skills=2,
    )
    used_default = [s for s in used if s.category != "discoverable"]
    used_disc = [s for s in used if s.category == "discoverable"]
    assert len(used_default) == 2
    assert len(used_disc) == 1
    assert used_disc[0].name == "disc-extra"
    assert "<relevant_skills>" in block
    assert "<matched_skills_brief>" in block
