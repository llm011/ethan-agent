"""Automatic native-channel checkpoint lifecycle, without duplicate UI messages."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar

from ethan.core.run_checkpoint import RunCheckpointRecorder
from ethan.providers.base import Message

# Channel final save occurs in the same request context after stream iteration.
_pending_final: ContextVar[tuple | None] = ContextVar("checkpoint_pending_final", default=None)
_active_checkpoint: ContextVar[object | None] = ContextVar("active_checkpoint", default=None)


async def begin_checkpoint(agent, messages):
    if getattr(agent, "_checkpoint_callback", None) is not None or not getattr(agent, "session_id", ""):
        return None
    from ethan.memory.session import get_session_store
    store = await get_session_store()
    async with store._db.execute("SELECT 1 FROM sessions WHERE id=?", (agent.session_id,)) as cursor:
        if await cursor.fetchone() is None:
            return None  # e.g. an external transient ACP id, not a persisted session
    _pending_final.set(None)
    row_id = await store.save_message(agent.session_id, Message("assistant", "", status="running"))
    recorder = RunCheckpointRecorder(store, agent.session_id, row_id, messages)
    try:
        await recorder({"kind": "created"})
    except BaseException:
        await asyncio.shield(store.update_message_status(row_id, "interrupted"))
        raise
    agent._checkpoint_callback = recorder
    _active_checkpoint.set(recorder)
    return recorder


async def end_checkpoint(agent, recorder, status: str):
    if recorder is None:
        return
    try:
        await asyncio.shield(recorder({"kind": status, "phase": status,
                                       "messages": list(getattr(agent, "_wire_transcript", []) or [])}))
        await asyncio.shield(recorder.store.update_message_status(recorder.message_id, status))
        # If a channel doesn't save final content, durable transcript still contains
        # the final assistant. A later history load can recover it exactly.
        _pending_final.set((str(recorder.store._db_path), recorder.session_id,
                            recorder.message_id, list(getattr(agent, "_wire_transcript", []) or []), status))
    finally:
        _active_checkpoint.set(None)
        agent._checkpoint_callback = None


def attach_final_wire(db_path, session_id: str, row_id: int, message):
    pending = _pending_final.get()
    if pending is not None and pending[:3] == (str(db_path), session_id, row_id):
        message._wire_transcript = pending[3]
        assistants = [m for m in pending[3] if m.role == "assistant"]
        if assistants:
            message.reasoning = assistants[-1].reasoning
        if pending[4] != "completed":
            message.status = pending[4]


def claim_final_message(db_path, session_id: str, message):
    active = _active_checkpoint.get()
    if active is not None and message.role == "assistant" and str(active.store._db_path) == str(db_path) and active.session_id == session_id:
        message.status = "running"
        return active.message_id
    pending = _pending_final.get()
    if pending is None or message.role != "assistant":
        return None
    path, sid, row_id, wire, status = pending
    if path != str(db_path) or sid != session_id:
        return None
    message._wire_transcript = wire
    assistants = [m for m in wire if m.role == "assistant"]
    if assistants:
        message.reasoning = assistants[-1].reasoning
    if status != "completed":
        message.status = status
    return row_id


def consume_final_message(db_path, session_id: str, row_id: int):
    """Only called AFTER database commit; rollback leaves the claim retryable."""
    pending = _pending_final.get()
    if pending is not None and pending[:3] == (str(db_path), session_id, row_id):
        _pending_final.set(None)
