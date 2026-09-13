"""SessionStore.load 分页：只取最近 N 条 / 取 before 之前的一页。

背景：长会话（最多 841 条消息、单会话 10.7MB）全量返回会让点开会话卡好几秒，
前端其实只渲染最近 10 条。这里锁住后端的分页语义。

不变量：
- 不传 limit/before 时行为与分页前完全一致（全量、正序）
- 分页返回的 messages 仍是时间正序
- before 是「严格早于」，恰好翻页不会重复拿到同一条
- has_more_messages 判断准确（含边界：没有了 / 恰好还有一条）
"""

import asyncio

from ethan.memory.session import SessionStore
from ethan.providers.base import Message


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


async def _seed(store, sid="s1", n=10):
    """写入 n 条消息，返回它们的 id（正序）。"""
    if not await store.load(sid):
        await store.create_with_id(sid, model="m", source="web", mode="")
    ids = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msg = Message(role=role, content=f"msg-{i}")
        mid = await store.save_message(sid, msg)
        ids.append(mid)
    return ids


def test_load_without_paging_returns_everything(tmp_path):
    """不传参数 = 全量，且正序（兼容既有调用方）。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store, n=10)
        s = await store.load("s1")
        await store.close()
        assert [m.id for m in s.messages] == ids
        assert [m.content for m in s.messages] == [f"msg-{i}" for i in range(10)]

    asyncio.run(_run())


def test_limit_returns_most_recent_and_in_order(tmp_path):
    """limit=3 取最近 3 条，且仍按时间正序返回（不是倒序）。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store, n=10)
        s = await store.load("s1", limit=3)
        await store.close()
        assert [m.id for m in s.messages] == ids[-3:]
        assert [m.content for m in s.messages] == ["msg-7", "msg-8", "msg-9"]

    asyncio.run(_run())


def test_before_excludes_the_boundary_message(tmp_path):
    """before 是严格早于：不会重复拿到边界那条。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store, n=10)
        # 用第 5 条（index 4）作边界，应拿到它之前的 4 条里的最近 2 条
        s = await store.load("s1", limit=2, before=ids[4])
        await store.close()
        assert [m.id for m in s.messages] == ids[2:4]
        assert all(m.id < ids[4] for m in s.messages)

    asyncio.run(_run())


def test_paging_covers_all_messages_without_gaps_or_dupes(tmp_path):
    """一页页往回翻，能无重无漏地覆盖全部消息。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store, n=10)
        collected = []
        before = None
        while True:
            s = await store.load("s1", limit=3, before=before)
            page = [m.id for m in s.messages]
            if not page:
                break
            collected = page + collected
            before = page[0]
            if not await store.has_more_messages("s1", before):
                break
        await store.close()
        assert collected == ids

    asyncio.run(_run())


def test_has_more_messages_boundaries(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store, n=3)
        first = ids[0]
        # 最旧那条之前没有更多了
        assert await store.has_more_messages("s1", first) is False
        # 第二条之前还有第一条
        assert await store.has_more_messages("s1", ids[1]) is True
        await store.close()

    asyncio.run(_run())


def test_limit_larger_than_total_returns_all(tmp_path):
    """limit 超过总数时返回全部，不报错，也不补空。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store, n=3)
        s = await store.load("s1", limit=100)
        await store.close()
        assert [m.id for m in s.messages] == ids

    asyncio.run(_run())


def test_limit_zero_is_clamped_not_crashing(tmp_path):
    """limit=0 不应让 SQL 变成 LIMIT 0 拿到空页（内部钳到 1）。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store, n=5)
        s = await store.load("s1", limit=0)
        await store.close()
        assert [m.id for m in s.messages] == [ids[-1]]

    asyncio.run(_run())


def test_empty_session_paging_is_safe(tmp_path):
    """空会话分页不抛错，返回空 messages。"""
    async def _run():
        store = await _mk_store(tmp_path)
        await store.create_with_id("empty", model="m", source="web", mode="")
        s = await store.load("empty", limit=10)
        n = await store.count_messages("empty")
        await store.close()
        assert s.messages == []
        assert n == 0

    asyncio.run(_run())


def test_nonexistent_session_returns_none(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.load("nope", limit=10)
        await store.close()
        assert s is None

    asyncio.run(_run())
