"""飞书事件处理（已读、reaction 反馈、卡片按钮回调）。

- message_read：日志记录（事件需在飞书后台订阅后才会上报）
- reaction：👍/👎 在答案卡片上 → 反馈写入会话历史（agent 下轮可见）
- card action：答案卡片按钮（重新生成 / 复制原文 / test）
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _handle_message_read(event_data: dict) -> None:
    reader_id = (
        event_data.get("reader_id")
        or event_data.get("reader_open_id")
        or event_data.get("open_id")
        or ""
    )
    message_id = event_data.get("message_id", "")
    chat_id = event_data.get("chat_id", "")
    logger.info("[Lark] message read: chat=%s msg=%s by=%s", chat_id, message_id, reader_id)


async def _handle_reaction(event_data: dict) -> None:
    """reaction 事件。答案卡片上的 👍/👎 记录为用户反馈（进会话历史，agent 下轮可见）。

    其它 emoji（含 bot 自己加的 THINKING/STRIVE）只记日志。非答案卡片上的 reaction 忽略
    （用户互相点赞等，与 bot 无关）。
    """
    rt = event_data.get("reaction_type", "")
    if isinstance(rt, dict):  # 兼容未展平的结构 {emoji_type: ...}
        rt = rt.get("emoji_type", "") or ""
    operator_id = (
        event_data.get("operator_id")
        or event_data.get("operator_open_id")
        or event_data.get("open_id")
        or ""
    )
    message_id = event_data.get("message_id", "")
    chat_id = event_data.get("chat_id", "")

    if rt not in ("THUMBSUP", "THUMBSDOWN"):
        logger.debug("[Lark] reaction %s ignored (not feedback emoji) chat=%s", rt, chat_id)
        return

    from ethan.interface.lark_state import _get_answer_entry
    entry = _get_answer_entry(message_id)
    if not entry:
        logger.debug("[Lark] reaction %s on non-answer msg %s ignored", rt, message_id)
        return

    try:
        from ethan.memory.session import get_session_store
        from ethan.providers.base import Message

        good = rt == "THUMBSUP"
        emoji = "👍" if good else "👎"
        wish = "满意，继续保持这类回答风格" if good else "不满意，后续回答注意改进质量"
        note = f"[用户反馈] 用户对上一条回答点了 {emoji}（{wish}）。"
        store = await get_session_store()
        await store.save_message(entry["session_id"], Message(role="user", content=note))
        await store.touch(entry["session_id"])
        # bot 加 ✅ reaction 作为确认（不发消息，避免噪音）
        from ethan.interface.lark_typing import _send_reaction
        await _send_reaction(message_id, "DONE")
        logger.info(
            "[Lark] feedback recorded: chat=%s session=%s good=%s by=%s",
            entry["chat_id"], entry["session_id"], good, operator_id[:12] if operator_id else "(?)",
        )
    except Exception:
        logger.exception("[Lark] failed to record reaction feedback for msg %s", message_id)


async def _handle_card_action(event_data: dict) -> None:
    """卡片按钮回调：按 action_value.cmd 路由（regenerate / copy / test）。"""
    action_tag = event_data.get("action_tag", "")
    action_value_raw = event_data.get("action_value", "")
    action_name = event_data.get("action_name", "")
    form_value = event_data.get("form_value", {})
    message_id = event_data.get("message_id", "")
    chat_id = event_data.get("chat_id", "")
    open_id = event_data.get("open_id", "")
    token = event_data.get("token", "")

    import json as _json
    try:
        action_value = _json.loads(action_value_raw) if action_value_raw else {}
    except (ValueError, TypeError):
        action_value = {"_raw": action_value_raw}

    logger.info(
        "[Lark] card action: chat=%s msg=%s tag=%s name=%s value=%s form=%s by=%s",
        chat_id, message_id, action_tag, action_name, action_value, form_value, open_id,
    )

    cmd = (action_value.get("cmd") if isinstance(action_value, dict) else "") or ""
    if cmd == "test" and chat_id:
        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "✅ card.action.trigger 已打通"},
                "template": "green",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": (
                            f"收到按钮回调：`tag={action_tag}` `name={action_name}`\n"
                            f"点击者：`{open_id}`\n"
                            f"原消息：`{message_id}`\n"
                            "事件链路 OK，后续可据 action_value 路由到具体工作流。"
                        ),
                    }
                ]
            },
        }
        from ethan.interface.lark_send import _send_interactive_card
        await _send_interactive_card(chat_id, card)
        logger.debug(
            "[Lark] card action test echo sent: chat=%s token_present=%s",
            chat_id, bool(token),
        )
        return
    if cmd == "regenerate":
        # 起独立 task：重生成要跑完整 Agent 流程，不能阻塞事件消费循环
        import asyncio as _aio
        _aio.create_task(_do_regenerate(message_id, chat_id, open_id))
        return
    if cmd == "copy":
        await _do_copy_answer(message_id, chat_id)
        return
    logger.debug("[Lark] unhandled card action cmd=%s", cmd)


async def _do_copy_answer(card_msg_id: str, chat_id: str) -> None:
    """复制原文：把答案原始 markdown 用 post 气泡重发（post 文本可长按复制）。"""
    from ethan.interface.lark_fetch import _send_reply
    from ethan.interface.lark_render import _split_long_text
    from ethan.interface.lark_state import _get_answer_entry

    entry = _get_answer_entry(card_msg_id)
    text = (entry or {}).get("answer_text", "") or ""
    if not text:
        await _send_reply(chat_id, "⚠️ 找不到原答案上下文（服务可能已重启），请直接重发问题。")
        return
    chunks = _split_long_text(text, limit=4000)
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        prefix = f"【原文 {i + 1}/{total}】\n" if total > 1 else "【原文】\n"
        await _send_reply(chat_id, prefix + chunk)


async def _do_regenerate(card_msg_id: str, chat_id: str, operator_open_id: str) -> None:
    """重新生成：定位原问题 → 删上一轮 user/assistant 落库行 → 重跑 Agent（不重复存 user 消息）。

    task 登记进 _lark_running_tasks，/stop 可取消（与 _handle_message 同规则）。
    """
    import asyncio as _aio

    from ethan.interface.lark_state import _lark_running_tasks, _untrack_task

    cur_task = _aio.current_task()
    if cur_task is not None:
        _lark_running_tasks.setdefault(chat_id, set()).add(cur_task)
    try:
        await _do_regenerate_inner(card_msg_id, chat_id, operator_open_id)
    finally:
        if cur_task is not None:
            _untrack_task(chat_id, cur_task)


async def _do_regenerate_inner(card_msg_id: str, chat_id: str, operator_open_id: str) -> None:
    from ethan.interface.lark_fetch import _send_reply
    from ethan.interface.lark_send import TypingState
    from ethan.interface.lark_state import _get_answer_entry, _lark_running_tasks

    entry = _get_answer_entry(card_msg_id)
    if not entry:
        await _send_reply(chat_id, "⚠️ 找不到原问题上下文（服务可能已重启），请直接重发问题。")
        return
    question = entry.get("question", "")
    if not question:
        await _send_reply(chat_id, "⚠️ 原问题为空，无法重新生成。")
        return

    # 已有任务在跑：提示先停止（同 chat 并发写库会乱）
    tasks = _lark_running_tasks.get(chat_id)
    if tasks and any(not t.done() for t in tasks):
        await _send_reply(chat_id, "⏳ 当前有回复正在进行中，等它完成或发 /stop 后再试。")
        return

    # 主人判定（与 _handle_message 同规则）
    from ethan.core.config import get_config as _gc
    _lark_cfg = getattr(_gc(), "lark", None)
    owner_open_id = getattr(_lark_cfg, "owner_open_id", "") if _lark_cfg else ""
    is_owner = bool(owner_open_id) and bool(operator_open_id) and operator_open_id == owner_open_id
    owner_claimed = bool(owner_open_id)

    # 删上一轮落库行（本卡片对应的那一轮）：
    # - 有 assistant_row_id（落库时回写）：直接用，精确删这张卡片对应的 assistant 行；
    # - 无 row id（旧条目兜底）：按原问题内容从后往前锚定——找与本卡片问题一致的最后一条
    #   user 行，删它之后的第一条 assistant。绝不能兜底扫「最后一条 assistant」：
    #   用户点旧卡片时会误删最新一轮，重跑上下文直接串掉。
    # - 都锚定不到：不删行直接重跑（宁可上下文多一轮冗余，不可删错）。
    from ethan.memory.session import get_session_store
    store = await get_session_store()
    session_obj = await store.load(entry["session_id"])
    rows_to_delete: list[int] = []
    if session_obj:
        msgs = session_obj.messages
        assistant_row = entry.get("assistant_row_id")
        if assistant_row:
            rows_to_delete.append(assistant_row)
            # 问题行 = assistant 行之前最近的非反馈 user 行（跳过 [用户反馈] 标记行）
            for m in reversed(msgs):
                if m.role == "user" and getattr(m, "id", 0) and m.id < assistant_row:
                    if (m.content or "").startswith("[用户反馈]"):
                        continue
                    rows_to_delete.append(m.id)
                    break
        else:
            q = question.strip()
            for idx in range(len(msgs) - 1, -1, -1):
                m = msgs[idx]
                if m.role != "user" or not getattr(m, "id", None):
                    continue
                if m.content.startswith("[用户反馈]") or (m.content or "").strip() != q:
                    continue
                for j in range(idx + 1, len(msgs)):
                    if msgs[j].role == "assistant" and getattr(msgs[j], "id", None):
                        rows_to_delete.append(m.id)
                        rows_to_delete.append(msgs[j].id)
                        break
                break
    for rid in dict.fromkeys(rows_to_delete):  # 去重，保序
        try:
            await store.delete_message_by_id(rid)
        except Exception:
            logger.debug("[Lark] delete row %s failed on regenerate", rid, exc_info=True)

    # 重跑 Agent：合成最小 event_data（text 类型，无资源）；引用锚定回原问题消息
    import time as _t
    synthetic_event = {
        "chat_id": chat_id,
        "message_type": "text",
        "content": question,
        "message_id": entry.get("question_msg_id", ""),
        "create_time": str(int(_t.time() * 1000)),
        "sender_id": operator_open_id,
    }
    from ethan.interface.lark_agent import _handle_agent_message
    from ethan.interface.lark_stream import _get_chat_lock

    ts = TypingState(card_msg_id)  # THINKING 挂在旧答案卡片上，指示正在重新生成
    await ts.__aenter__()
    try:
        async with _get_chat_lock(chat_id):
            await _handle_agent_message(
                synthetic_event,
                chat_id=chat_id,
                message_id=entry.get("question_msg_id", ""),
                text=question,
                sender_open_id=operator_open_id,
                owner_open_id=owner_open_id,
                is_owner=is_owner,
                owner_claimed=owner_claimed,
                btw_mode=False,
                ts=ts,
                save_user_msg=False,
            )
    except Exception:
        logger.exception("[Lark] regenerate failed for chat %s", chat_id)
        await ts.clear()
