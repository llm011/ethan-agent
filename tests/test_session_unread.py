"""会话未读红点（last_read_at 水位）语义测试。

不变量：未读 = updated_at > last_read_at。
- 新会话已读（水位=创建时刻）
- 消息到达（touch）产生未读；mark_read 推进水位消除未读，幂等
- 元数据更新（改标题/换模式）不制造未读，也不吞掉已有未读
- 旧库迁移：存量会话回填为已读，避免升级后满屏红点
"""

import asyncio
import sqlite3

from ethan.memory.session import SessionStore
from ethan.providers.base import Message


def _unread(s) -> bool:
    return s.updated_at > s.last_read_at


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


def test_new_session_is_read(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        sid = (await store.create("m", source="web", mode="")).id
        (s,) = await store.list_recent(10)
        assert s.id == sid
        assert not _unread(s), "新会话不应有未读红点"

    asyncio.run(_run())


def test_touch_creates_unread_and_mark_read_clears(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        sid = (await store.create("m", source="web", mode="")).id
        await store.save_message(sid, Message(role="assistant", content="后台回复"))
        await store.touch(sid)  # 模拟后台消息落库后的时间戳推进

        (s,) = await store.list_recent(10)
        assert _unread(s), "消息到达后应有未读红点"

        advanced = await store.mark_read(sid)
        assert advanced is True
        (s,) = await store.list_recent(10)
        assert not _unread(s), "mark_read 后红点应消失"

        # 幂等：已读再 mark_read 返回 False
        assert await store.mark_read(sid) is False

    asyncio.run(_run())


def test_metadata_update_never_creates_or_clears_unread(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        read_sid = (await store.create("m", source="web", mode="")).id
        unread_sid = (await store.create("m", source="web", mode="")).id
        # unread_sid 制造未读
        await store.save_message(unread_sid, Message(role="assistant", content="x"))
        await store.touch(unread_sid)

        pre_updated = {s.id: s.updated_at for s in await store.list_recent(10)}
        await store.update_title(read_sid, "改名后的已读会话")
        await store.update_mode(read_sid, "legal")

        by_id = {s.id: s for s in await store.list_recent(10)}
        assert not _unread(by_id[read_sid]), "已读会话改标题/换模式不应出现红点"
        assert by_id[read_sid].title == "改名后的已读会话"
        assert by_id[read_sid].mode == "legal"
        # updated_at 确实被推进了（排除『没更新导致不未读』的假阳性）
        assert by_id[read_sid].updated_at > pre_updated[read_sid]

        await store.update_title(unread_sid, "改名后的未读会话")
        by_id = {s.id: s for s in await store.list_recent(10)}
        assert _unread(by_id[unread_sid]), "未读会话改标题不应吞掉红点"

    asyncio.run(_run())


def test_pinned_and_search_carry_last_read_at(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        sid = (await store.create("m", source="web", mode="")).id
        await store.pin_session(sid)
        await store.save_message(sid, Message(role="assistant", content="内容含关键词"))
        await store.touch(sid)

        (p,) = await store.list_pinned()
        assert p.id == sid and _unread(p), "置顶列表应带未读状态"

        (s,) = await store.search("关键词")
        assert s.id == sid and _unread(s), "搜索结果应带未读状态"

        await store.mark_read(sid)
        (p,) = await store.list_pinned()
        assert not _unread(p)

    asyncio.run(_run())


def test_legacy_db_backfills_read(tmp_path):
    """旧版本 DB（无 last_read_at 列）：迁移后存量会话视为已读。"""

    async def _run():
        db = tmp_path / "legacy.db"
        con = sqlite3.connect(str(db))
        con.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL, source TEXT NOT NULL DEFAULT 'web', mode TEXT NOT NULL DEFAULT '')"
        )
        con.execute(
            "INSERT INTO sessions VALUES ('s_legacy', '老会话', 'm', 100.0, 200.0, 'web', '')"
        )
        con.commit()
        con.close()

        store = SessionStore(db_path=db)
        await store.init()
        (s,) = await store.list_recent(10)
        assert s.id == "s_legacy"
        assert not _unread(s), "存量会话迁移后应视为已读，避免升级后满屏红点"
        assert s.last_read_at == 200.0

    asyncio.run(_run())
