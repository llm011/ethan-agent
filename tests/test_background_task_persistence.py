"""后台任务持久化（计划条目 6）。

原先后台任务只存在模块级 _REGISTRY（纯内存），进程重启即丢失——侧边栏看不到历史
任务。现在落库到 sessions.db 的 background_tasks 表：
  - 创建即落库，状态变更/终态更新；
  - 启动扫描把 running 标 interrupted（daemon 线程已死）；
  - list_tasks() 合并内存与持久化历史（内存优先覆盖）。
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

from ethan.memory.session import SessionStore
from ethan.tools.builtin import background_task as bt


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


def test_background_tasks_table_created(tmp_path):
    async def _run():
        await _mk_store(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "s.db"))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='background_tasks'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "background_tasks 表未创建"

    asyncio.run(_run())


def test_upsert_and_list_roundtrip(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.create("m")
        await store.upsert_background_task(
            s.id, title="深度调研", status="running", channel="web",
            prompt="调研 X", user_id="u1", started_at=1000.0,
        )
        rec = await store.get_background_task(s.id)
        assert rec is not None
        assert rec["title"] == "深度调研"
        assert rec["status"] == "running"
        assert rec["prompt"] == "调研 X"

        # 更新为终态 + 结果
        await store.upsert_background_task(
            s.id, title="深度调研", status="done", channel="web",
            prompt="调研 X", user_id="u1", result="结论：OK",
            started_at=1000.0, ended_at=2000.0,
        )
        rec = await store.get_background_task(s.id)
        assert rec["status"] == "done"
        assert rec["result"] == "结论：OK"
        assert rec["ended_at"] == 2000.0

        tasks = await store.list_background_tasks()
        assert len(tasks) == 1
        assert tasks[0]["session_id"] == s.id

    asyncio.run(_run())


def test_startup_marks_running_as_interrupted(tmp_path):
    """模拟进程重启：重新 init 同一 DB，running 任务应被标 interrupted。"""
    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.create("m")
        await store.upsert_background_task(
            s.id, title="跑到一半", status="running", channel="web",
            prompt="p", started_at=time.time(),
        )
        # 模拟重启：新 store 对同一 db 重新 init
        store2 = SessionStore(db_path=tmp_path / "s.db")
        await store2.init()
        rec = await store2.get_background_task(s.id)
        assert rec["status"] == "interrupted", "重启后 running 任务应标 interrupted"
        assert rec["ended_at"] is not None

    asyncio.run(_run())


def test_persist_helper_writes_row(tmp_path, monkeypatch):
    """daemon 线程用的同步 _persist 能写入并更新状态。"""
    async def _setup():
        store = await _mk_store(tmp_path)
        s = await store.create("m")
        return s.id

    sid = asyncio.run(_setup())
    monkeypatch.setattr(bt, "user_sessions_db_path", lambda: tmp_path / "s.db", raising=False)
    # _persist 内部是 from ethan.core.paths import user_sessions_db_path，需 patch 源模块
    import ethan.core.paths as paths_mod
    monkeypatch.setattr(paths_mod, "user_sessions_db_path", lambda: tmp_path / "s.db")

    task = bt._BgTask(
        session_id=sid, title="同步落库", started_at=1000.0, channel="web",
        prompt="p", result="",
    )
    bt._persist(task)

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        row = conn.execute(
            "SELECT title, status FROM background_tasks WHERE session_id=?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "同步落库"
    assert row[1] == "running"

    # 终态更新
    task.status = "done"
    task.result = "结果"
    bt._persist(task, ended=True)
    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        row = conn.execute(
            "SELECT status, result, ended_at FROM background_tasks WHERE session_id=?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "done"
    assert row[1] == "结果"
    assert row[2] is not None


def test_list_tasks_merges_registry_and_persisted(tmp_path, monkeypatch):
    """list_tasks() 合并内存记录与持久化历史，内存状态覆盖同 id 历史行。"""
    async def _setup():
        store = await _mk_store(tmp_path)
        s1 = await store.create("m")
        s2 = await store.create("m")
        await store.upsert_background_task(
            s1.id, title="历史任务", status="interrupted", channel="web",
            prompt="p", started_at=1000.0,
        )
        await store.upsert_background_task(
            s2.id, title="内存任务", status="running", channel="web",
            prompt="p", started_at=2000.0,
        )
        return s1.id, s2.id

    s1, s2 = asyncio.run(_setup())
    import ethan.core.paths as paths_mod
    monkeypatch.setattr(paths_mod, "user_sessions_db_path", lambda: tmp_path / "s.db")

    # 内存里只放 s2，且状态更新为 done（覆盖历史 running）
    monkeypatch.setattr(bt, "_REGISTRY", {
        s2: bt._BgTask(session_id=s2, title="内存任务", started_at=2000.0,
                       status="done", channel="web"),
    })

    tasks = bt.list_tasks()
    by_id = {t["id"]: t for t in tasks}
    assert s1 in by_id, "持久化历史任务应出现在列表里"
    assert by_id[s1]["status"] == "interrupted"
    assert by_id[s2]["status"] == "done", "内存记录应覆盖同 id 的历史状态"
    # 按发起时间倒序
    assert tasks[0]["id"] == s2
