"""Run checkpoint transactions, isolated from shared aiosqlite connection commits."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from .session_wire import SessionWireMixin


class SessionCheckpointsMixin(SessionWireMixin):


    async def persist_run_checkpoint(self, session_id: str, row_id: int, checkpoint: dict) -> None:
        # A short dedicated connection avoids interleaving execute/commit with
        # schedule attribution or another coroutine on the singleton connection.
        encoded = json.dumps(checkpoint, ensure_ascii=False)
        def persist():
            with sqlite3.connect(str(self._db_path), timeout=30) as db:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute(
                    "INSERT INTO run_checkpoints(message_id,session_id,state) VALUES(?,?,?) "
                    "ON CONFLICT(message_id) DO UPDATE SET state=excluded.state",
                    (row_id, session_id, encoded),
                )
                db.execute("UPDATE messages SET run_checkpoint=? WHERE id=? AND session_id=?", (encoded, row_id, session_id))
        await asyncio.to_thread(persist)


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
