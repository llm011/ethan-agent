"""飞书消息处理：会话状态 + 命令路由 + Agent 流式回复（_handle_message）。

依赖 lark_send（收发 IO）/ lark_render（渲染）。事件去重、chat→session 映射、
进行中任务登记等会话状态也在这里（被 lark_events 的事件循环复用）。

输出形态（基础能力，勿改坏）：
- 工具进度 → post 富文本气泡（流式 update）
- 最终回答 → interactive 卡片（流式 patch）
- ui_card 工具产出的自定义卡片（lark_card）→ 额外发一条 interactive 卡片（增量，可有可无）
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import deque

from ethan.interface.lark_render import _render_tool_msg_content
from ethan.interface.lark_tool_trace import (
    sanitize_args_summary,
    sanitize_result_preview,
)
from ethan.interface.lark_send import (
    _delete_message,
    _edit_message,
    _fetch_recent_chat_messages,
    _lark_client,
    _remove_reaction,
    _resolve_quoted_text,
    _send_interactive_card,
    _send_message,
    _send_reaction,
    _send_reply,
)

logger = logging.getLogger(__name__)

# 工具进度行前缀图标（与下方 _TOOL_DISPLAY 的 display_name 对齐）。
_TOOL_LINE_RE = re.compile(r'\*\*(?:📖|💻|🔍|🌐|📁|✏️|🧠|💾|⏰|📋|✨|👤|📝|🔧)')


def _looks_like_tool_trace(text: str) -> bool:
    """检测文本是否像「工具调用过程」而非正常答案。

    正常的最终答案不该是多行 `**💻 terminal**(args)` `_✓ 结果_` 这种工具进度格式——那是
    lark_stream 内部构造的工具进度文本。模型若在正文里照抄这种格式，几乎都是读了**被污染的
    历史消息**后学到的错误模式（见存库处的 fallback 说明）：上一轮没出总结时把工具过程存进了
    content，模型读到便以为「答案长这样」而在新轮正文里模仿，又被渲染成卡片 → 又污染历史 →
    反馈循环。命中即视为无效总结，不渲染成卡片、不存进 content，从源头断循环。
    """
    if not text:
        return False
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return False
    # 有 ≥2 行带工具进度图标前缀 → 判定模仿工具过程。
    # 正常答案不会出现 `**💻 terminal**` 这种图标格式（这是 lark_stream 工具进度气泡的内部格式），
    # 模型只在读到被污染的历史后才会照抄，故命中即可视为无效总结。
    tool_lines = sum(1 for l in lines if _TOOL_LINE_RE.search(l))
    return tool_lines >= 2

_lark_chat_map: dict[str, str] = {}  # chat_id -> session_id, in-memory cache

# chat_id -> 串行锁。同一飞书 chat 连发多条消息时，Agent 处理必须排队（否则并发改同一
# session、流式卡片互相覆盖、/stop 登记混乱）。命令路径（/new /stop 等）不经锁，保持即时响应。
_lark_chat_locks: dict[str, asyncio.Lock] = {}


def _get_chat_lock(chat_id: str) -> asyncio.Lock:
    """取（或创建）该 chat 的串行锁。锁对象复用，跨消息持久。"""
    lock = _lark_chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _lark_chat_locks[chat_id] = lock
    return lock


# chat_id -> 正在处理该 chat 消息的 Agent task 集合。供 /stop 取消进行中的生成。
# 事件分发是 fire-and-forget（lark_events 里 asyncio.create_task(_handle_message)），同一 chat
# 连发多条会并发跑，故用 set 而非单值——否则后一条会覆盖前一条的登记，/stop 停不到前一个。
_lark_running_tasks: dict[str, set[asyncio.Task]] = {}


def _untrack_task(chat_id: str, task) -> None:
    """从登记表摘掉某个 task（每条消息结束时调）。空集合顺手清掉，避免泄漏。"""
    s = _lark_running_tasks.get(chat_id)
    if s is not None:
        s.discard(task)
        if not s:
            _lark_running_tasks.pop(chat_id, None)

# 飞书事件投递是 at-least-once：bot 未在超时窗口内 ack（长任务、断线重连重放）会重投同一条事件。
# 用 message_id 幂等去重，否则同一消息被处理多次（表现为重复回复 / 两份不同的 token 统计）。
_seen_message_ids: set[str] = set()
_seen_message_order: deque[str] = deque(maxlen=2000)


def _already_handled(message_id: str) -> bool:
    """命中返回 True（重复事件，应丢弃）；否则登记并返回 False。同事件循环内同步执行，无 await，天然原子。"""
    if not message_id:
        return False
    if message_id in _seen_message_ids:
        return True
    if len(_seen_message_order) == _seen_message_order.maxlen:
        _seen_message_ids.discard(_seen_message_order[0])  # deque 满，append 会丢最左，先同步移出 set
    _seen_message_order.append(message_id)
    _seen_message_ids.add(message_id)
    return False


def _lark_map_file():
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "memory" / "lark_sessions.json"


def _load_lark_map():
    import json
    f = _lark_map_file()
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}


def _save_lark_map(mapping: dict):
    import json
    f = _lark_map_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(mapping, ensure_ascii=False))


def _lark_welcomed() -> bool:
    """是否已经向飞书发过首次配置欢迎语。每个部署只发一次，之后拉新群/清上下文都不再发。"""
    from ethan.core.config import CONFIG_DIR
    return (CONFIG_DIR / "memory" / ".lark_welcomed").exists()


def _mark_lark_welcomed() -> None:
    from ethan.core.config import CONFIG_DIR
    f = CONFIG_DIR / "memory" / ".lark_welcomed"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()


async def _handle_message(event_data: dict) -> None:
    """处理收到的消息事件，调用 Agent 并流式回复。

    lark-cli event consume 输出的是扁平结构：
    {"chat_id": "oc_xxx", "content": "text", "message_id": "om_xxx",
     "message_type": "text", "sender_id": "ou_xxx", ...}

    流式策略：
    - 积累 chunk 直到 ≥80 字符或距上次发送 ≥2 秒
    - 首次 flush：移除 THINKING 表情后发送第一条消息
    - 后续 flush：lark-cli 不支持 patch，直接追加新消息
    - 最终确保完整内容已发出
    """
    from ethan.core.agent import Agent
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message, ToolEvent, ThinkingEvent
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
    from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeEditTool, KnowledgeReadTool, KnowledgeSearchTool
    from ethan.tools.builtin.memory_write import MemoryWriteTool
    from ethan.tools.builtin.procedure_write import ProcedureWriteTool
    from ethan.tools.builtin.profile_update import ProfileUpdateTool
    from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
    from ethan.tools.builtin.skill_create import SkillCreateTool
    from ethan.tools.builtin.skill_read import SkillReadTool, SkillListTool
    from ethan.tools.builtin.secrets import SetSecretTool, GetSecretTool, ListSecretsTool
    from ethan.tools.builtin.shell import ShellTool
    from ethan.tools.builtin.web import WebFetchTool
    from ethan.tools.builtin.web_search import WebSearchTool
    from ethan.tools.builtin.search import RipgrepTool, FdTool
    from ethan.tools.registry import ToolRegistry

    # lark-cli 已经把 event 字段展平，直接从顶层读取
    # post（图文混合）/ image / file / audio / video 的 content 也是 lark-cli 预渲染的可读文本：
    # post → markdown（图片占位 ![Image](img_xxx) + 正文）
    # image → ![Image](img_xxx)
    # file/audio/video → <file key="file_xxx" .../> 等
    _HANDLED_TYPES = {"text", "post", "image", "file", "audio", "video"}
    if event_data.get("message_type") not in _HANDLED_TYPES:
        return

    text = event_data.get("content", "").strip()
    if not text:
        return

    chat_id = event_data.get("chat_id", "")
    message_id = event_data.get("message_id", "")

    # 幂等去重：飞书 at-least-once 重投同一事件时直接丢弃，避免重复处理（重复回复 + 双份 token 统计）。
    if _already_handled(message_id):
        logger.info("[Lark] duplicate event dropped: message_id=%s", message_id)
        return

    # 过滤过期事件：进程重启后 _seen_message_ids 清空，lark-cli 重连会重放旧消息；
    # 超过 60 秒的消息直接丢弃，避免 restart 后处理历史命令（如 /help）刷屏。
    import time as _t
    _create_ms = int(event_data.get("create_time", "0") or "0")
    if _create_ms and (_t.time() * 1000 - _create_ms) > 60_000:
        logger.info("[Lark] stale event dropped: message_id=%s age=%ds", message_id, int((_t.time() * 1000 - _create_ms) / 1000))
        return

    # 发消息者 open_id（飞书按 open_id 认主人）。lark-cli 展平后字段名可能是
    # sender_id / open_id / sender_open_id，挨个兜底。
    sender_open_id = (
        event_data.get("sender_open_id")
        or event_data.get("open_id")
        or event_data.get("sender_id")
        or ""
    )

    if not chat_id:
        return

    # 主人判定：config.lark.owner_open_id 为空 = 还没认主人。
    from ethan.core.config import get_config as _gc
    _lark_cfg = getattr(_gc(), "lark", None)
    owner_open_id = getattr(_lark_cfg, "owner_open_id", "") if _lark_cfg else ""
    is_owner = bool(owner_open_id) and sender_open_id == owner_open_id
    owner_claimed = bool(owner_open_id)

    # ── /btw：顺带一问——不带历史、不带 cold facts 的单轮轻量查询 ──
    # 解析放在 /command 之前，因为 /btw 需要走完整 agent 流程（只是上下文为空）。
    from ethan.interface.channel_commands import CommandContext, handle_command, is_command, is_btw, btw_question, is_review, review_target
    btw_mode = False
    if is_btw(text):
        q = btw_question(text)
        if not q:
            await _send_reply(chat_id, "用法：/btw <问题>，例如：/btw 今天几号？")
            return
        btw_mode = True
        text = q

    # ── /review：不带历史、强制触发 code-review 技能 ──
    # 把文本改写成含 trigger 关键词的形式，让 skill matcher 自然命中 code-review 技能。
    # 行为同 /btw：清空历史上下文，不拉群消息背景。
    elif is_review(text):
        target = review_target(text)
        if not target:
            await _send_reply(chat_id, "用法：/review <PR/MR 链接>，例如：/review https://github.com/foo/bar/pull/123")
            return
        btw_mode = True  # 复用 btw_mode：不带历史、不拉群消息
        text = f"帮我 code review 这个 PR/MR：{target}"

    # ── /command：以 / 开头的命令先于 Agent 处理（不加思考表情，直接回复）──
    if is_command(text):
        async def _reset_lark_session(cid: str) -> None:
            """清空该飞书 chat 的会话映射，下次消息新建 session。"""
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            if cid in _lark_chat_map:
                _lark_chat_map.pop(cid)
                _save_lark_map(_lark_chat_map)

        async def _get_web_token() -> str:
            from ethan.core.config import get_config
            return getattr(get_config().network, "auth_token", "") or ""

        async def _get_model() -> str:
            from ethan.core.config import get_config
            return get_config().defaults.model

        async def _resolve_lark_session(cid: str) -> str | None:
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            return _lark_chat_map.get(cid)

        async def _list_lark_sessions(cid: str) -> str:
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from datetime import datetime
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                recent = await store.list_recent(5)
            finally:
                await store.close()
            if not recent:
                return "暂无会话。"
            current = _lark_chat_map.get(cid)
            lines = ["最近会话："]
            for s in recent:
                mark = " ← 当前" if s.id == current else ""
                t = datetime.fromtimestamp(s.updated_at).strftime("%m-%d %H:%M")
                sid = s.id if len(s.id) <= 16 else s.id[-12:]
                lines.append(f"• {sid}  {s.title}  {t}{mark}")
            lines.append("\n用 /resume <id> 恢复某个会话")
            return "\n".join(lines)

        async def _resume_lark_session(cid: str, sid_prefix: str) -> str:
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                recent = await store.list_recent(50)
            finally:
                await store.close()
            match = next((s for s in recent if s.id == sid_prefix or s.id.endswith(sid_prefix)), None)
            if not match:
                return f"找不到会话：{sid_prefix}\n用 /sessions 查看可用 id"
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            _lark_chat_map[cid] = match.id
            _save_lark_map(_lark_chat_map)
            return f"✓ 已切换到会话：{match.title}\n（继续聊即可恢复上下文）"

        async def _compact_lark_session(cid: str) -> str:
            from ethan.core.session_ops import compact_session
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from ethan.core.config import get_config
            sid = _lark_chat_map.get(cid)
            if not sid:
                if not _lark_chat_map:
                    _lark_chat_map.update(_load_lark_map())
                sid = _lark_chat_map.get(cid)
            if not sid:
                return "当前没有进行中的会话，先聊几句再 /compact 吧~"
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                return await compact_session(store, sid, get_config().defaults.model)
            finally:
                await store.close()

        async def _set_lark_owner(cid: str, sid: str) -> str:
            """认主人：把发消息者 open_id 设为主人，当前 chat 设为主会话。"""
            from ethan.core.config import get_config, save_config, reload_config
            if not sid:
                return "⚠️ 没拿到你的 open_id，无法认主人。"
            cfg = get_config()
            cfg.lark.owner_open_id = sid
            cfg.lark.main_chat_id = cid
            save_config(cfg)
            reload_config()
            return (
                "👑 已认你为主人，并把当前会话设为主会话。\n"
                "今后通知和定时任务结果会发到这里；非主人的高风险指令我会先确认。"
            )

        async def _get_lark_mode(cid: str) -> str:
            sid = _lark_chat_map.get(cid)
            if not sid:
                if not _lark_chat_map:
                    _lark_chat_map.update(_load_lark_map())
                sid = _lark_chat_map.get(cid)
            if not sid:
                return ""
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                s = await store.load(sid)
                return getattr(s, "mode", "") or "" if s else ""
            finally:
                await store.close()

        async def _set_lark_mode(cid: str, mode_key: str) -> None:
            """切换当前飞书会话模式；无会话则新建一个带该模式的 session。"""
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from ethan.core.config import get_config as _gc
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            sid = _lark_chat_map.get(cid)
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                if not sid:
                    s = await store.create(_gc().defaults.model, source="lark", mode=mode_key)
                    _lark_chat_map[cid] = s.id
                    _save_lark_map(_lark_chat_map)
                else:
                    await store.update_mode(sid, mode_key)
            finally:
                await store.close()

        async def _stop_lark_task(cid: str) -> bool:
            """取消该 chat 所有进行中的 Agent 生成任务。返回是否真的停了至少一个。"""
            tasks = _lark_running_tasks.get(cid)
            if not tasks:
                return False
            stopped = False
            for t in list(tasks):
                if not t.done():
                    t.cancel()
                    stopped = True
            return stopped

        cmd_ctx = CommandContext(
            chat_id=chat_id,
            raw_text=text,
            sender_id=sender_open_id,
            reset_session=_reset_lark_session,
            resolve_session_id=_resolve_lark_session,
            list_sessions=_list_lark_sessions,
            resume_session=_resume_lark_session,
            compact_session=_compact_lark_session,
            set_owner=_set_lark_owner,
            get_token=_get_web_token,
            get_model=_get_model,
            get_mode=_get_lark_mode,
            set_mode=_set_lark_mode,
            stop_task=_stop_lark_task,
        )
        reply = await handle_command(cmd_ctx)
        if reply:
            await _send_reply(chat_id, reply)
        return

    # ── 同 chat 串行：Agent 处理必须排队 ──
    # 同一飞书 chat 连发多条消息时，若并发跑会互相踩：并发改同一 session、流式卡片
    # 互相覆盖、/stop 登记混乱。命令路径不经锁（已 return），保持即时响应；这里只串行化
    # 真正的 Agent 生成。锁按 chat_id 复用，跨消息持久；message_id 去重已在锁外完成，
    # 重投事件不会进到这里两次。
    async with _get_chat_lock(chat_id):
        await _handle_agent_message(
            event_data,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            sender_open_id=sender_open_id,
            is_owner=is_owner,
            owner_claimed=owner_claimed,
            btw_mode=btw_mode,
        )


async def _handle_agent_message(
    event_data: dict,
    *,
    chat_id: str,
    message_id: str,
    text: str,
    sender_open_id: str,
    is_owner: bool,
    owner_claimed: bool,
    btw_mode: bool,
) -> None:
    """真正的 Agent 流式处理（在持锁串行下运行）。_handle_message 完成去重/命令/主人判定后调本函数。"""
    # 立刻加思考表情，保存 reaction_id 以便回复后删除
    reaction_id = await _send_reaction(message_id)

    # 查找或创建对应的 Session（lark 渠道归 admin）
    from ethan.core.paths import user_sessions_db_path
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

        # 拉最近 10 条群消息作为背景上下文，让 agent 感知 @mention 之间群里发生了什么。
        # 仅限群聊（chat_id 以 oc_ 开头）；私聊消息已全量在 session history 里，不重复拉。
        # /btw 无历史模式也跳过：群消息可能很大（含代码/diff），违背 /btw 精简上下文的本意。
        # 失败时静默忽略，不阻断主流程。
        if not btw_mode and chat_id.startswith("oc_"):
            recent_msgs = await _fetch_recent_chat_messages(chat_id, limit=10)
            if recent_msgs:
                lines = ["[群聊近期消息（供背景参考，最近10条）]"]
                for m in recent_msgs:
                    prefix = f"[{m['time']}] {m['sender']}: " if m['sender'] else f"[{m['time']}] "
                    lines.append(prefix + m["text"])
                agent_user_text = "\n".join(lines) + "\n\n---\n" + agent_user_text
                agent_user_msg = Message(role="user", content=agent_user_text)
        # 飞书场景每条 assistant 消息体积较大（含工具/思考），5 轮够用且节省 token
        from ethan.memory.working import MemoryConfig, WorkingMemory
        from ethan.memory.facts import FactStore
        from ethan.core.paths import user_facts_path
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
        from ethan.tools.builtin.browser import BrowserSessionTool, BrowserTabTool, BrowserPageTool
        from ethan.tools.builtin.ui_card import UiCardTool
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
        reply_reaction_id: str | None = None   # 加在回复消息上的 THINKING 表情（打字中指示器）
        reply_reaction_msg: str | None = None  # 哪条消息上有该表情
        FLUSH_INTERVAL = 2.0
        ANSWER_BUFFER_THRESHOLD = 50  # 纯对话首段缓冲字数，避免孤立短卡片

        async def _update_tool_msg() -> None:
            nonlocal tool_msg_id, reaction_id, reply_reaction_id, reply_reaction_msg
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
                    # 回复消息发出后：移除用户消息上的 THINKING，给回复消息加打字中表情
                    if reaction_id and message_id:
                        await _remove_reaction(message_id, reaction_id)
                        reaction_id = None
                    reply_reaction_id = await _send_reaction(tool_msg_id)
                    reply_reaction_msg = tool_msg_id
                else:
                    if reaction_id and message_id:
                        await _remove_reaction(message_id, reaction_id)
                        reaction_id = None
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
            nonlocal answer_msg_id, answer_text, pending, last_flush, answer_created, reaction_id, reply_reaction_id, reply_reaction_msg
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
                # 发出首条回答后移除用户消息上的 reaction（若工具进度消息没发出过）
                if reaction_id and message_id:
                    await _remove_reaction(message_id, reaction_id)
                    reaction_id = None
                # 工具进度消息上若有旧 reaction，先移除再给答案卡片加新的
                if reply_reaction_id and reply_reaction_msg:
                    await _remove_reaction(reply_reaction_msg, reply_reaction_id)
                    reply_reaction_id = None
                    reply_reaction_msg = None
                # 给答案卡片加"打字中" THINKING 表情
                reply_reaction_id = await _send_reaction(answer_msg_id)
                reply_reaction_msg = answer_msg_id
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
                    # 两个工具之间加空行
                    tool_text = (tool_text.rstrip() + "\n\n" + tool_name_line + "\n") if tool_text else tool_name_line + "\n"
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
                    preview = sanitize_result_preview(chunk.result_preview or "").replace("\n", " ").replace("`", "'")[:200]
                    result_line = f"_{mark} {preview}_" if preview else f"_{mark} {duration_ms}ms_"
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
            # 结果卡片已定稿，移除打字中表情
            if reply_reaction_id and reply_reaction_msg:
                await _remove_reaction(reply_reaction_msg, reply_reaction_id)
                reply_reaction_id = None
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
            # 工具进度消息已定稿，移除打字中表情
            if reply_reaction_id and reply_reaction_msg:
                await _remove_reaction(reply_reaction_msg, reply_reaction_id)
                reply_reaction_id = None
        else:
            # 没有任何输出（工具和正文都没有）
            await _send_message(chat_id, f"（没有找到相关内容）\n{stats_line}", use_card=False)

        # 确保两个 reaction 都被清理（理论上前面已经清了）
        if reaction_id and message_id:
            await _remove_reaction(message_id, reaction_id)
        if reply_reaction_id and reply_reaction_msg:
            await _remove_reaction(reply_reaction_msg, reply_reaction_id)

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
            if reaction_id and message_id:
                await _remove_reaction(message_id, reaction_id)
            if reply_reaction_id and reply_reaction_msg:
                await _remove_reaction(reply_reaction_msg, reply_reaction_id)
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
        # 确保表情被清理
        if reaction_id and message_id:
            await _remove_reaction(message_id, reaction_id)
        if reply_reaction_id and reply_reaction_msg:
            await _remove_reaction(reply_reaction_msg, reply_reaction_id)
        await store.close()
        _untrack_task(chat_id, asyncio.current_task())
        return

    await store.close()
    _untrack_task(chat_id, asyncio.current_task())
