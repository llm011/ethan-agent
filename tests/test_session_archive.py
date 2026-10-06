"""会话归档（设置 → 数据管理）的契约。

锁住的关键行为：
- N 天前的未置顶会话被快照进 archive/ 的独立 db（sessions.{start}~{end}.db
  命名，恢复功能靠文件名解析时间范围），并从主库删除
- 置顶会话永不归档（用户显式「保留在手边」）
- 归档库 schema 与主库一致，恢复时可直接并库
- days 只允许 30/90/180 三档（挡住 days=0 误删全库）
- 无命中时不产出空文件
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.interface.routers import sessions as sessions_mod
from ethan.interface.routers.deps import verify_token
from ethan.memory.session import SessionStore
from ethan.memory.session_archive import (
    archive_old_sessions,
    list_archives,
    preview_archive,
)
from ethan.providers.base import Message


@pytest.fixture()
def store(tmp_path, monkeypatch):
    s = SessionStore(db_path=tmp_path / "sessions.db")

    async def _init():
        await s.init()

    asyncio.run(_init())

    async def _fake_store():
        return s

    monkeypatch.setattr(sessions_mod, "get_session_store", _fake_store)
    monkeypatch.setattr("ethan.core.paths.user_session_archive_dir",
                        lambda: tmp_path / "archive")
    yield s
    asyncio.run(s.close())


@pytest.fixture()
def client(store):
    app = FastAPI()
    app.include_router(sessions_mod.router)
    app.dependency_overrides[verify_token] = lambda: ""
    return TestClient(app, raise_server_exceptions=False)


def _mk_session(store, sid: str, n_msgs: int = 2, updated_at: float | None = None,
                pinned_at: float = 0.0):
    """建会话 + n 条消息，可选改 updated_at（做旧）和置顶。"""
    async def _run():
        await store.create_with_id(sid, model="m", source="web", mode="")
        for i in range(n_msgs):
            await store.save_message(sid, Message(role="user", content=f"{sid}-m{i}"))
        if updated_at is not None:
            await store._db.execute(
                "UPDATE sessions SET created_at=?, updated_at=? WHERE id=?",
                (updated_at - 3600, updated_at, sid),
            )
        if pinned_at:
            await store._db.execute(
                "UPDATE sessions SET pinned_at=? WHERE id=?", (pinned_at, sid)
            )
        await store._db.commit()

    asyncio.run(_run())


def test_preview_counts_only_old_unpinned(store):
    now = time.time()
    old_ts = now - 40 * 86400
    _mk_session(store, "old1", updated_at=old_ts)
    _mk_session(store, "old2", updated_at=old_ts)
    _mk_session(store, "pinned-old", updated_at=old_ts, pinned_at=now)
    _mk_session(store, "fresh", updated_at=now)

    pv = asyncio.run(preview_archive(store, 30))
    assert pv["session_count"] == 2
    assert pv["message_count"] == 4  # 2 个会话 × 2 条消息
    assert pv["oldest_date"] and pv["newest_date"]
    assert pv["days"] == 30

    # 半年档位下连 40 天前的也算「新」
    pv180 = asyncio.run(preview_archive(store, 180))
    assert pv180["session_count"] == 0


def test_archive_moves_old_sessions_and_keeps_new_and_pinned(store, tmp_path):
    now = time.time()
    old_ts = now - 100 * 86400
    _mk_session(store, "old1", updated_at=old_ts)
    _mk_session(store, "old2", updated_at=now - 95 * 86400)
    _mk_session(store, "pinned-old", updated_at=old_ts, pinned_at=now)
    _mk_session(store, "fresh", updated_at=now)

    result = asyncio.run(archive_old_sessions(store, 90))
    assert result["archived_sessions"] == 2
    assert result["archived_messages"] == 4
    assert result["start_date"] and "~" in result["archive_file"]
    # 文件名带时间范围，恢复功能据此展示「多久前的备份」
    assert result["archive_file"] == f"sessions.{result['start_date']}~{result['end_date']}.db"

    # 主库只剩 未过期 + 置顶
    async def _remaining():
        async with store._db.execute("SELECT id FROM sessions ORDER BY id") as cur:
            return [r[0] for r in await cur.fetchall()]

    assert asyncio.run(_remaining()) == ["fresh", "pinned-old"]

    # 归档库里有且仅有旧会话，消息随行，schema 可读
    arch_db = tmp_path / "archive" / result["archive_file"]
    assert arch_db.exists()
    conn = sqlite3.connect(str(arch_db))
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM sessions ORDER BY id")]
        assert ids == ["old1", "old2"]
        n_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert n_msgs == 4
    finally:
        conn.close()


def test_archive_with_no_hits_produces_no_file(store):
    _mk_session(store, "fresh", updated_at=time.time())
    result = asyncio.run(archive_old_sessions(store, 90))
    assert result["archived_sessions"] == 0
    assert result["archive_file"] is None
    assert list(list_archives()) == []


def test_invalid_days_rejected(store):
    with pytest.raises(ValueError):
        asyncio.run(archive_old_sessions(store, 0))
    with pytest.raises(ValueError):
        asyncio.run(preview_archive(store, 7))


def test_router_archive_endpoints(client, store, tmp_path):
    now = time.time()
    _mk_session(store, "old1", updated_at=now - 200 * 86400)
    _mk_session(store, "fresh", updated_at=now)

    # 预览
    res = client.get("/sessions/archive/preview", params={"days": 180})
    assert res.status_code == 200
    assert res.json()["session_count"] == 1

    # days 非法 → 400（而不是把全库清了）
    res = client.get("/sessions/archive/preview", params={"days": 1})
    assert res.status_code == 400
    res = client.post("/sessions/archive/run", json={"days": 0})
    assert res.status_code == 400

    # 执行
    res = client.post("/sessions/archive/run", json={"days": 180})
    assert res.status_code == 200
    body = res.json()
    assert body["archived_sessions"] == 1

    # 列表端点能看到归档文件（恢复功能/设置页共用）
    res = client.get("/sessions/archives")
    assert res.status_code == 200
    archives = res.json()["archives"]
    assert len(archives) == 1
    assert archives[0]["file"] == body["archive_file"]
    assert archives[0]["start_date"] == body["start_date"]
    assert archives[0]["size_bytes"] > 0

    # 主库会话列表不再含已归档会话
    res = client.get("/sessions")
    ids = [s["id"] for s in res.json()["sessions"]]
    assert "old1" not in ids


def test_archive_failure_rolls_back_partial_main_db_deletes(store, tmp_path):
    """第 3 步主库删除中途失败：隐式事务必须回滚，消息不能被部分删掉。

    回归背景：except 里若不 rollback，挂着的未提交事务会被常驻服务后续任意
    一次写库 commit 连带提交——部分删除落定、tmp 快照又被清理，等于真丢数据。
    """
    now = time.time()
    old_ts = now - 100 * 86400
    _mk_session(store, "old1", n_msgs=3, updated_at=old_ts)
    _mk_session(store, "fresh", updated_at=now)

    real_db = store._db

    class _FailOnBlobDelete:
        """包一层真实连接：DELETE message_intermediate_blobs 时抛错，模拟中途失败。"""

        def __getattr__(self, name):
            return getattr(real_db, name)

        async def execute(self, sql, *args, **kwargs):
            if "DELETE FROM message_intermediate_blobs" in sql:
                raise RuntimeError("simulated mid-archive failure")
            return await real_db.execute(sql, *args, **kwargs)

    store._db = _FailOnBlobDelete()
    with pytest.raises(RuntimeError, match="simulated"):
        asyncio.run(archive_old_sessions(store, 90))
    store._db = real_db

    # 回滚生效：旧会话与全部消息仍在主库（未提交的部分删除被撤销）
    async def _count():
        async with real_db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id='old1'"
        ) as cur:
            return (await cur.fetchone())[0]

    assert asyncio.run(_count()) == 3

    # 后续一次无关写库 commit 也不会把「幽灵删除」带出来
    _mk_session(store, "fresh2", updated_at=now)
    assert asyncio.run(_count()) == 3

    # tmp 快照已清理、没有产出归档文件
    assert list(list_archives()) == []
    assert not any(p.name.startswith(".archive-tmp-") for p in (tmp_path / "archive").iterdir())
