"""内联图片卡片迁移：存量 base64 卡片落盘为资产文件路径。

背景：历史上 file_read 把整张图的 base64 内联进卡片 url，写入 messages.cards /
tool_steps 后单条会话响应可达数 MB，前端点开会话要等好几秒。
_migrate_inline_image_cards 在启动时把这些 data URI 落盘，卡片只留相对路径。

不变量：
- 迁移后卡片 url 指向真实存在的资产文件
- 幂等：重复 init 不再产生写入，也不重复落盘
- 解析失败 / 落盘失败时保留原卡片，绝不丢数据
"""

import asyncio
import base64
import json
import sqlite3
import time

from ethan.memory.session import SessionStore

# 1x1 PNG 头 + 填充，撑到 2048 字节以上。
# 迁移有 LENGTH(cards) > 2048 的扫描门槛（避免每次启动全表扫），
# 所以测试数据必须像真实截图那样"体积可观"，否则会被有意跳过。
_PNG_HEAD = b"\x89PNG\r\n\x1a\n"
_PNG_B64 = base64.b64encode(_PNG_HEAD + b"0" * 6000).decode("ascii")
_DATA_URI = "data:image/png;base64," + _PNG_B64


def _count_data_uris(db_path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        n = 0
        for cards, steps in conn.execute("SELECT cards, tool_steps FROM messages"):
            for blob in (cards, steps):
                if blob:
                    n += blob.count("data:image/png;base64,")
        return n
    finally:
        conn.close()


def _insert_legacy_message(db_path, sid: str, cards, tool_steps=None):
    """直接写库，模拟历史遗留的内联 base64 卡片。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (id, title, model, created_at, updated_at, source, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "legacy", "m", time.time(), time.time(), "web", ""),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, cards, tool_steps) VALUES (?, ?, ?, ?, ?)",
            (sid, "assistant", "hi", json.dumps(cards), json.dumps(tool_steps) if tool_steps else None),
        )
        conn.commit()
    finally:
        conn.close()


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


async def _seed(tmp_path, sid, cards, tool_steps=None):
    """先建库（跑完 init 迁移），关闭连接后再写历史数据，避免连接互锁。"""
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    await store.close()
    _insert_legacy_message(tmp_path / "s.db", sid, cards, tool_steps)


def test_inline_card_in_cards_is_migrated(tmp_path):
    async def _run():
        db_path = tmp_path / "s.db"
        await _seed(
            tmp_path, "s_legacy_cards",
            [{"type": "image", "title": "a.png", "url": _DATA_URI, "local_path": ""}],
        )

        # 重新 init 触发迁移
        store2 = await _mk_store(tmp_path)
        conn = sqlite3.connect(db_path)
        try:
            cards = json.loads(conn.execute(
                "SELECT cards FROM messages WHERE session_id='s_legacy_cards'"
            ).fetchone()[0])
        finally:
            conn.close()
        await store2.close()

        url = cards[0]["url"]
        assert url.startswith("assets/images/"), f"应为资产路径，实际 {url!r}"
        assert not url.startswith("data:")

        # 文件真实存在
        from ethan.core.assets import image_file_path
        assert image_file_path(url[len("assets/images/"):]).is_file()

        # 库里不再有内联 base64
        assert _count_data_uris(db_path) == 0

    asyncio.run(_run())


def test_inline_card_in_tool_steps_is_migrated(tmp_path):
    async def _run():
        db_path = tmp_path / "s.db"
        step = {"tool": "file_read", "state": "done",
                "cards": [{"type": "image", "url": _DATA_URI}]}
        # tool_steps 的扫描门槛是 8192 字节，真实历史行往往还带 thought 等字段
        step["thought"] = "x" * 9000
        await _seed(tmp_path, "s_legacy_steps", [{"type": "x"}], [step])

        store2 = await _mk_store(tmp_path)
        conn = sqlite3.connect(db_path)
        try:
            steps = json.loads(conn.execute(
                "SELECT tool_steps FROM messages WHERE session_id='s_legacy_steps'"
            ).fetchone()[0])
        finally:
            conn.close()
        await store2.close()

        assert steps[0]["cards"][0]["url"].startswith("assets/images/")
        assert _count_data_uris(db_path) == 0

    asyncio.run(_run())


def test_migration_is_idempotent(tmp_path):
    async def _run():
        db_path = tmp_path / "s.db"
        await _seed(tmp_path, "s_idem", [{"type": "image", "url": _DATA_URI}])

        store2 = await _mk_store(tmp_path)
        await store2.close()
        size_after_first = db_path.stat().st_size

        # 再跑两次不应产生任何变化
        store3 = await _mk_store(tmp_path)
        await store3.close()
        store4 = await _mk_store(tmp_path)
        await store4.close()

        assert db_path.stat().st_size == size_after_first, "重复 init 不应再写入"
        assert _count_data_uris(db_path) == 0

    asyncio.run(_run())


def test_non_data_uri_cards_are_untouched(tmp_path):
    """普通卡片（外链 / 搜索 / 已落盘路径）必须原样保留。"""
    async def _run():
        db_path = tmp_path / "s.db"
        original = [
            {"type": "search_result", "title": "t", "url": "https://example.com"},
            {"type": "image", "url": "assets/images/s_1/existing.png"},
        ]
        await _seed(tmp_path, "s_plain", original)

        store2 = await _mk_store(tmp_path)
        conn = sqlite3.connect(db_path)
        try:
            cards = json.loads(conn.execute(
                "SELECT cards FROM messages WHERE session_id='s_plain'"
            ).fetchone()[0])
        finally:
            conn.close()
        await store2.close()

        assert cards == original

    asyncio.run(_run())


def test_no_cards_table_rows_are_safe(tmp_path):
    """空库 / 无 cards 的行不会让迁移报错。"""
    async def _run():
        store = await _mk_store(tmp_path)
        sid = (await store.create("m", source="web", mode="")).id
        await store.close()
        # 再 init 一次不应抛错
        store2 = await _mk_store(tmp_path)
        await store2.close()
        assert sid

    asyncio.run(_run())
