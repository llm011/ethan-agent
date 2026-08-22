"""飞书交互增强测试：卡片按钮 / 长答案分段 / 答案登记表 / reaction 反馈 / /tasks 命令。"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from ethan.interface.channel_commands import CommandContext, handle_command
from ethan.interface.lark_render import (
    ANSWER_SPLIT_THRESHOLD,
    _card_action_buttons,
    _render_card_content,
    _split_long_text,
)
from ethan.interface.lark_state import (
    _get_answer_entry,
    _lark_answer_map,
    _register_answer,
    _update_answer_entry,
)


def run_async(coro):
    return asyncio.run(coro)


# ── 卡片操作按钮渲染 ──────────────────────────────────────────────────────────

def test_card_action_buttons_format():
    buttons = _card_action_buttons([
        {"cmd": "regenerate", "text": "🔄 重新生成"},
        {"cmd": "copy", "text": "📋 复制原文"},
        {"cmd": "", "text": "空 cmd 应被跳过"},
        {"cmd": "x", "text": ""},
    ])
    assert len(buttons) == 2
    assert buttons[0]["tag"] == "button"
    assert buttons[0]["value"] == {"cmd": "regenerate"}
    assert buttons[0]["text"]["content"] == "🔄 重新生成"
    assert buttons[1]["value"] == {"cmd": "copy"}


def test_render_card_content_with_actions():
    content = json.loads(_render_card_content(
        "hello world",
        actions=[{"cmd": "regenerate", "text": "🔄 重新生成"}],
    ))
    elements = content["body"]["elements"]
    assert elements[0]["tag"] == "markdown"
    assert elements[-1]["tag"] == "action"
    assert elements[-1]["actions"][0]["value"] == {"cmd": "regenerate"}


def test_render_card_content_without_actions_has_no_action_element():
    content = json.loads(_render_card_content("hello"))
    tags = [e["tag"] for e in content["body"]["elements"]]
    assert "action" not in tags


# ── 长答案分段 ────────────────────────────────────────────────────────────────

def test_split_short_text_single_chunk():
    assert _split_long_text("short") == ["short"]
    assert _split_long_text("") == [""]


def test_split_long_text_prefers_paragraph_boundary():
    para = "a" * 100 + "\n\n"
    text = para * 100  # 10100 chars, plenty of \n\n boundaries
    chunks = _split_long_text(text)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= ANSWER_SPLIT_THRESHOLD


def test_split_long_text_hard_cut_when_no_boundary():
    text = "x" * (ANSWER_SPLIT_THRESHOLD * 2 + 10)
    chunks = _split_long_text(text)
    assert len(chunks) == 3
    assert all(len(c) <= ANSWER_SPLIT_THRESHOLD for c in chunks)
    assert "".join(chunks) == text  # 硬切不丢字符


def test_split_long_text_content_preserved_on_lines():
    lines = "\n".join(f"line-{i:04d}" + "x" * 50 for i in range(200))
    chunks = _split_long_text(lines)
    # 行边界切割不丢行（拼接处行还原，允许边界行归属任一段）
    assert all("line-" in c for c in chunks)
    assert sum(len(c.split("\n")) for c in chunks) >= 200


# ── 答案登记表 ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_answer_map():
    _lark_answer_map.clear()
    yield
    _lark_answer_map.clear()


def test_register_and_get_answer_entry():
    _register_answer(
        "om_answer1",
        chat_id="oc_chat1",
        session_id="sess1",
        question="今天天气怎么样",
        question_msg_id="om_q1",
        assistant_row_id=42,
    )
    entry = _get_answer_entry("om_answer1")
    assert entry is not None
    assert entry["chat_id"] == "oc_chat1"
    assert entry["session_id"] == "sess1"
    assert entry["question"] == "今天天气怎么样"
    assert entry["assistant_row_id"] == 42
    assert entry["answer_text"] == ""


def test_update_answer_entry():
    _register_answer("om_a", chat_id="c", session_id="s", question="q", question_msg_id="qm")
    _update_answer_entry("om_a", answer_text="最终答案", assistant_row_id=7)
    entry = _get_answer_entry("om_a")
    assert entry["answer_text"] == "最终答案"
    assert entry["assistant_row_id"] == 7


def test_get_answer_entry_missing():
    assert _get_answer_entry("om_nonexistent") is None
    assert _get_answer_entry("") is None


def test_answer_map_max_prune():
    for i in range(150):
        _register_answer(f"om_{i}", chat_id="c", session_id="s", question="q", question_msg_id="qm")
    assert len(_lark_answer_map) <= 100


def test_answer_entry_ttl_expiry():
    import ethan.interface.lark_state as st
    _register_answer("om_old", chat_id="c", session_id="s", question="q", question_msg_id="qm")
    # 把时间戳拨到 25h 前
    _lark_answer_map["om_old"]["_ts"] -= st._ANSWER_MAP_TTL + 1
    assert _get_answer_entry("om_old") is None
    assert "om_old" not in _lark_answer_map


# ── /tasks 命令 ───────────────────────────────────────────────────────────────

def test_tasks_command_both_lists():
    ctx = CommandContext(
        chat_id="oc_c",
        raw_text="/tasks",
        list_bg_tasks=AsyncMock(return_value="🖥 后台任务：\n  ▶️ 跑一个长任务 — running（30s）"),
        list_cron_jobs=AsyncMock(return_value="⏰ 定时任务：\n  • 日报 — cron → 明天 08:00"),
    )
    reply = run_async(handle_command(ctx))
    assert "后台任务" in reply and "跑一个长任务" in reply
    assert "定时任务" in reply and "日报" in reply


def test_tasks_command_empty():
    ctx = CommandContext(
        chat_id="oc_c",
        raw_text="/tasks",
        list_bg_tasks=AsyncMock(return_value=""),
        list_cron_jobs=AsyncMock(return_value=""),
    )
    reply = run_async(handle_command(ctx))
    assert "没有后台任务" in reply


def test_tasks_command_no_callbacks():
    ctx = CommandContext(chat_id="oc_c", raw_text="/tasks")
    reply = run_async(handle_command(ctx))
    assert "没有后台任务" in reply


# ── 卡片回调路由 ──────────────────────────────────────────────────────────────

def test_card_action_copy_uses_registry():
    from ethan.interface.lark_event_handlers import _handle_card_action
    _register_answer("om_card", chat_id="oc_c", session_id="s", question="q", question_msg_id="qm")
    _update_answer_entry("om_card", answer_text="答案原文")
    event = {
        "action_tag": "button",
        "action_value": json.dumps({"cmd": "copy"}),
        "message_id": "om_card",
        "chat_id": "oc_c",
        "open_id": "ou_user",
    }
    with patch("ethan.interface.lark_fetch._send_reply", new=AsyncMock()) as mock_send:
        run_async(_handle_card_action(event))
        mock_send.assert_awaited_once()
        sent = mock_send.call_args[0][1]
        assert "答案原文" in sent


def test_card_action_copy_missing_entry():
    from ethan.interface.lark_event_handlers import _handle_card_action
    event = {
        "action_tag": "button",
        "action_value": json.dumps({"cmd": "copy"}),
        "message_id": "om_gone",
        "chat_id": "oc_c",
        "open_id": "ou_user",
    }
    with patch("ethan.interface.lark_fetch._send_reply", new=AsyncMock()) as mock_send:
        run_async(_handle_card_action(event))
        mock_send.assert_awaited_once()
        assert "找不到原答案" in mock_send.call_args[0][1]


def test_card_action_regenerate_missing_entry():
    from ethan.interface.lark_event_handlers import _handle_card_action
    event = {
        "action_tag": "button",
        "action_value": json.dumps({"cmd": "regenerate"}),
        "message_id": "om_gone",
        "chat_id": "oc_c",
        "open_id": "ou_user",
    }
    with patch("ethan.interface.lark_fetch._send_reply", new=AsyncMock()) as mock_send:
        run_async(_handle_card_action(event))
        # regenerate 走 create_task，异步执行；等一拍
        run_async(asyncio.sleep(0.05))
        mock_send.assert_awaited_once()


# ── reaction 反馈 ─────────────────────────────────────────────────────────────

def test_reaction_feedback_recorded():
    from ethan.interface.lark_event_handlers import _handle_reaction
    _register_answer("om_card", chat_id="oc_c", session_id="sess_fb", question="q", question_msg_id="qm")

    store = AsyncMock()
    store.save_message = AsyncMock(return_value=1)
    with patch("ethan.memory.session.get_session_store", return_value=store), \
         patch("ethan.interface.lark_typing._send_reaction", new=AsyncMock()) as mock_react:
        run_async(_handle_reaction({
            "reaction_type": "THUMBSUP",
            "message_id": "om_card",
            "chat_id": "oc_c",
            "operator_id": "ou_owner",
        }))
        store.save_message.assert_awaited_once()
        saved_msg = store.save_message.call_args[0][1]
        assert saved_msg.role == "user"
        assert "用户反馈" in saved_msg.content and "👍" in saved_msg.content
        store.touch.assert_awaited_once_with("sess_fb")
        mock_react.assert_awaited_once_with("om_card", "DONE")


def test_reaction_non_answer_ignored():
    from ethan.interface.lark_event_handlers import _handle_reaction
    with patch("ethan.interface.lark_typing._send_reaction", new=AsyncMock()) as mock_react:
        run_async(_handle_reaction({
            "reaction_type": "THUMBSUP",
            "message_id": "om_user_msg",  # 不在登记表
            "chat_id": "oc_c",
            "operator_id": "ou_owner",
        }))
        mock_react.assert_not_awaited()


def test_reaction_other_emoji_ignored():
    from ethan.interface.lark_event_handlers import _handle_reaction
    _register_answer("om_card", chat_id="oc_c", session_id="s", question="q", question_msg_id="qm")
    with patch("ethan.interface.lark_typing._send_reaction", new=AsyncMock()) as mock_react:
        run_async(_handle_reaction({
            "reaction_type": "THINKING",  # bot 自己的打字表情
            "message_id": "om_card",
            "chat_id": "oc_c",
        }))
        mock_react.assert_not_awaited()


# ── regenerate：task 登记（/stop 可取消）+ 删行精确锚定 ─────────────────────

class _Msg:
    def __init__(self, id: int, role: str, content: str):
        self.id = id
        self.role = role
        self.content = content


class _SessionObj:
    def __init__(self, messages):
        self.messages = messages


class _NullLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def test_regenerate_registers_running_task():
    """regenerate task 必须登记进 _lark_running_tasks：/stop 才能取消它。"""
    from ethan.interface import lark_event_handlers as handlers
    from ethan.interface.lark_state import _lark_running_tasks

    entry = {"chat_id": "oc_c", "session_id": "s", "question": "q",
             "question_msg_id": "qm", "answer_text": "a", "assistant_row_id": 7}

    async def _main():
        release = asyncio.Event()
        inner_calls = 0

        async def _slow_inner(*a, **k):
            nonlocal inner_calls
            inner_calls += 1
            await release.wait()  # 阻塞住，模拟 Agent 重跑中

        with patch("ethan.interface.lark_state._get_answer_entry", return_value=entry), \
             patch.object(handlers, "_do_regenerate_inner", new=_slow_inner):
            t = asyncio.create_task(handlers._do_regenerate("om_card", "oc_c", "ou_u"))
            await asyncio.sleep(0.01)
            registered = any(t is x for x in _lark_running_tasks.get("oc_c", set()))
            alive = registered and not t.done()
            release.set()  # 放行
            await t
            return alive, inner_calls, _lark_running_tasks.get("oc_c")

    alive, called, leftover = asyncio.run(_main())
    assert alive is True   # 跑动期间在登记表里，/stop 能取消
    assert called == 1     # 实际执行了 inner
    assert not leftover    # 结束后摘除，不泄漏


def test_regenerate_delete_rows_anchor_by_question():
    """无 assistant_row_id 的旧条目：按问题内容锚定，不误删最新一轮。"""
    from ethan.interface import lark_event_handlers as handlers

    # 历史：u1(旧问题) a1(旧答案) u2(新问题) a2(新答案)。点的是「旧卡片」。
    msgs = [
        _Msg(1, "user", "旧问题"),
        _Msg(2, "assistant", "旧答案"),
        _Msg(3, "user", "新问题"),
        _Msg(4, "assistant", "新答案"),
    ]
    entry = {"chat_id": "oc_c", "session_id": "s", "question": "旧问题",
             "question_msg_id": "qm", "answer_text": "", "assistant_row_id": None}
    store = AsyncMock()
    store.load = AsyncMock(return_value=_SessionObj(msgs))
    store.delete_message_by_id = AsyncMock()

    async def _run():
        with patch("ethan.interface.lark_state._get_answer_entry", return_value=entry), \
             patch("ethan.memory.session.get_session_store", return_value=store), \
             patch("ethan.core.config.get_config"), \
             patch("ethan.interface.lark_agent._handle_agent_message", new=AsyncMock()), \
             patch("ethan.interface.lark_stream._get_chat_lock", new=lambda cid: _NullLock()), \
             patch("ethan.interface.lark_send.TypingState") as _ts:
            _ts.return_value.__aenter__ = AsyncMock(return_value=None)
            _ts.return_value.clear = AsyncMock()
            await handlers._do_regenerate_inner("om_old_card", "oc_c", "ou_owner")

    asyncio.run(_run())
    deleted = {c.args[0] for c in store.delete_message_by_id.await_args_list}
    assert deleted == {1, 2}  # 删旧问题+旧答案，绝不动 {3,4}（最新一轮）


def test_regenerate_delete_rows_skip_feedback_rows():
    """有 assistant_row_id：问题行锚定要跳过 [用户反馈] 标记行。"""
    from ethan.interface import lark_event_handlers as handlers

    msgs = [
        _Msg(1, "user", "旧问题"),
        _Msg(2, "assistant", "旧答案"),
        _Msg(3, "user", "[用户反馈] 用户对上一条回答点了 👍"),
        _Msg(4, "assistant", "新答案"),
    ]
    entry = {"chat_id": "oc_c", "session_id": "s", "question": "旧问题",
             "question_msg_id": "qm", "answer_text": "", "assistant_row_id": 2}
    store = AsyncMock()
    store.load = AsyncMock(return_value=_SessionObj(msgs))
    store.delete_message_by_id = AsyncMock()

    async def _run():
        with patch("ethan.interface.lark_state._get_answer_entry", return_value=entry), \
             patch("ethan.memory.session.get_session_store", return_value=store), \
             patch("ethan.core.config.get_config"), \
             patch("ethan.interface.lark_agent._handle_agent_message", new=AsyncMock()), \
             patch("ethan.interface.lark_stream._get_chat_lock", new=lambda cid: _NullLock()), \
             patch("ethan.interface.lark_send.TypingState") as _ts:
            _ts.return_value.__aenter__ = AsyncMock(return_value=None)
            _ts.return_value.clear = AsyncMock()
            await handlers._do_regenerate_inner("om_old_card", "oc_c", "ou_owner")

    asyncio.run(_run())
    deleted = {c.args[0] for c in store.delete_message_by_id.await_args_list}
    assert deleted == {1, 2}  # 反馈行 3 不删


# ── 尾部反馈收集（reaction 反馈进 agent 上下文）──────────────────────────────

def test_collect_tail_feedback():
    from ethan.interface.lark_state import _collect_tail_feedback
    history = [
        _Msg(1, "user", "问题1"),
        _Msg(2, "assistant", "答案1"),
        _Msg(3, "user", "[用户反馈] 用户对上一条回答点了 👍"),
    ]
    assert _collect_tail_feedback(history) == ["[用户反馈] 用户对上一条回答点了 👍"]
    # 反馈被消化（其后有新 assistant）→ 不再收集，避免重复进上下文
    history2 = history + [_Msg(4, "user", "问题2"), _Msg(5, "assistant", "答案2")]
    assert _collect_tail_feedback(history2) == []
    # 多条尾部反馈按时间正序
    history3 = [
        _Msg(1, "assistant", "答案"),
        _Msg(2, "user", "[用户反馈] 点了 👎"),
        _Msg(3, "user", "[用户反馈] 点了 👍"),
    ]
    assert _collect_tail_feedback(history3) == ["[用户反馈] 点了 👎", "[用户反馈] 点了 👍"]
    # 无尾部反馈
    assert _collect_tail_feedback([_Msg(1, "assistant", "a")]) == []


# ── 代码围栏安全切分 ─────────────────────────────────────────────────────────

def test_split_avoids_cutting_code_fence():
    """切点不能落在未闭合 ``` 围栏内：每段围栏计数应为偶数。"""
    # 结构：普通文本 + 代码块 + 尾部文本，总长超 limit，切点大概率落在围栏内
    head = "段落文本。\n\n" * 400
    code = "```python\n" + "x = 1\n" * 350 + "```\n"
    tail = "结尾说明。\n\n" * 200
    text = head + code + tail
    chunks = _split_long_text(text, limit=3000)
    assert len(chunks) > 1
    for c in chunks:
        assert c.count("```") % 2 == 0  # 每段围栏自闭合


def test_fence_adjust_oversized_code_block_hard_cut():
    """单个代码块超过 limit：只能硬切（回退会导致某段过短），但不丢内容。"""
    text = "```python\n" + "x = 1\n" * 1500 + "```"
    chunks = _split_long_text(text, limit=3000)
    assert all(len(c) <= 3000 for c in chunks)
    joined = "".join(chunks)
    # 硬切剥离了部分换行，但实质内容（x = 1 行数）不丢
    assert joined.count("x = 1") == 1500
