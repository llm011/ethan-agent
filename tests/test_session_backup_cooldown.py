"""sessions.db 备份节流与检查点撞锁重试的契约。

锁住的关键行为：
- 两次成功备份之间有最小冷却间隔，高频定时任务不会在整点连续触发全库备份
- 冷却窗口内调用被静默跳过，不产出新备份、不改动旧备份
- 运行检查点写入撞锁时会退避重试，且重试过程中不泄漏 sqlite 连接
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ethan.memory import session_backup


@pytest.fixture
def isolated_backup(monkeypatch, tmp_path):
    """把备份目录与用户库路径都指到临时目录，避免碰真实 sessions.db。"""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO sessions (id, title) VALUES ('s1', 'a')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "ethan.core.paths.user_sessions_db_path", lambda: db_path
    )
    monkeypatch.setattr(session_backup, "_last_backup_at", 0.0)
    monkeypatch.setattr(session_backup, "_timer", None)
    return db_path


def _backups(db_path: Path) -> list[Path]:
    return session_backup._list_backups(db_path.parent)


def test_backup_creates_file_and_sets_cooldown(isolated_backup):
    session_backup._do_backup()

    backups = _backups(isolated_backup)
    assert len(backups) == 1, "首次备份应产出一个备份文件"
    assert session_backup._last_backup_at > 0, "成功备份后应记录时间戳"


def test_backup_within_cooldown_is_deferred_not_dropped(isolated_backup):
    """冷却命中时这次备份必须被排到冷却结束，而不是直接丢掉。"""
    session_backup._do_backup()
    first = _backups(isolated_backup)
    assert len(first) == 1
    first_size = first[0].stat().st_size

    # 塞大 blob 让库明显变大，制造「本来会触发新备份」的条件
    # （否则「比已有备份大才备份」这条判据自己就会跳过，测不到冷却）
    conn = sqlite3.connect(isolated_backup)
    conn.execute(
        "INSERT INTO sessions (id, title) VALUES ('big', ?)", ("x" * 200_000,)
    )
    conn.commit()
    conn.close()

    try:
        session_backup._do_backup()
        # 此刻不应产出新备份
        assert len(_backups(isolated_backup)) == 1, "冷却窗口内不应立刻产出备份"
        assert _backups(isolated_backup)[0].stat().st_size == first_size, (
            "冷却窗口内不应覆盖已有备份"
        )
        # 但必须排了一个补偿性的定时器，否则这轮对话的备份就永久丢了
        assert session_backup._timer is not None, (
            "冷却命中后必须重排备份，不能直接丢弃"
        )
        assert session_backup._timer.is_alive(), "重排的定时器应处于等待状态"
    finally:
        timer = session_backup._timer
        if timer is not None:
            timer.cancel()
        session_backup._timer = None


def test_backup_resumes_after_cooldown(isolated_backup, monkeypatch):
    session_backup._do_backup()
    first = _backups(isolated_backup)
    assert len(first) == 1
    first_size = first[0].stat().st_size

    # 把时间戳往前推，模拟冷却已过期
    monkeypatch.setattr(
        session_backup, "_last_backup_at",
        session_backup._last_backup_at - session_backup._MIN_COOLDOWN_S - 1,
    )
    # 塞一个大 blob 让库明显变大（小行会被复用空页，文件尺寸不变，
    # 会让「比已有备份大才备份」的判据失真）
    conn = sqlite3.connect(isolated_backup)
    conn.execute(
        "INSERT INTO sessions (id, title) VALUES ('big', ?)", ("x" * 200_000,)
    )
    conn.commit()
    conn.close()

    session_backup._do_backup()

    # 备份文件名只精确到分钟，同一分钟内会覆盖同一个文件；
    # 这里用体积增长证明冷却过期后确实重新备份了。
    latest = _backups(isolated_backup)[-1]
    assert latest.stat().st_size > first_size, "冷却过期后应重新备份（库已变大）"


def test_checkpoint_retry_closes_every_connection(tmp_path, monkeypatch):
    """撞锁重试时每个尝试都必须关掉自己的连接，不能泄漏。

    `with sqlite3.connect(...)` 只 commit/rollback 不 close，重试循环里
    写成 with 会每次撞锁漏一个连接，长跑后会耗光文件描述符。
    """
    import asyncio
    import json

    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE run_checkpoints("
        "message_id INTEGER PRIMARY KEY, session_id TEXT, state TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages("
        "id INTEGER PRIMARY KEY, session_id TEXT, run_checkpoint TEXT)"
    )
    conn.execute("INSERT INTO messages(id, session_id) VALUES (1, 's1')")
    conn.commit()
    conn.close()

    from ethan.memory.session_checkpoints import SessionCheckpointsMixin

    opened: list[sqlite3.Connection] = []
    closed: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect
    # 前两次尝试人为抛 locked，逼出重试路径
    remaining_locks = {"n": 2}

    class TrackedConnection:
        def __init__(self, inner):
            self._inner = inner
            opened.append(self)

        def execute(self, sql, *params):
            if "INSERT INTO run_checkpoints" in sql and remaining_locks["n"] > 0:
                remaining_locks["n"] -= 1
                raise sqlite3.OperationalError("database is locked")
            return self._inner.execute(sql, *params)

        def commit(self):
            return self._inner.commit()

        def close(self):
            closed.append(self)
            return self._inner.close()

        # 对齐真实 sqlite3.Connection：with 退出只 commit，不 close。
        # 这样若生产代码写成 `with connect(...)`，本测试就能抓到连接泄漏。
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                self._inner.commit()
            else:
                self._inner.rollback()
            return False

    def fake_connect(*args, **kwargs):
        return TrackedConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(
        "ethan.memory.session_checkpoints.sqlite3.connect", fake_connect
    )

    class Store(SessionCheckpointsMixin):
        _db_path = db_path

    asyncio.run(Store().persist_run_checkpoint("s1", 1, {"step": 1}))

    assert len(opened) == 3, f"应经历 2 次失败 + 1 次成功，实际 {len(opened)}"
    assert len(closed) == len(opened), (
        f"连接必须全部关闭：打开 {len(opened)} 个，关闭 {len(closed)} 个"
    )

    row = sqlite3.connect(db_path).execute(
        "SELECT state FROM run_checkpoints WHERE message_id = 1"
    ).fetchone()
    assert json.loads(row[0]) == {"step": 1}, "重试后应成功落库"
