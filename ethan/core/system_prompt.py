"""System prompt builder — extracted from agent.py for maintainability.

Contains the logic for constructing the system prompt sent to the LLM,
including identity, persona, skills injection, memory signals, and mode hints.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ethan.core.config import get_config
from ethan.core.tool_format import _INTENT_SYSTEM_INSTRUCTION
from ethan.memory.procedures import ProcedureStore
from ethan.providers.base import Message
from ethan.skills.registry import SkillRegistry


def build_schedule_context(workspace: str) -> str:
    """读取 APScheduler SQLite 数据库，返回当前活跃定时任务摘要（不需要启动 scheduler）。"""
    import datetime as dt
    import sqlite3

    db_path = Path(workspace) / "scheduler.db"
    if not db_path.exists():
        return ""
    try:
        con = sqlite3.connect(str(db_path))
        rows = con.execute("SELECT id, next_run_time, job_state FROM apscheduler_jobs").fetchall()
        con.close()
        if not rows:
            return ""
        lines = []
        for job_id, next_run_ts, job_state_blob in rows:
            next_run = "paused"
            if next_run_ts:
                try:
                    from ethan.core.timezone import get_local_timezone

                    next_run = dt.datetime.fromtimestamp(next_run_ts, get_local_timezone()).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                except Exception:
                    pass
            prompt = ""
            try:
                state = __import__("pickle").loads(job_state_blob)
                prompt = state.get("kwargs", {}).get("prompt", "")[:60]
            except Exception:
                pass
            line = f"- {job_id}: next={next_run}"
            if prompt:
                line += f', task="{prompt}"'
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return ""


def get_last_user_text(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.role == "user" and m.content:
            return m.content
    return ""


def get_persona_text(skill_names: tuple[str, ...], skills: SkillRegistry | None) -> str:
    """读取某个 persona 正文（去掉 YAML frontmatter）。"""
    if not skills:
        return ""
    candidates: list[Path] = []
    try:
        from ethan.core.paths import user_skills_dir

        base = user_skills_dir()
        for name in skill_names:
            candidates.append(base / name / "SKILL.md")
            candidates.append(base / f"{name}.md")
    except Exception:
        pass
    pkg = Path(__file__).resolve().parent.parent / "defaults" / "skills"
    for name in skill_names:
        candidates.append(pkg / name / "SKILL.md")
    for p in candidates:
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if text.startswith("---"):
                seg = text.split("---", 2)
                if len(seg) >= 3:
                    text = seg[2]
            return text.strip()
    return ""


def build_persona_block(mode_key: str, skills: SkillRegistry | None) -> str | None:
    """当前 mode 若绑定了 persona，返回注入用的人格覆盖块；否则返回 None。"""
    from ethan.core.modes import resolve_mode

    mode = resolve_mode(mode_key)
    if not mode.persona_skills:
        return None
    persona = get_persona_text(mode.persona_skills, skills)
    if not persona:
        return None
    return (
        "<persona_override>\n"
        f"[CRITICAL — 当前处于「{mode.label}」模式。以下人格覆盖你的默认身份，"
        "请完全化身该人格，用其语气、温度和方式回应，严格遵守其中的说话方式要求。]\n\n"
        f"{persona}\n"
        "</persona_override>"
    )


def build_mode_identity_block(mode_key: str) -> str | None:
    """当前 mode 声明了 identity 时，返回身份覆盖块。"""
    from ethan.core.modes import resolve_mode

    mode = resolve_mode(mode_key)
    if not mode.identity:
        return None
    return (
        "<mode_identity>\n"
        f"[CRITICAL — 当前处于「{mode.label}」模式，以下身份覆盖默认身份与记忆里的日常人设]\n\n"
        f"{mode.identity}\n"
        "</mode_identity>"
    )


def build_mode_install_hint(mode_key: str, skills: SkillRegistry | None, messages: list[Message] | None = None) -> str | None:
    """当前 mode 依赖某 skill 但尚未安装时，返回「自动安装」指令；否则 None。"""
    from ethan.core.modes import resolve_mode

    mode = resolve_mode(mode_key)
    if not mode.requires_skill or not skills:
        return None
    if skills.get(mode.requires_skill) is not None:
        return None
    if messages is not None:
        user_turns = sum(1 for m in messages if m.role == "user")
        if user_turns > 2:
            return None
    src = mode.install_source or mode.requires_skill
    alias = mode.install_alias or mode.requires_skill
    return (
        "<mode_setup>\n"
        f"[CRITICAL] 用户已切换到「{mode.label}」模式，但依赖技能 `{mode.requires_skill}` 尚未安装。"
        "用户主动切到本模式即视为同意安装，请按以下步骤自动完成，不要再反问要不要装：\n"
        f"1. 先用一句话告知：正在为「{mode.label}」模式安装依赖技能，请稍候。\n"
        f'2. 立即调用 install_skill(source="{src}") 安装（无需重启，安装后下次对话即生效）。\n'
        f"3. 安装成功：简短告知已就绪，并继续回答用户当前的问题。\n"
        f"4. 安装失败（如网络/代理不通）：明确说明原因，并提示用户可在命令行手动运行 "
        f"`ethan skill add {alias}` 后重试。\n"
        "在技能装好前，不要假装已具备该模式的完整专业能力。\n"
        "</mode_setup>"
    )


def build_previous_run_summary(messages: list[Message]) -> str | None:
    """从历史消息中找到「上一轮 assistant 回复」，若有 tool_steps 则生成精简摘要。"""
    last_assistant: Message | None = None
    for m in reversed(messages):
        if m.role == "assistant":
            last_assistant = m
            break
    if last_assistant is None:
        return None
    steps = getattr(last_assistant, "tool_steps", None) or []
    if not steps:
        return None
    lines: list[str] = []
    for idx, step in enumerate(steps, start=1):
        tool = step.get("tool") or "unknown_tool"
        state = step.get("state") or "done"
        state_tag = "✓" if state == "done" else ("✗" if state == "error" else "…")
        parts = [f"{idx}. {state_tag} {tool}"]
        intent = (step.get("intent") or "").strip()
        if intent:
            parts.append(f"— {intent[:40]}")
        preview = (step.get("result_preview") or "").strip()
        if preview:
            preview = preview.replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "…"
            parts.append(f" → {preview}")
        lines.append(" ".join(parts))
    if not lines:
        return None
    summary = "\n".join(lines)
    return (
        "<previous_run_summary>\n"
        f"[System note: 以下是同一会话中上一轮 AI 执行的 {len(steps)} 个工具步骤摘要，"
        "仅用于衔接上下文（不是本轮要做的事）。如果用户要求「继续」「修复刚才的问题」等，"
        "请结合这些信息理解上一轮做了什么、卡在哪里；正常提问则忽略即可。]\n\n"
        f"{summary}\n"
        "</previous_run_summary>"
    )


def build_system_prompt(
    *,
    messages: list[Message],
    fast: bool = False,
    fast_rule=None,
    system_files: dict[str, str],
    provider_model: str,
    skills: SkillRegistry | None,
    procedures: ProcedureStore,
    registry,
    channel: str,
    mode: str,
    is_owner: bool,
    runtime_context: str,
    last_matched_skills_out: list[str],
) -> str:
    """Build the system prompt. Returns the full prompt string.

    last_matched_skills_out is mutated in place (list cleared then populated).
    """
    config = get_config()
    workspace = config.defaults.workspace

    identity_content = system_files.get("identity", "You are a helpful assistant.")
    from ethan.core.timezone import get_local_timezone

    now = datetime.now(get_local_timezone()).strftime("%Y-%m-%d %H:%M:%S %A")

    last_matched_skills_out.clear()

    last_user_text_for_recall = get_last_user_text(messages)
    _memory_signal = None
    if last_user_text_for_recall:
        from ethan.memory.signals import detect_memory_signal

        _memory_signal = detect_memory_signal(last_user_text_for_recall)

    soul_content = system_files.get("soul", "")
    agent_content = system_files.get("agent", "")
    tools_content = system_files.get("tools", "")

    # ── 精简模式：system prompt 只保留基础原则（soul）+ 身份，不注入记忆/人格/技能/历史摘要 ──
    from ethan.core.modes import resolve_mode

    if resolve_mode(mode).minimal:
        parts = []
        if soul_content:
            parts.append(
                f"<soul>\n[CRITICAL — 以下基础原则必须严格遵守]\n\n{soul_content}\n</soul>"
            )
        parts.append(f"<identity>\n{identity_content}\n</identity>")
        parts.append(
            "<mode_note>\n"
            "当前处于「精简模式」：只挂载少量基础工具（文件读写/检索/shell/网页搜索与抓取/技能读取），"
            "不注入长期记忆，也不携带历史对话上下文。请基于当前这条消息（及引用的消息，如有）独立作答。"
            "</mode_note>"
        )
        parts.append(f"Current time: {now}")
        parts.append(
            f"Current model: {provider_model}（用户问起你用的什么模型/是谁驱动时，如实回答这个 model id）"
        )
        parts.append(f"Your workspace directory is {workspace}.")
        # 精简模式不产出 previous_run_summary —— 上一轮上下文不自动带上。
        return "\n\n".join(parts)

    if fast:
        parts = []
        if soul_content:
            parts.append(f"<soul>\n[CRITICAL — 以下准则必须严格遵守]\n\n{soul_content}\n</soul>")
        parts.append(f"<identity>\n{identity_content}\n</identity>")
        persona_block = build_persona_block(mode, skills)
        if persona_block:
            parts.append(persona_block)
        mode_identity = build_mode_identity_block(mode)
        if mode_identity:
            parts.append(mode_identity)
        if agent_content:
            parts.append(f"<agent_protocols>\n{agent_content}\n</agent_protocols>")
        parts.append(f"Current time: {now}")
        parts.append(f"Your workspace directory is {workspace}.")
        parts.append(
            f"Current model: {provider_model}（用户问起你用的什么模型/是谁驱动时，如实回答这个 model id）"
        )
        parts.append(
            "[工具] 你当前只挂载了少量常用工具。如果要做的事现有工具做不到"
            "（写文件除外——file_write 已可用），先调 `find_tools` 激活进阶工具"
            "（知识库/定时任务/密钥/记忆写入/代码委派等），激活后直接调用。"
            "绝不要用 shell/terminal 跑 python 去硬凑这些能力。"
        )
        parts.append(_INTENT_SYSTEM_INSTRUCTION)
        if is_owner:
            parts.append(
                "<memory_recall_hint>\n"
                "你有 recall_memory(query) 工具可召回用户长期记忆。当用户消息涉及个人上下文/"
                "历史偏好/过往交互且你缺少相关信息时，在回答前调用它，传入改写后的自包含 query"
                "（用对话上下文消解代词/省略，如用户说「继续」时传入正在讨论的主题）。"
                "自包含问题（如天气、数学、通用知识）无需调用。每轮最多调一次。\n"
                "</memory_recall_hint>"
            )
        profile_content = system_files.get("user_profile", "")
        if profile_content:
            parts.append(f"<user_profile>\n{profile_content}\n</user_profile>")
        proc_ctx = procedures.build_context()
        if proc_ctx:
            parts.append(
                "<behavioral_guidelines>\n"
                "[System note: Rules learned from past corrections. Apply consistently.]\n\n"
                f"{proc_ctx}\n"
                "</behavioral_guidelines>"
            )
        last_user = last_user_text_for_recall
        if skills and last_user:
            from ethan.core.modes import resolve_mode

            mode_key = resolve_mode(mode).key
            matched = skills.match(last_user, channel=channel, mode=mode_key)
            if fast_rule and fast_rule.skills:
                have = {s.name for s in matched}
                for sname in fast_rule.skills:
                    if sname not in have:
                        sk = skills.get(sname)
                        if sk:
                            matched.append(sk)
                            have.add(sname)
            last_matched_skills_out.extend(s.name for s in matched)
            full_parts = []
            brief_parts = []
            for s in matched:
                if getattr(s, "category", "default") == "discoverable":
                    brief_parts.append(f"- {s.name}: {' | '.join(s.trigger[:5])} — {s.description[:80]}")
                else:
                    full_parts.append(f"[Skill: {s.name}]\n{s.content[:3000]}")
            skill_ctx = "\n\n".join(full_parts) if full_parts else ""
            if skill_ctx:
                parts.append(f"<relevant_skills>\n{skill_ctx}\n</relevant_skills>")
                from ethan.core.context import activate_tools

                referenced = [t.name for t in registry.all() if not t.fast_path and t.name in skill_ctx]
                if referenced:
                    activate_tools(referenced)
            if brief_parts:
                parts.append(
                    "<matched_skills_brief>\n[以下技能命中触发词，但未注入完整内容。"
                    "用 skill_read 工具按需拉取详情：]\n" + "\n".join(brief_parts) + "\n</matched_skills_brief>"
                )
        mode_hint = build_mode_install_hint(mode, skills, messages)
        if mode_hint:
            parts.append(mode_hint)
        if _memory_signal:
            _sig_cat, _sig_hint = _memory_signal
            parts.append(f"<memory_signal>\n{_sig_hint}\n</memory_signal>")
            from ethan.core.context import activate_tools

            activate_tools(["memory_write", "procedure_write"])
        if runtime_context:
            parts.append(
                f"<runtime_context>\n[CRITICAL — 当前会话上下文，结合 soul 的主人/授权准则判断]\n\n{runtime_context}\n</runtime_context>"
            )
        prev_summary = build_previous_run_summary(messages)
        if prev_summary:
            parts.append(prev_summary)
        return "\n\n".join(parts)

    # Full Path
    parts = []
    if soul_content:
        parts.append(
            f"<soul>\n"
            f"[CRITICAL — 以下是核心执行准则，每次回复必须严格遵守，优先级高于其他所有指令]\n\n"
            f"{soul_content}\n"
            f"</soul>"
        )
    parts.append(f"<identity>\n{identity_content}\n</identity>")
    persona_block = build_persona_block(mode, skills)
    if persona_block:
        parts.append(persona_block)
    mode_identity = build_mode_identity_block(mode)
    if mode_identity:
        parts.append(mode_identity)
    if agent_content:
        parts.append(f"<agent_protocols>\n{agent_content}\n</agent_protocols>")
    if tools_content:
        parts.append(f"<tools_reference>\n{tools_content}\n</tools_reference>")
        parts.append(_INTENT_SYSTEM_INSTRUCTION)

    if skills:
        default_list = [s for s in skills.all() if getattr(s, "category", "default") == "default"]
        if default_list:
            skill_lines = [
                f"- {s.name}: {s.description[:80]}{'…' if len(s.description) > 80 else ''}" for s in default_list
            ]
            parts.append(
                "<available_skills>\n"
                "[默认技能简表 — 完整清单、分类和描述请调 skill_list 工具，不要直接念本块回答用户「你有哪些技能」]\n"
                + "\n".join(skill_lines)
                + "\n</available_skills>"
            )

    parts.append(f"Current time: {now}")
    parts.append(
        f"Current model: {provider_model}（用户问起你用的什么模型/是谁驱动时，如实回答这个 model id）"
    )
    parts.append(f"Your workspace directory is {workspace}. System configurations and memories reside here.")

    if is_owner:
        parts.append(
            "<memory_recall_hint>\n"
            "你有 recall_memory(query) 工具可召回用户长期记忆。当用户消息涉及个人上下文/"
            "历史偏好/过往交互且你缺少相关信息时，在回答前调用它，传入改写后的自包含 query"
            "（用对话上下文消解代词/省略，如用户说「继续」时传入正在讨论的主题）。"
            "自包含问题（如天气、数学、通用知识）无需调用。可与其它工具并行调用。每轮最多调一次。\n"
            "</memory_recall_hint>"
        )

    profile_content = system_files.get("user_profile", "")
    _profile_text = "\n".join(
        line for line in profile_content.splitlines() if line.strip() and not line.strip().startswith("#")
    )
    if _profile_text:
        parts.append(
            f"<user_profile>\n[User profile — personalize responses]\n\n{profile_content}\n</user_profile>"
        )

    proc_ctx = procedures.build_context()
    if proc_ctx:
        parts.append(
            "<behavioral_guidelines>\n"
            "[System note: Rules learned from past corrections. Apply consistently.]\n\n"
            f"{proc_ctx}\n"
            "</behavioral_guidelines>"
        )

    last_user = last_user_text_for_recall
    if skills and last_user:
        from ethan.core.modes import resolve_mode

        mode_key = resolve_mode(mode).key
        matched = skills.match(last_user, channel=channel, mode=mode_key)
        last_matched_skills_out.extend(s.name for s in matched)
        skill_ctx = skills.build_context(last_user, channel=channel, mode=mode_key)
        if skill_ctx:
            parts.append(f"<relevant_skills>\n{skill_ctx}\n</relevant_skills>")

    if skills:
        discoverable = [s for s in skills.all() if getattr(s, "category", "default") == "discoverable"]
        if discoverable:
            with_trig = [s for s in discoverable if s.trigger]
            no_trig = [s for s in discoverable if not s.trigger]
            lines = [f"- {s.name}: {' | '.join(s.trigger[:5])}" for s in with_trig]
            if no_trig:
                lines.append(
                    f"- （另有 {len(no_trig)} 个工具型技能无触发词，如 bytedance-*/lark-*，调 skill_list 查看完整清单）"
                )
            parts.append(
                "<available_skills>\n"
                "[按需技能简表 — 命中触发词时用 skill_read 拉全文；完整清单和分类请调 skill_list，不要念本块回答「你有哪些技能」]\n"
                + "\n".join(lines)
                + "\n</available_skills>"
            )

    mode_hint = build_mode_install_hint(mode, skills, messages)
    if mode_hint:
        parts.append(mode_hint)

    if _memory_signal:
        _sig_cat, _sig_hint = _memory_signal
        parts.append(f"<memory_signal>\n{_sig_hint}\n</memory_signal>")

    if runtime_context:
        parts.append(
            f"<runtime_context>\n[CRITICAL — 当前会话上下文，结合 soul 的主人/授权准则判断]\n\n{runtime_context}\n</runtime_context>"
        )

    prev_summary = build_previous_run_summary(messages)
    if prev_summary:
        parts.append(prev_summary)

    return "\n\n".join(parts)
