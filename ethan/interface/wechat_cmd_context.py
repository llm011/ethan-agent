"""微信渠道命令上下文工厂。

与 lark_cmd_context.py 对应：把 CommandContext 需要的回调实现成模块级函数，
减少 wechat_events.py 的闭包深度。所有回调通过函数体内的延迟导入访问
store / 配置，避免模块级循环导入。

微信与飞书的会话映射差异：
- 飞书有内存映射 _lark_chat_map 持久化到 lark_sessions.json
- 微信无内存映射，通过 session title 前缀 `微信:{chat_key}:` 在 store 里搜索
  （见 wechat_events._get_or_create_session）
因此 /new 的实现是把所有该前缀的 session 改名（加 [已废弃] 前缀），
让 _get_or_create_session 下次搜不到从而新建。
"""
from __future__ import annotations

import asyncio
import logging

from ethan.interface.channel_commands import CommandContext

logger = logging.getLogger(__name__)


# ── 任务登记表 ─────────────────────────────────────────────────────────────────
# chat_key -> 正在处理该 chat 的 Agent task 集合，供 /stop 取消。
# 与 lark_state._lark_running_tasks 同构；仅登记 Agent 流程，命令分支不登记
# （否则 /stop 会取消自己）。
_wechat_running_tasks: dict[str, set[asyncio.Task]] = {}


def _register_wechat_task(chat_key: str, task: asyncio.Task) -> None:
    """登记某个 chat_key 当前正在跑的 Agent task。"""
    _wechat_running_tasks.setdefault(chat_key, set()).add(task)


def _untrack_wechat_task(chat_key: str, task: asyncio.Task) -> None:
    """task 完成时从登记表摘掉（add_done_callback 调用）。空集合顺手清掉。"""
    s = _wechat_running_tasks.get(chat_key)
    if s is not None:
        s.discard(task)
        if not s:
            _wechat_running_tasks.pop(chat_key, None)


async def _stop_wechat_task(cid: str) -> bool:
    """取消该 chat 所有进行中的 Agent 生成任务。返回是否真的停了至少一个。"""
    tasks = _wechat_running_tasks.get(cid)
    if not tasks:
        return False
    stopped = False
    for t in list(tasks):
        if not t.done():
            t.cancel()
            stopped = True
    return stopped


# ── Session 前缀工具 ───────────────────────────────────────────────────────────
# 与 wechat_events._get_or_create_session 保持一致
def _session_prefix(chat_key: str) -> str:
    return f"微信:{chat_key}:"


async def _resolve_wechat_session(chat_key: str) -> str | None:
    """根据 chat_key 在 store 里查当前 session_id。

    取 title 以 `微信:{chat_key}:` 开头的最新一条（list_recent 默认按 updated_at 降序）。
    """
    from ethan.memory.session import get_session_store
    store = await get_session_store()
    prefix = _session_prefix(chat_key)
    recent = await store.list_recent(limit=100)
    for s in recent:
        if s.title and s.title.startswith(prefix):
            return s.id
    return None


async def _reset_wechat_session(chat_key: str) -> None:
    """清空该 chat_key 的会话映射：把所有以 `微信:{chat_key}:` 开头的 session
    改名（加 [已废弃] 前缀），下次 _get_or_create_session 找不到就会新建。
    """
    from ethan.memory.session import get_session_store
    store = await get_session_store()
    prefix = _session_prefix(chat_key)
    recent = await store.list_recent(limit=100)
    for s in recent:
        if s.title and s.title.startswith(prefix):
            await store.update_title(s.id, f"[已废弃]{s.title}")


async def _list_wechat_sessions(chat_key: str) -> str:
    """列出最近 5 个 session，标注当前 chat_key 对应的会话。"""
    from datetime import datetime

    from ethan.memory.session import get_session_store
    store = await get_session_store()
    recent = await store.list_recent(5)
    if not recent:
        return "暂无会话。"
    current = await _resolve_wechat_session(chat_key)
    lines = ["最近会话："]
    for s in recent:
        mark = " ← 当前" if s.id == current else ""
        t = datetime.fromtimestamp(s.updated_at).strftime("%m-%d %H:%M")
        sid = s.id if len(s.id) <= 16 else s.id[-12:]
        lines.append(f"• {sid}  {s.title}  {t}{mark}")
    lines.append("\n用 /resume <id> 恢复某个会话（微信端暂不支持）")
    return "\n".join(lines)


async def _compact_wechat_session(chat_key: str) -> str:
    from ethan.core.config import get_config
    from ethan.core.session_ops import compact_session
    from ethan.memory.session import get_session_store
    sid = await _resolve_wechat_session(chat_key)
    if not sid:
        return "当前没有进行中的会话，先聊几句再 /compact 吧~"
    store = await get_session_store()
    return await compact_session(store, sid, get_config().defaults.model)


async def _summary_wechat_session(chat_key: str) -> str:
    from ethan.core.config import get_config
    from ethan.core.session_ops import summary_session
    from ethan.memory.session import get_session_store
    sid = await _resolve_wechat_session(chat_key)
    if not sid:
        return "当前没有进行中的会话，先聊几句再 /summary 吧~"
    store = await get_session_store()
    return await summary_session(store, sid, get_config().defaults.model)


def build_wechat_cmd_context(
    chat_key: str,
    text: str,
    sender_id: str,
    *,
    is_group_chat: bool = False,
) -> CommandContext:
    """构建微信渠道命令上下文，注入微信能实现的回调。

    未实现的回调（resume_session / new_session / set_owner / get_token /
    get_model / set_model / get_mode / set_mode）留 None，handle_command
    会自动返回「此渠道暂不支持」。
    """
    return CommandContext(
        chat_id=chat_key,
        raw_text=text,
        sender_id=sender_id,
        is_group_chat=is_group_chat,
        reset_session=_reset_wechat_session,
        resolve_session_id=_resolve_wechat_session,
        list_sessions=_list_wechat_sessions,
        compact_session=_compact_wechat_session,
        summary_session=_summary_wechat_session,
        stop_task=_stop_wechat_task,
        extra_help=(
            "微信渠道提示：\n"
            "- 会话通过 title 前缀管理，/new 会废弃当前会话\n"
            "- /resume、/owner、/model、/mode、/token 等命令暂不支持，请到 Web 端操作"
        ),
    )
