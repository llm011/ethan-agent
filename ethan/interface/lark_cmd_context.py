"""飞书命令上下文工厂：把 _handle_message 里内嵌的 session 回调提升为模块级函数，
减少 lark_stream.py 的闭包深度。

所有回调通过函数体内的延迟导入访问 lark_stream 的共享状态（_lark_chat_map 等），
避免模块级循环导入。
"""
from __future__ import annotations

from ethan.interface.channel_commands import CommandContext


async def _reset_lark_session(cid: str) -> None:
    """清空该飞书 chat 的会话映射，下次消息新建 session。"""
    from ethan.interface.lark_stream import _lark_chat_map, _load_lark_map, _save_lark_map
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
    from ethan.interface.lark_stream import _lark_chat_map, _load_lark_map
    if not _lark_chat_map:
        _lark_chat_map.update(_load_lark_map())
    return _lark_chat_map.get(cid)


async def _list_lark_sessions(cid: str) -> str:
    from datetime import datetime

    from ethan.interface.lark_stream import _lark_chat_map
    from ethan.memory.session import get_session_store
    store = await get_session_store()
    recent = await store.list_recent(5)
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
    from ethan.interface.lark_stream import _lark_chat_map, _load_lark_map, _save_lark_map
    from ethan.memory.session import get_session_store
    store = await get_session_store()
    recent = await store.list_recent(50)
    match = next((s for s in recent if s.id == sid_prefix or s.id.endswith(sid_prefix)), None)
    if not match:
        return f"找不到会话：{sid_prefix}\n用 /sessions 查看可用 id"
    if not _lark_chat_map:
        _lark_chat_map.update(_load_lark_map())
    _lark_chat_map[cid] = match.id
    _save_lark_map(_lark_chat_map)
    return f"✓ 已切换到会话：{match.title}\n（继续聊即可恢复上下文）"


async def _compact_lark_session(cid: str) -> str:
    from ethan.core.config import get_config
    from ethan.core.session_ops import compact_session
    from ethan.interface.lark_stream import _lark_chat_map, _load_lark_map
    from ethan.memory.session import get_session_store
    sid = _lark_chat_map.get(cid)
    if not sid:
        if not _lark_chat_map:
            _lark_chat_map.update(_load_lark_map())
        sid = _lark_chat_map.get(cid)
    if not sid:
        return "当前没有进行中的会话，先聊几句再 /compact 吧~"
    store = await get_session_store()
    return await compact_session(store, sid, get_config().defaults.model)


async def _summary_lark_session(cid: str) -> str:
    from ethan.core.config import get_config
    from ethan.core.session_ops import summary_session
    from ethan.interface.lark_stream import _lark_chat_map, _load_lark_map
    from ethan.memory.session import get_session_store
    sid = _lark_chat_map.get(cid)
    if not sid:
        if not _lark_chat_map:
            _lark_chat_map.update(_load_lark_map())
        sid = _lark_chat_map.get(cid)
    if not sid:
        return "当前没有进行中的会话，先聊几句再 /summary 吧~"
    store = await get_session_store()
    return await summary_session(store, sid, get_config().defaults.model)


async def _set_lark_owner(cid: str, sid: str) -> str:
    """认主人：把发消息者 open_id 设为主人，当前 chat 设为主会话。

    安全策略：
    - 已有主人时，只有当前主人才能重新绑定（防止他人抢夺）
    - 未认主人时，第一个执行 /owner 的人成为主人
    """
    from ethan.core.config import get_config, reload_config, save_config
    if not sid:
        return "⚠️ 没拿到你的 open_id，无法认主人。"
    cfg = get_config()
    current_owner = getattr(cfg.lark, "owner_open_id", "") or ""
    # 已有主人且不是当前主人 → 拒绝
    if current_owner and current_owner != sid:
        return "⚠️ 已有主人绑定，只有当前主人才能重新设置。如需转移，请主人本人操作。"
    cfg.lark.owner_open_id = sid
    cfg.lark.main_chat_id = cid
    save_config(cfg)
    reload_config()
    return (
        "👑 已认你为主人，并把当前会话设为主会话。\n"
        "今后通知和定时任务结果会发到这里；非主人的高风险指令我会先确认。"
    )


async def _get_lark_mode(cid: str) -> str:
    from ethan.interface.lark_stream import _lark_chat_map, _load_lark_map
    from ethan.memory.session import get_session_store
    sid = _lark_chat_map.get(cid)
    if not sid:
        if not _lark_chat_map:
            _lark_chat_map.update(_load_lark_map())
        sid = _lark_chat_map.get(cid)
    if not sid:
        return ""
    store = await get_session_store()
    s = await store.load(sid)
    return getattr(s, "mode", "") or "" if s else ""


async def _set_lark_mode(cid: str, mode_key: str) -> None:
    """切换当前飞书会话模式；无会话则新建一个带该模式的 session。"""
    from ethan.core.config import get_config as _gc
    from ethan.interface.lark_stream import _lark_chat_map, _load_lark_map, _save_lark_map
    from ethan.memory.session import get_session_store
    if not _lark_chat_map:
        _lark_chat_map.update(_load_lark_map())
    sid = _lark_chat_map.get(cid)
    store = await get_session_store()
    if not sid:
        s = await store.create(_gc().defaults.model, source="lark", mode=mode_key)
        _lark_chat_map[cid] = s.id
        _save_lark_map(_lark_chat_map)
    else:
        await store.update_mode(sid, mode_key)


def build_cmd_context(chat_id: str, text: str, sender_open_id: str, *, is_group_chat: bool = False) -> CommandContext:
    """构建命令上下文，注入所有飞书 session 回调。

    在 _handle_message 的 is_command 分支调用，替代原来的 10 个内嵌闭包。
    """
    from ethan.interface.lark_stream import _stop_lark_task

    return CommandContext(
        chat_id=chat_id,
        raw_text=text,
        sender_id=sender_open_id,
        is_group_chat=is_group_chat,
        reset_session=_reset_lark_session,
        resolve_session_id=_resolve_lark_session,
        list_sessions=_list_lark_sessions,
        resume_session=_resume_lark_session,
        compact_session=_compact_lark_session,
        summary_session=_summary_lark_session,
        set_owner=_set_lark_owner,
        get_token=_get_web_token,
        get_model=_get_model,
        get_mode=_get_lark_mode,
        set_mode=_set_lark_mode,
        stop_task=_stop_lark_task,
    )
