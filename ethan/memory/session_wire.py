"""Atomic wire transcript storage, separate from aggregated UI messages."""
from __future__ import annotations

import json


class SessionWireMixin:
    async def _message_transaction(self, operation: str, *args):
        """No other singleton writer can commit a half-written message/wire pair."""
        import aiosqlite

        from ethan.memory.session import SessionStore
        class ConnectionProxy:
            def __init__(self, connection):
                self.connection = connection
            def __getattr__(self, name):
                return getattr(self.connection, name)
            async def commit(self):
                pass
        async with aiosqlite.connect(str(self._db_path), timeout=30) as connection:
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute("BEGIN IMMEDIATE")
            isolated = SessionStore(self._db_path, _singleton=True)
            isolated._db = ConnectionProxy(connection)
            isolated._transaction_owned = True
            try:
                result = await getattr(isolated, operation)(*args)
                await connection.commit()
                from ethan.core.checkpoint_lifecycle import consume_final_message
                row_id = result if operation == "save_message" else args[0]
                consume_final_message(self._db_path, args[0] if operation == "save_message" else args[1], row_id)
                return result
            except BaseException:
                await connection.rollback()
                raise


    async def _persist_message_wire(self, session_id: str, row_id: int, message) -> None:
        """Keep nonstream returned Message transcript in the same message transaction."""
        wire = getattr(message, "_wire_transcript", None)
        if wire is None:
            return
        from ethan.core.wire_transcript import wire_message
        async with self._db.execute("SELECT state FROM message_wire_transcripts WHERE message_id=?", (row_id,)) as cursor:
            existing = await cursor.fetchone()
        state = json.loads(existing[0]) if existing else {"version": 2, "phase": message.status}
        state["transcript"] = [wire_message(m) for m in wire]
        encoded = json.dumps(state, ensure_ascii=False)
        await self._db.execute(
            "INSERT INTO message_wire_transcripts(message_id,session_id,state) VALUES(?,?,?) "
            "ON CONFLICT(message_id) DO UPDATE SET state=excluded.state", (row_id, session_id, encoded)
        )


    async def load_wire_transcripts(self, session_id: str) -> dict[int, list]:
        from ethan.core.wire_transcript import complete_wire, restore_wire
        async with self._db.execute(
            "SELECT message_id,state FROM message_wire_transcripts WHERE session_id=?", (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        transcripts = {}
        for row_id, state in rows:
            try:
                raw = json.loads(state).get("transcript", [])
                transcripts[row_id] = restore_wire(complete_wire(raw))
            except (ValueError, TypeError, KeyError):
                continue
        return transcripts
