"""最终回复落库的 database-locked 韧性测试。

背景：sessions.db 为 DELETE journal 模式，写锁全库排他；多连接（对话 producer、
定时任务、heartbeat 各自的 store）并发写会撞 `sqlite3.OperationalError:
database is locked`。曾经最终回复落库（producers._run_generation 定稿段）无重试
无兜底，锁冲突时异常裸冒出 producer task —— run 不 finish、回复永久丢失、
进度占位行永远停在 running 态（刷新后 UI 无限转圈）。
"""

import asyncio
import sqlite3

import pytest


def test_retry_on_db_locked_succeeds_after_locks():
    """撞锁 N 次后退避重试成功：返回结果且不抛。"""
    from ethan.memory.session import retry_on_db_locked

    calls = []

    async def flaky(v):
        calls.append(v)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
        return v * 2

    async def _run():
        return await retry_on_db_locked(flaky, 21, retries=5, base_delay=0.01)

    assert asyncio.run(_run()) == 42
    assert len(calls) == 3


def test_retry_on_db_locked_non_lock_error_no_retry():
    """非锁类 OperationalError（如表不存在）不重试，直接抛出。"""
    from ethan.memory.session import retry_on_db_locked

    calls = []

    async def bad():
        calls.append(1)
        raise sqlite3.OperationalError("no such table: foo")

    async def _run():
        await retry_on_db_locked(bad, retries=5, base_delay=0.01)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        asyncio.run(_run())
    assert len(calls) == 1


def test_retry_on_db_locked_exhausts_and_raises():
    """一直撞锁：尝试 retries+1 次后抛出最后一个锁错误，不让调用方挂死。"""
    from ethan.memory.session import retry_on_db_locked

    calls = []

    async def always_locked():
        calls.append(1)
        raise sqlite3.OperationalError("database is locked")

    async def _run():
        await retry_on_db_locked(always_locked, retries=3, base_delay=0.01)

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        asyncio.run(_run())
    assert len(calls) == 4


def test_interrupt_running_messages(tmp_path):
    """只把 running 态 assistant 行标成 interrupted；completed/user 行不动，且幂等。"""
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    async def _run():
        store = SessionStore(db_path=tmp_path / "s.db")
        await store.init()
        sid = (await store.create("m", source="web", mode="")).id
        await store.save_message(sid, Message(role="user", content="hi"))
        # 模拟实时进度占位行：content 空、status=running
        await store.save_message(sid, Message(role="assistant", content="", status="running"))
        await store.save_message(sid, Message(role="assistant", content="ok", status="completed"))

        n = await store.interrupt_running_messages(sid)
        assert n == 1

        sess = await store.load(sid)
        statuses = [m.status for m in sess.messages]
        assert statuses == ["completed", "interrupted", "completed"]

        # 幂等：没有 running 行时返回 0
        assert await store.interrupt_running_messages(sid) == 0

    asyncio.run(_run())
