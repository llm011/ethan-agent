"""后台任务会话的过滤与 query 去重测试。

两个回归点：
1. 后台任务会话（title 前缀 `[后台]` / `✅ [后台]`）不该出现在侧边栏和「全部会话」里——
   一次 deep-review 会扇出多条，全堆进去会把正常对话挤没。入口收敛到任务中心 +
   主会话顶部任务条。这里验证 store 层的 exclude_title_prefixes 能正确排除它们。
2. 后台会话里同一条 query 曾出现两次：background_task 建会话时预存了一次，
   _run_background 又经 POST /api/chat 发一次，而 /api/chat 自己会落库。
   修复是去掉预存。这里验证 background_task 不再预存 prompt。
"""

import asyncio
from unittest.mock import patch

from ethan.memory.session import SessionStore
from ethan.providers.base import Message


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


async def _seed(store):
    """造 4 个会话：普通 / [后台] / ✅ [后台] / [心跳]。"""
    ids = {}
    for key, title in [
        ("plain", "普通对话"),
        ("bg", "[后台] PR323 维度扫描 A"),
        ("bg_done", "✅ [后台] 验证F1：可达性"),
        ("hb", "[心跳] 2026-09-12 · 系统维护"),
    ]:
        s = await store.create("m", source="web", mode="")
        await store.update_title(s.id, title)
        await store.save_message(s.id, Message(role="user", content="内容"))
        ids[key] = s.id
    return ids


def test_background_sessions_excluded_by_prefix(tmp_path):
    """[后台] / ✅ [后台] 前缀会话被排除，普通会话保留。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        got = await store.list_recent(
            50, 0, exclude_title_prefixes=["[后台]", "✅ [后台]"],
        )
        return {s.id for s in got}, ids

    got, ids = asyncio.run(_run())
    assert ids["plain"] in got
    assert ids["bg"] not in got, "[后台] 会话应被排除"
    assert ids["bg_done"] not in got, "✅ [后台] 会话应被排除"
    # 心跳未在本测试的排除列表里，仍在结果中（验证排除是精确的，不是一刀切）
    assert ids["hb"] in got


def test_background_exclusion_composes_with_heartbeat_exclusion(tmp_path):
    """[后台] 与 [心跳] 排除可叠加（对齐 /sessions 的 hide_* 语义）。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        got = await store.list_recent(
            50, 0, exclude_title_prefixes=["[后台]", "✅ [后台]", "[心跳]"],
        )
        return {s.id for s in got}, ids

    got, ids = asyncio.run(_run())
    assert got == {ids["plain"]}


def test_background_prefix_like_is_literal_not_charclass(tmp_path):
    """回归：SQLite 的 LIKE 里 `[后台]` 是字面量（GLOB 才是字符类）。

    若被当成字符类，`[后台]%` 会匹配「任何单个字符开头」的标题，
    把普通会话一起误杀 —— 这里用一个以「后」开头的普通标题来验证不会误伤。
    """
    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.create("m", source="web", mode="")
        await store.update_title(s.id, "后端服务的重构计划")  # 以「后」开头，非 [后台]
        await store.save_message(s.id, Message(role="user", content="x"))
        got = await store.list_recent(50, 0, exclude_title_prefixes=["[后台]"])
        return {x.id for x in got}, s.id

    got, sid = asyncio.run(_run())
    assert sid in got, "「后端…」这类普通标题不应被 [后台] 前缀误伤"


def test_background_task_does_not_presave_prompt(tmp_path):
    """background_task 建会话时不应预存 prompt（否则与 /api/chat 的落库重复）。"""
    async def _run():
        store = await _mk_store(tmp_path)
        calls: list[tuple] = []

        real_save = store.save_message

        async def spy_save(session_id, msg):
            calls.append((msg.role, msg.content))
            return await real_save(session_id, msg)

        async def fake_get_store():
            return store

        from ethan.tools.builtin.background_task import BackgroundTaskTool

        # 打桩：不让线程真的去发 HTTP；只验证建会话阶段的落库行为
        with patch(
            "ethan.memory.session.get_session_store", fake_get_store,
        ), patch.object(store, "save_message", spy_save), patch(
            "ethan.tools.builtin.background_task.threading.Thread",
        ) as mock_thread:
            mock_thread.return_value.start = lambda: None
            await BackgroundTaskTool(user_id="").run(title="测试任务", prompt="请调研 X")

        # 建会话阶段不应有任何 user 消息落库（prompt 由后续 /api/chat 落）
        assert calls == [], f"不应预存消息，实际落库：{calls}"

        # 会话确实建出来了，且标题带 [后台] 前缀
        recent = await store.list_recent(50, 0)
        assert len(recent) == 1
        assert recent[0].title.startswith("[后台]")

    asyncio.run(_run())
