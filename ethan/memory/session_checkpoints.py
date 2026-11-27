"""Run checkpoint transactions, isolated from shared aiosqlite connection commits."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time

from .session_wire import SessionWireMixin


class SessionCheckpointsMixin(SessionWireMixin):


    async def persist_run_checkpoint(self, session_id: str, row_id: int, checkpoint: dict) -> None:
        # A short dedicated connection avoids interleaving execute/commit with
        # schedule attribution or another coroutine on the singleton connection.
        encoded = json.dumps(checkpoint, ensure_ascii=False)
        def persist():
            # 每次尝试的 busy_timeout 必须小，否则 retry 会把「一次 30s」放大成
            # 几分钟：每次尝试各自等满 timeout，最坏 5×30s+退避 ≈ 154s，而这些
            # 时间全占着共享的 asyncio 默认线程池（本机 14 个 worker），并发撞锁
            # 时会拖住无关的 to_thread 调用（读文件、加载 skill）。
            # 这里用「总预算」约束：单次 5s，整体不超过 _TOTAL_BUDGET_S。
            per_attempt_timeout = 5.0
            total_budget = 15.0
            deadline = time.monotonic() + total_budget
            delay = 0.3
            while True:
                # `with sqlite3.connect(...)` 只负责 commit/rollback，不会关闭连接；
                # 重试循环里必须显式 close，否则每次撞锁都泄漏一个连接。
                db = sqlite3.connect(str(self._db_path), timeout=per_attempt_timeout)
                try:
                    db.execute("PRAGMA foreign_keys=ON")
                    db.execute(
                        "INSERT INTO run_checkpoints(message_id,session_id,state) VALUES(?,?,?) "
                        "ON CONFLICT(message_id) DO UPDATE SET state=excluded.state",
                        (row_id, session_id, encoded),
                    )
                    db.execute("UPDATE messages SET run_checkpoint=? WHERE id=? AND session_id=?", (encoded, row_id, session_id))
                    db.commit()
                    return
                except sqlite3.OperationalError as e:
                    msg = str(e).lower()
                    if "locked" not in msg and "busy" not in msg:
                        raise
                    # 预算必须把「下一次尝试自身的 busy_timeout」也算进去，
                    # 否则最后一次尝试仍可超预算跑满 per_attempt_timeout。
                    if time.monotonic() + delay + per_attempt_timeout >= deadline:
                        raise  # 预算用完，交给调用方按原有的失败路径处理
                    time.sleep(delay)
                    delay = min(delay * 2, 2.0)
                finally:
                    db.close()
        await asyncio.to_thread(persist)


    async def save_schedule_message(self, session_id: str, message, progress_id: int | None,
                                    job_id: str, user_id: str) -> int:
        """Commit assistant message and exact schedule attribution together."""
        import aiosqlite

        from ethan.memory.session import SessionStore

        class TransactionConnection:
            def __init__(self, connection):
                self.connection = connection
            def __getattr__(self, name):
                return getattr(self.connection, name)
            async def commit(self):
                pass  # existing message helpers cannot commit this transaction

        async with aiosqlite.connect(str(self._db_path), timeout=30) as connection:
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute("BEGIN IMMEDIATE")
            isolated = SessionStore(self._db_path, _singleton=True)
            isolated._db = TransactionConnection(connection)
            isolated._transaction_owned = True
            try:
                if progress_id is None:
                    row_id = await isolated.save_message(session_id, message)
                else:
                    await isolated.update_message(progress_id, session_id, message)
                    row_id = progress_id
                await connection.execute(
                    "CREATE TABLE IF NOT EXISTS schedule_message_attribution ("
                    "message_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, "
                    "job_id TEXT NOT NULL, user_id TEXT NOT NULL, "
                    "FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE, "
                    "FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE)"
                )
                cursor = await connection.execute(
                    "SELECT session_id,job_id,user_id FROM schedule_message_attribution WHERE message_id=?", (row_id,)
                )
                existing = await cursor.fetchone()
                await cursor.close()
                if existing and tuple(existing) != (session_id, job_id, user_id):
                    raise ValueError("Schedule message attribution is immutable")
                await connection.execute(
                    "INSERT OR IGNORE INTO schedule_message_attribution(message_id,session_id,job_id,user_id) VALUES(?,?,?,?)",
                    (row_id, session_id, job_id, user_id),
                )
                await connection.execute("CREATE INDEX IF NOT EXISTS idx_schedule_cost_job ON schedule_message_attribution(user_id,job_id)")
                import time
                await connection.execute("UPDATE sessions SET updated_at=? WHERE id=?", (time.time(), session_id))
                await connection.commit()
                from ethan.core.checkpoint_lifecycle import consume_final_message
                consume_final_message(self._db_path, session_id, row_id)
                return row_id
            except BaseException:
                await connection.rollback()
                raise

    async def load_wire_transcripts(self, session_id: str) -> dict[int, list]:
        from ethan.core.run_checkpoint import complete_wire, restore_wire
        async with self._db.execute(
            "SELECT message_id,state FROM run_checkpoints WHERE session_id=?", (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        transcripts = await super().load_wire_transcripts(session_id)
        for row_id, state in rows:
            if row_id in transcripts:
                continue  # Final message wire includes minimal/fallback rounds after the last loop hook.
            try:
                raw = json.loads(state).get("transcript", [])
                transcripts[row_id] = restore_wire(complete_wire(raw))
            except (ValueError, TypeError, KeyError):
                continue
        return transcripts
