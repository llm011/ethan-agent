"""飞书 Agent 流式处理主体（_handle_agent_message）。

从 lark_stream 拆出，内嵌闭包（_update_tool_msg/_flush_answer/_emit_lark_cards）保持原位。
"""
from __future__ import annotations

import asyncio
import logging

from ethan.interface.lark_render import _render_tool_msg_content
from ethan.interface.lark_send import (
    TypingState,
    _delete_message,
    _edit_message,
    _lark_client,
    _resolve_quoted_text,
    _send_interactive_card,
    _send_message,
    _send_reply,
)
from ethan.interface.lark_tool_trace import sanitize_args_summary, sanitize_result_preview

logger = logging.getLogger(__name__)

async def _handle_agent_message(
    event_data: dict,
    *,
    chat_id: str,
    message_id: str,
    text: str,
    sender_open_id: str,
    owner_open_id: str,
    is_owner: bool,
    owner_claimed: bool,
    btw_mode: bool,
    ts: "TypingState",
) -> None:
    """真正的 Agent 流式处理（在持锁串行下运行）。_handle_message 完成去重/命令/主人判定后调本函数。"""
    # shared state from lark_stream (lazy import avoids circular dep)
    from ethan.core.agent import Agent

    # 查找或创建对应的 Session（lark 渠道归 admin）
    from ethan.core.paths import user_sessions_db_path
    from ethan.interface.lark_stream import (
        _lark_chat_map,
        _lark_running_tasks,
        _lark_welcomed,
        _load_lark_map,
        _looks_like_tool_trace,
        _mark_lark_welcomed,
        _pop_forwarded,
        _save_lark_map,
        _untrack_task,
    )
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message, ThinkingEvent, ToolEvent
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.registry import ToolRegistry
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()

    try:
        from ethan.core.config import get_config
        cfg = get_config()
        # Fast lookup: in-memory cache first, then persistent file
        if not _lark_chat_map:
            _lark_chat_map.update(_load_lark_map())
        session_id = _lark_chat_map.get(chat_id)

        if not session_id:
            session = await store.create(cfg.defaults.model, source="lark")
            # Set a clean title from the first user message
            from ethan.memory.session import _auto_title
            from ethan.providers.base import Message as _Msg
            auto = _auto_title([_Msg(role="user", content=text)])
            await store.update_title(session.id, auto)
            session_id = session.id
            _lark_chat_map[chat_id] = session.id
            _save_lark_map(_lark_chat_map)
            # 首次配置飞书时发一次欢迎语；之后拉新群、/new 清上下文都不再发（无用噪音）
            if not _lark_welcomed():
                welcome = "嘿！我是 Ethan，你的私人 AI 助手 👋\n\n我已经在这台 Mac mini 上常驻了，有任何事直接找我就行——写代码、查信息、控制设备、管理日程都行。\n\n你叫什么名字？让我记住你~"
                await _send_reply(chat_id, welcome)
                _mark_lark_welcomed()
            # Let reaction stay visible while user reads welcome, then process their actual message

        # 加载完整历史，用 WorkingMemory 重建热区（与 REPL/API 一致）
        session_obj = await store.load(session_id)
        history = session_obj.messages if session_obj else []
        session_mode = getattr(session_obj, "mode", "") or "" if session_obj else ""

        user_msg = Message(role="user", content=text)
        await store.save_message(session_id, user_msg)

        # 引用消息：lark-cli 压平的事件里没有 parent_id，需用 message_id 先 mget 当前消息详情，
        # 从详情里找被引用消息 id 再取其文本，拼到本轮发给 agent 的消息里
        # （只进 agent 上下文，不污染存库的原始 user_msg 和标题）。
        agent_user_text = text
        quoted, quoted_msg_id = await _resolve_quoted_text(message_id)
        if quoted:
            agent_user_text = f"[用户引用了一条消息]\n> {quoted}\n\n{text}"

        # 注入此前缓存的转发消息内容：用户「合并转发」一批消息后紧跟这条说明消息，
        # 把缓存的转发内容拼到本轮上下文最前面，让 agent 拿到转发原文 + 本条说明一起处理。
        # 仅进 agent 上下文，不污染存库的原始 user_msg 和标题。
        forwarded = _pop_forwarded(chat_id)
        if forwarded:
            agent_user_text = f"[用户此前转发来以下消息，请结合本条说明一起处理]\n{forwarded}\n\n---\n{agent_user_text}"

        # 非文本消息：解析资源 key，注入明确的下载指令
        # 同时扫引用的原消息（quoted_msg_id），让 agent 能下载引用消息里的图片/文件
        msg_type = event_data.get("message_type", "text")
        import re as _re

        def _build_resource_hints(content: str, src_msg_id: str) -> list[str]:
            """从 lark-cli 预渲染的 content 里提取 img_/file_ key，生成下载命令。"""
            hints = []
            for k in _re.findall(r'\bimg_[A-Za-z0-9_\-]+', content):
                hints.append(
                    f"  # 下载图片 {k}（来自消息 {src_msg_id}）：\n"
                    f"  lark-cli im +messages-resources-download "
                    f"--message-id {src_msg_id} --file-key {k} --type image"
                )
            for k in _re.findall(r'\bfile_[A-Za-z0-9_\-]+', content):
                hints.append(
                    f"  # 下载文件 {k}（来自消息 {src_msg_id}）：\n"
                    f"  lark-cli im +messages-resources-download "
                    f"--message-id {src_msg_id} --file-key {k} --type file"
                )
            return hints

        resource_hints = []
        if msg_type != "text" and message_id:
            resource_hints += _build_resource_hints(text, message_id)
        if quoted_msg_id:
            resource_hints += _build_resource_hints(quoted, quoted_msg_id)

        if resource_hints:
            hint = (
                f"[飞书消息，类型={msg_type}，message_id={message_id}]\n"
                f"{agent_user_text}"
                "\n\n[资源已识别，下载命令如下——直接执行，无需再读 lark-im 技能]\n"
                + "\n".join(resource_hints)
            )
            agent_user_text = hint
        agent_user_msg = Message(role="user", content=agent_user_text)

        # 从本地缓存读取群聊背景消息，替代每次拉 API（零延迟）
        # 仅限群聊且非 /btw 模式
        if not btw_mode and chat_id.startswith("oc_"):
            from ethan.interface.lark_state import _get_group_context
            recent_msgs = _get_group_context(chat_id, limit=10)
            if recent_msgs:
                lines = ["[群聊近期消息（供背景参考）]"]
                for m in recent_msgs:
                    prefix = f"[{m['time']}] {m['sender']}: " if m.get('sender') else f"[{m['time']}] "
                    lines.append(prefix + m["text"])
                agent_user_text = "\n".join(lines) + "\n\n---\n" + agent_user_text
                agent_user_msg = Message(role="user", content=agent_user_text)
        # 飞书场景每条 assistant 消息体积较大（含工具/思考），5 轮够用且节省 token
        from ethan.core.paths import user_facts_path
        from ethan.memory.facts import FactStore
        from ethan.memory.working import MemoryConfig, WorkingMemory
        if btw_mode:
            # /btw：不带任何历史，单轮轻量查询，上下文只有本条消息
            context_messages = [agent_user_msg]
        else:
            memory = WorkingMemory(config=MemoryConfig(hot_size=5))
            memory.cold_facts = FactStore(path=user_facts_path()).build_context()
            hist_ua = [m for m in history if m.role in ("user", "assistant")]
            pairs, i = [], 0
            while i < len(hist_ua) - 1:
                if hist_ua[i].role == "user" and hist_ua[i+1].role == "assistant":
                    pairs.append((hist_ua[i], hist_ua[i+1]))
                    i += 2
                else:
                    i += 1
            for u, a in pairs[-memory.config.hot_size:]:
                memory.hot.append(u)
                memory.hot.append(a)
            context_messages = memory.build_context() + [agent_user_msg]

        registry = ToolRegistry()
        from ethan.core.context import set_session_id
        from ethan.tools.builtin.browser import BrowserPageTool, BrowserSessionTool, BrowserTabTool
        from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
        from ethan.tools.builtin.knowledge import (
            KnowledgeAddTool,
            KnowledgeEditTool,
            KnowledgeReadTool,
            KnowledgeSearchTool,
        )
        from ethan.tools.builtin.memory_write import MemoryWriteTool
        from ethan.tools.builtin.procedure_write import ProcedureWriteTool
        from ethan.tools.builtin.profile_update import ProfileUpdateTool
        from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
        from ethan.tools.builtin.search import FdTool, RipgrepTool
        from ethan.tools.builtin.secrets import GetSecretTool, ListSecretsTool, SetSecretTool
        from ethan.tools.builtin.shell import ShellTool
        from ethan.tools.builtin.skill_create import SkillCreateTool
        from ethan.tools.builtin.skill_read import SkillListTool, SkillReadTool
        from ethan.tools.builtin.ui_card import UiCardTool
        from ethan.tools.builtin.web import WebFetchTool
        from ethan.tools.builtin.web_search import WebSearchTool
        set_session_id(session_id)  # browser 工具按对话隔离/授权
        for tool in [ShellTool(), WebSearchTool(), WebFetchTool(),
                     FileReadTool(), FileWriteTool(), FileListTool(),
                     RipgrepTool(), FdTool(),
                     ScheduleCreateTool(), ScheduleListTool(), ScheduleRemoveTool(),
                     KnowledgeSearchTool(), KnowledgeReadTool(), KnowledgeAddTool(), KnowledgeEditTool(),
                     MemoryWriteTool(), ProcedureWriteTool(), ProfileUpdateTool(), SkillCreateTool(),
                     SkillReadTool(), SkillListTool(),
                     SetSecretTool(), GetSecretTool(), ListSecretsTool(),
                     UiCardTool(channel="lark"),
                     BrowserSessionTool(), BrowserTabTool(), BrowserPageTool()]:
            registry.register(tool)
        skills = SkillRegistry()
        skills.load()
        agent = Agent(tool_registry=registry, skill_registry=skills, channel="lark", mode=session_mode)

        # 注入主人/授权运行时上下文，配合 soul.md 的主人准则判断是否执行有副作用操作
        # 环境提示：让模型知道自己在飞书 IM 渠道（轻提示，不压制正常的工具过程/结果输出）。
        # 具体场景的输出形态（如 code-review 在 IM 里只回简短总结）由对应 skill 自己约束。
        # 输出分工是飞书体验的关键：工具调用过程/中间步骤/思考由渠道单独用结构化 post 消息实时展示，
        # 模型的文字正文会被流式渲染成「结果卡片」。若模型在正文里复述过程（"我先做了X再做Y"、
        # "步骤1/2/3"、"执行了哪些命令"），这些就会刷进结果卡片，造成刷屏、主次不分。所以明确要求
        # 正文只给面向结果的答案，把过程留给系统的结构化展示。
        env_note = (
            "【运行环境】你正在【飞书】（IM 即时通讯渠道）和用户对话，回复偏简洁口语化即可。\n"
            "【输出分工，重要】你调用工具的过程、中间步骤、思考，系统会单独用结构化消息实时展示给用户，"
            "无需你在正文里复述。所以你的文字回复【只给最终的、面向结果的答案】（结论 / 产出 / 直接回应用户的话），"
            "不要写「我先做了X、再做了Y」「执行了哪些命令 / 调用了哪些工具」「步骤1/2/3」这类过程叙述，"
            "保持干净简洁、避免刷屏。\n\n"
        )
        if not owner_claimed:
            agent.runtime_context = env_note + (
                "本渠道（飞书）还没有认主人。当前发消息的人身份未确认。"
                "对有副作用/高消耗的操作（改文件、删数据、执行 shell、花钱、对外发消息）要保守，先确认。"
            )
        elif is_owner:
            agent.runtime_context = env_note + "当前发消息的人是【主人】，可执行有副作用的操作（但危险红线操作仍需拒绝/二次确认）。"
        else:
            agent.runtime_context = env_note + (
                f"当前发消息的人【不是主人】（主人 open_id={owner_open_id[:8]}…）。"
                "默认只做只读/低风险/低消耗的事；涉及改文件、删数据、执行 shell、花钱、对外发消息等操作不要主动执行，"
                "说明需要主人授权。"
            )

        # 硬策略守卫：一旦认了主人（owner_claimed），后续就要校验——非主人不得执行 side_effect 工具。
        # 没认主人则不装守卫（permissive），仅靠上面的 runtime_context 软约束。
        # 守卫通过 ContextVar 作用于本条消息的 Agent 循环（每条飞书消息在独立 task 中处理，互不影响）。
        if owner_claimed:
            from ethan.core.consent import ChannelGuardProvider, set_consent_provider
            set_consent_provider(ChannelGuardProvider(is_owner=is_owner))

        # --- 两条消息策略 ---
        # - 工具进度（post 富文本，编辑更新）：首个工具触发时发出
        # - 最终回答（卡片，流式编辑）：首段缓冲到 ≥阈值再发，避免孤立 "I" 短卡片
        #
        # 关键防泄漏：工具调用前的 narration（如 "I will read..."）不能残留为最终答案。
        # 渠道无法预判一段文字后面是否还跟工具调用，所以采用「先发、必要时撤回」：
        # 一旦又出现工具调用（说明刚那段是工具前说明而非最终答案），撤回已发的答案卡片。
        import time as _lark_time

        tool_msg_id: str | None = None
        tool_text = ""          # 工具进度消息的内容
        answer_msg_id: str | None = None
        answer_text = ""        # 已提交到答案卡片的最终答案文字
        pending = ""            # 自上次工具事件以来缓冲的文字
        collected_tool_steps: list[dict] = []
        lark_tool_start_times: dict[str, float] = {}
        last_flush = _lark_time.time()
        answer_created = False  # 答案卡片是否已创建
        thinking_shown = False  # 是否已在工具消息里显示了 "🤔 thinking..."
        tools_used = False      # 本条消息是否已调用过工具（决定正文是否还能乐观发卡片）
        # THINKING 表情由外层 TypingState(ts) 统一管理，不再用 reply_reaction_id/msg 手工记账
        FLUSH_INTERVAL = 2.0
        ANSWER_BUFFER_THRESHOLD = 50  # 纯对话首段缓冲字数，避免孤立短卡片

        async def _update_tool_msg() -> None:
            nonlocal tool_msg_id
            if not tool_text:
                return
            content = _render_tool_msg_content(tool_text)
            if tool_msg_id is None:
                from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody
                client = _lark_client()
                if client is None:
                    return
                # 工具进度是首条可见消息时，用 reply 锚定到用户那条消息（引用回复），
                # 让用户清楚机器人在响应哪条提问。message_id 缺失时退化为普通 create。
                if message_id:
                    req = (
                        ReplyMessageRequest.builder()
                        .message_id(message_id)
                        .request_body(
                            ReplyMessageRequestBody.builder()
                            .msg_type("post").content(content).build()
                        ).build()
                    )
                    resp = await asyncio.to_thread(client.im.v1.message.reply, req)
                else:
                    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
                    req = (
                        CreateMessageRequest.builder()
                        .receive_id_type("chat_id")
                        .request_body(
                            CreateMessageRequestBody.builder()
                            .receive_id(chat_id).msg_type("post").content(content).build()
                        ).build()
                    )
                    resp = await asyncio.to_thread(client.im.v1.message.create, req)
                if resp.success() and resp.data:
                    tool_msg_id = resp.data.message_id
                    # 回复消息发出后：把 THINKING 表情从用户消息迁移到工具进度消息
                    await ts.move_to(tool_msg_id)
                else:
                    # 发送失败：直接清掉用户消息上的表情
                    await ts.clear()
            else:
                from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody
                client = _lark_client()
                if client:
                    req = (
                        UpdateMessageRequest.builder()
                        .message_id(tool_msg_id)
                        .request_body(
                            UpdateMessageRequestBody.builder()
                            .msg_type("post")
                            .content(content)
                            .build()
                        )
                        .build()
                    )
                    await asyncio.to_thread(client.im.v1.message.update, req)

        async def _flush_answer(force: bool = False) -> None:
            nonlocal answer_msg_id, answer_text, pending, last_flush, answer_created
            if not pending:
                return
            # 工具流程中不乐观发卡片：工具间的零碎 narration 一旦发卡、下个工具 start 又撤回，
            # 会刷出满屏「撤回了一条消息」。工具用过后只在流结束的 force flush 落最终答案卡片，
            # 期间 pending 攒着、由工具 start 清掉（最终答案是「最后一次工具之后」那一轮的正文）。
            if tools_used and not force:
                return
            # 首段缓冲到阈值再创建卡片，避免 "I" 这种孤立短卡片（force 时跳过该限制）
            if not answer_created and not force and len(pending) < ANSWER_BUFFER_THRESHOLD:
                return
            # 已创建卡片且非 force：按 FLUSH_INTERVAL 节流流式编辑
            if answer_created and not force and (_lark_time.time() - last_flush) < FLUSH_INTERVAL:
                return
            answer_text += pending
            pending = ""
            last_flush = _lark_time.time()
            if answer_msg_id is None:
                answer_created = True
                # 引用回复：把答案卡片锚定到用户那条消息，飞书显示成"引用回复"，让用户清楚在答哪条
                answer_msg_id, _ = await _send_message(chat_id, answer_text, use_card=True, reply_to_msg_id=message_id)
                # 把 THINKING 表情迁移到答案卡片（无论之前在用户消息还是工具进度消息上）
                await ts.move_to(answer_msg_id)
            else:
                await _edit_message(answer_msg_id, answer_text, use_card=True)

        async def _emit_lark_cards(ui: list | None) -> None:
            """消费 ui_card 工具产出的 ui 列表，把其中的 lark_card 作为独立 interactive 卡片发出。

            增量能力：基础的工具进度(post)/答案(流式卡片)不受影响，这里只额外补发自定义卡片。
            锚定到用户那条消息（引用回复），让卡片紧跟在对话里。
            """
            if not ui:
                return
            for entry in ui:
                if isinstance(entry, dict) and isinstance(entry.get("lark_card"), dict):
                    await _send_interactive_card(chat_id, entry["lark_card"], reply_to_msg_id=message_id)

        # 登记当前生成任务，供 /stop 取消。同 chat 可能并发多条（事件分发 fire-and-forget），
        # 故加进 set 而非覆盖单值；结束时（正常/取消/异常）各自从 set 摘除（见 _untrack_task）。
        import asyncio as _aio
        _cur = _aio.current_task()
        if _cur is not None:
            _lark_running_tasks.setdefault(chat_id, set()).add(_cur)

        async for chunk in agent.stream_chat(context_messages):
            if isinstance(chunk, ThinkingEvent):
                # 模型思考：不打印 delta 原文（避免泄漏 reasoning），只在工具消息里挂一个占位。
                # 已有 reaction/工具进度时无需重复展示。
                if tool_msg_id is None and answer_msg_id is None and not thinking_shown:
                    tool_text = "🤔 thinking...\n"
                    await _update_tool_msg()
                    thinking_shown = True
                continue
            if isinstance(chunk, ToolEvent):
                if chunk.state == "start":
                    lark_tool_start_times[chunk.tool_name] = _lark_time.time()
                    collected_tool_steps.append({
                        "tool": chunk.tool_name,
                        "args": chunk.args_summary,
                        "intent": chunk.intent or "",
                        "state": "running",
                        "duration_ms": None,
                        "result_preview": "",
                    })
                    # 工具开始：标记本条消息已用工具，并丢弃此前累积的 pending 文字。
                    # 这段文字是「工具前的 narration/思考」（如 "I will read...", 或流式残片 "}"），
                    # 不是最终答案——最终答案在「最后一次工具调用之后」的那一轮，由流结束时的
                    # force flush 提交。一旦用过工具，_flush_answer 在 force 之前不再发卡片，
                    # 因此工具流程中不会产生「发卡→撤回」的刷屏。
                    tools_used = True
                    pending = ""
                    thinking_shown = False
                    # 一次性撤回：若在「第一个工具之前」纯对话起头已乐观发出过卡片，
                    # 现在出现工具调用，说明那段是工具前 narration 而非最终答案——删掉并重置，
                    # 否则它会和最终答案拼在同一张卡里。tools_used 已置位，之后 _flush_answer
                    # 在 force 前不再发卡，所以此撤回每条消息最多触发一次，不会刷屏。
                    if answer_created and answer_msg_id:
                        await _delete_message(answer_msg_id)
                        answer_msg_id = None
                        answer_text = ""
                        answer_created = False
                    # icon + 人性化显示名映射
                    _TOOL_DISPLAY = {
                        "shell": "💻 terminal", "rg_search": "🔍 search", "fd_find": "🔍 find",
                        "file_read": "📖 read_file", "file_write": "✏️ write_file", "file_list": "📁 list_files",
                        "web_search": "🔍 web_search", "web_fetch": "🌐 web_fetch",
                        "knowledge_search": "🧠 knowledge_search", "knowledge_add": "💾 knowledge_add",
                        "memory_write": "🧠 memory_write", "procedure_write": "📝 procedure_write",
                        "profile_update": "👤 profile_update", "skill_create": "✨ skill_create",
                        "skill_read": "📖 skill_read", "skill_list": "📋 skill_list",
                        "schedule_create": "⏰ schedule_create", "schedule_list": "⏰ schedule_list",
                        "schedule_remove": "⏰ schedule_remove",
                    }
                    display_name = _TOOL_DISPLAY.get(chunk.tool_name, f"🔧 {chunk.tool_name}")
                    tool_name_line = f"**{display_name}**"
                    intent = (chunk.intent or "").strip()
                    # args_summary 可能含命令行里的 token/--secret=xxx，刷进飞书卡片会泄漏。
                    # 先过 sanitize_args_summary 脱敏再展示（行内敏感赋值 → [redacted]）。
                    safe_args = sanitize_args_summary(chunk.args_summary or "")
                    if intent:
                        tool_name_line += f" · _{intent}_"
                        if safe_args:
                            brief = safe_args if len(safe_args) <= 60 else safe_args[:60] + "…"
                            tool_name_line += f" ({brief})"
                    elif safe_args:
                        # 模型没给 intent 时兜底显示参数摘要
                        brief = safe_args if len(safe_args) <= 60 else safe_args[:60] + "…"
                        tool_name_line += f" · {brief}"
                    # 两个工具之间用 --- 分隔（_build_tool_elements 渲染成 hr 横线），
                    # 比空行更明确地切分工具组；首工具前不加。
                    tool_text = (tool_text.rstrip() + "\n---\n" + tool_name_line + "\n") if tool_text else tool_name_line + "\n"
                    await _update_tool_msg()
                else:  # done / error
                    duration_ms = int(
                        (_lark_time.time() - lark_tool_start_times.pop(chunk.tool_name, _lark_time.time())) * 1000
                    )
                    for step in reversed(collected_tool_steps):
                        if step["tool"] == chunk.tool_name and step["state"] == "running":
                            step["state"] = chunk.state
                            step["duration_ms"] = duration_ms
                            # result_preview 可能回显含 token 的命令/URL，脱敏后再存/展示
                            step["result_preview"] = sanitize_result_preview(chunk.result_preview or "")
                            break
                    mark = "✓" if chunk.state == "done" else "✗"
                    # 耗时格式：<1s 用 ms，否则保留 1 位小数秒（始终带在结果行，不再只在没有 preview 时显示）
                    dur_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms/1000:.1f}s"
                    if chunk.state == "done":
                        # 成功是多数、轻量不抢眼：preview 截短到 80 字、换行替成空格（单行扫过）
                        preview = sanitize_result_preview(chunk.result_preview or "").replace("\n", " ").replace("`", "'")[:80]
                    else:
                        # 失败是少数、醒目有价值：preview 保留 200 字、换行用字面量 \n 占位（_build_tool_elements
                        # 把字面量 \n 还原成真换行，让多行错误堆栈作为一个 code_block 整体渲染）。
                        # 末尾的 \n 占位会被 tool_text 拼接逻辑误判成行分隔，这里剥掉（用切片避免
                        # str.rstrip 字符集语义误伤 preview 末尾的 n/反斜杠等正常字符）。
                        raw_preview = sanitize_result_preview(chunk.result_preview or "").replace("`", "'")[:200].replace("\n", "\\n")
                        if raw_preview.endswith("\\n"):
                            raw_preview = raw_preview[:-2]
                        preview = raw_preview
                    result_line = f"{mark} {dur_str} · {preview}" if preview else f"{mark} {dur_str}"
                    tool_text = tool_text.rstrip() + "\n" + result_line
                    # 有其它工具仍在运行，追加 thinking 占位
                    running = [s for s in collected_tool_steps if s["state"] == "running"]
                    if running and not thinking_shown:
                        tool_text = tool_text.rstrip() + "\n🤔 thinking...\n"
                        thinking_shown = True
                    else:
                        tool_text += "\n"
                        thinking_shown = False
                    await _update_tool_msg()
                    # ui_card 工具产出的自定义卡片：在工具完成时补发（增量，不影响上面的进度/答案流）
                    await _emit_lark_cards(getattr(chunk, "ui", None))
                continue
            # 正文 chunk：进入最终回答阶段
            # 首个正文到来时若工具消息里有 "thinking..."，在工具消息末尾补一个空行分隔
            if pending == "" and tool_msg_id is not None and thinking_shown:
                tool_text = tool_text.rstrip() + "\n"
                await _update_tool_msg()
                thinking_shown = False
            pending += chunk
            await _flush_answer()

        # 流结束：flush 剩余回答
        await _flush_answer(force=True)

        # 末尾加 token 统计到回答卡片
        usage = agent.usage
        stats_parts = [f"↑{usage.input_tokens} ↓{usage.output_tokens}"]
        if usage.cache_tokens:
            stats_parts.append(f"⚡{usage.cache_tokens}")
        stats_line = "  ".join(stats_parts)

        if answer_msg_id:
            if _looks_like_tool_trace(answer_text):
                await _edit_message(answer_msg_id, "⚠️ 本轮未生成有效总结（输出像工具过程而非结论），工具过程已记录在上方。可重试或补充说明。", use_card=True)
            else:
                final_answer = (answer_text or "（没有找到相关内容）").rstrip() + f"\n\n---\n_{stats_line}_"
                await _edit_message(answer_msg_id, final_answer, use_card=True)
            # 结果卡片已定稿，立刻移除打字中表情（不必等到 finally）
            await ts.clear()
        elif tool_msg_id:
            # 只有工具调用没有正文（极少数情况），在工具消息末尾加 stats（保持 post 富文本样式）
            final_tool = tool_text.rstrip() + f"\n\n{stats_line}"
            from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody
            _tclient = _lark_client()
            if _tclient:
                _treq = (
                    UpdateMessageRequest.builder()
                    .message_id(tool_msg_id)
                    .request_body(
                        UpdateMessageRequestBody.builder()
                        .msg_type("post")
                        .content(_render_tool_msg_content(final_tool))
                        .build()
                    )
                    .build()
                )
                await asyncio.to_thread(_tclient.im.v1.message.update, _treq)
            # 工具进度消息已定稿，立刻移除打字中表情
            await ts.clear()
        else:
            # 没有任何输出（工具和正文都没有）
            await _send_message(chat_id, f"（没有找到相关内容）\n{stats_line}", use_card=False)

        # 表情已在前面对应分支定稿时清理（ts.clear）；这里无需再手动清。

        # 存库：只存最终答案正文（reasoning 已在工具阶段丢弃），减少 context token。
        # ⚠️ 绝不把 tool_text 当 content 存（旧的 `answer_text or tool_text` fallback）——
        # 工具过程一旦进了 content，历史就被污染，下一轮模型读到「答案=工具过程格式」
        # 便在正文里模仿照抄，又被渲染成卡片、又污染历史，形成「用卡片输出工具过程」
        # 的反馈循环。没总结就空 content；模型在正文模仿工具过程格式时也清空。
        # 工具过程始终在 tool_steps 字段里，不在 content。
        clean_answer = "" if _looks_like_tool_trace(answer_text) else answer_text.strip()
        stored_content = (clean_answer + f"\n\n{stats_line}") if clean_answer else (stats_line or "")

        # 保存完整 assistant 消息到 session（带 usage + tool_steps）
        usage_dict = {
            "input": agent.usage.input_tokens,
            "output": agent.usage.output_tokens,
            "cache": agent.usage.cache_tokens,
        }
        response = Message(role="assistant", content=stored_content, usage=usage_dict, tool_steps=collected_tool_steps or [])
        await store.save_message(session_id, response)
        await store.touch(session_id)

    except asyncio.CancelledError:
        # 用户 /stop 主动取消：把已生成的部分内容落库并标记「已停止」，清理表情。
        logger.info("[Lark] generation stopped by user for chat %s", chat_id)
        try:
            # TypingState.clear 兜底清理可能残留的 THINKING 表情（异常路径下可能还没清）
            await ts.clear()
            # 取已生成的部分正文（不 fallback 到 tool_text——见存库处注释，防污染历史）
            partial = "" if _looks_like_tool_trace(answer_text) else answer_text.strip()
            if partial:
                stopped_content = partial + "\n\n（已停止）"
                if answer_msg_id:
                    await _edit_message(answer_msg_id, stopped_content, use_card=True)
                stopped_usage = {
                    "input": agent.usage.input_tokens,
                    "output": agent.usage.output_tokens,
                    "cache": agent.usage.cache_tokens,
                }
                await store.save_message(session_id, Message(
                    role="assistant", content=stopped_content,
                    usage=stopped_usage, tool_steps=collected_tool_steps or [],
                ))
                await store.touch(session_id)
        except Exception:
            logger.exception("[Lark] error while saving stopped content for chat %s", chat_id)
        finally:
            await store.close()
            _untrack_task(chat_id, asyncio.current_task())
        return

    except Exception:
        logger.exception("Agent error handling Lark message")
        # 兜底清理 THINKING 表情（TypingState 封装了异常吞咽，不会再次抛出）
        try:
            await ts.clear()
        except Exception:
            logger.debug("TypingState.clear on error path failed", exc_info=True)
        await store.close()
        _untrack_task(chat_id, asyncio.current_task())
        return

    await store.close()
    _untrack_task(chat_id, asyncio.current_task())

    # A3: 飞书渠道也触发后台记忆抽取（原来只有 Web/REPL 触发）
    try:
        from ethan.interface.routers.tasks import _maybe_consolidate
        asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, owner_open_id))
    except Exception:
        pass

