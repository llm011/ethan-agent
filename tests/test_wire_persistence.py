import asyncio

import pytest

from ethan.memory.session import SessionStore
from ethan.providers.base import Message, ToolCall
from ethan.tools.registry import ToolRegistry


async def make_store(path):
    store = SessionStore(path)
    await store.init()
    session = await store.create("fake")
    row = await store.save_message(session.id, Message("assistant", "", status="running"))
    return store, session, row


def test_real_producer_persists_wire_and_terminal_paths(tmp_path, monkeypatch):
    termination = "completed"
    import ethan.core.paths as paths
    from ethan.core.agent import Agent
    from ethan.core.run_manager import ChatRun
    from ethan.interface.routers import producers
    from ethan.providers._transform import to_openai_messages
    from ethan.providers.base import StreamChunk
    from ethan.tools.base import BaseTool

    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(paths, "user_procedures_path", lambda: tmp_path / "procedures.json")
    async def noop(*args, **kwargs):
        return None
    for name in ("_maybe_consolidate", "_maybe_generate_skill", "_maybe_regen_title", "_close_browser_sessions"):
        monkeypatch.setattr(producers, name, noop)

    class Tool(BaseTool):
        name = "fixture_read"
        description = "fixture read"
        parameters = {"type": "object", "properties": {}}
        no_compress = True
        async def run(self, **kwargs):
            return "fixture result"

    class Provider:
        model = "fake"
        calls = 0
        captured = []
        async def stream_chat(self, messages, tools=None, system=None, **kwargs):
            self.calls += 1
            outgoing = to_openai_messages(messages, True, False)
            self.captured.append(outgoing)
            # Strict fake upstream rejects incorrectly paired persisted reasoning.
            for m in outgoing:
                if m.get("tool_calls"):
                    cid = m["tool_calls"][0]["id"]
                    assert m.get("reasoning_content") == {"call-1": "reason-1", "call-2": "reason-2"}[cid]
            if self.calls == 3:
                if termination == "error":
                    raise RuntimeError("fixture provider failure")
                if termination == "cancelled":
                    raise asyncio.CancelledError()
            if self.calls <= 2:
                call = ToolCall(f"call-{self.calls}", "fixture_read", {})
                yield StreamChunk("", reasoning=f"reason-{self.calls}")
                yield StreamChunk("", tool_calls=[call], is_final=True)
            else:
                yield StreamChunk("fixture done", reasoning="final-reason", is_final=True)
        async def chat(self, *args, **kwargs):
            return Message("assistant", "fixture done")

    async def run():
        store, session, row = await make_store(tmp_path / "s.db")
        # make_store placeholder isn't used by producer, remove it first.
        await store.delete_message_by_id(row)
        try:
            registry = ToolRegistry()
            registry.register(Tool())
            agent = Agent(tool_registry=registry)
            provider = Provider()
            agent._provider = provider
            agent._select_route = lambda messages: ("full", "fixture system", [registry.get("fixture_read")], 5)
            agent._provider_for_route = lambda route: provider
            agent._prepare_session_memory = noop
            agent._skills = None
            chat_run = ChatRun(session.id)
            task = producers._run_generation(chat_run, agent, [Message("user", "fixture goal")], store, session.id)
            if termination == "cancelled":
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            loaded = await store.load(session.id)
            assert len(loaded.messages) == 1
            bubble = loaded.messages[0]
            assert bubble.status == ("completed" if termination == "completed" else "interrupted")
            wire = bubble._wire_transcript
            assert [m.reasoning for m in wire if m.tool_calls] == ["reason-1", "reason-2"]
            assert [m.tool_call_id for m in wire if m.role == "tool"] == ["call-1", "call-2"]
            if termination == "completed":
                assert bubble.reasoning == "final-reason"
                # A NEW actual agent request expands DB history, not handmade history.
                async for _ in agent.stream_chat([*loaded.messages, Message("user", "continue fixture")]):
                    pass
                assert any(m.get("tool_calls") for m in provider.captured[-1])
        finally:
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize("operation", ["save", "update"])
def test_message_wire_transaction_cannot_be_committed_by_touch(tmp_path, monkeypatch, operation):
    async def run():
        store, session, old_row = await make_store(tmp_path / "s.db")
        if operation == "save":
            await store.delete_message_by_id(old_row)
        expected_rows = [] if operation == "save" else [("", "")]
        entered = asyncio.Event()
        release = asyncio.Event()
        original = SessionStore._persist_message_wire
        async def paused(self, *args):
            entered.set()
            await release.wait()
            await original(self, *args)
        monkeypatch.setattr(SessionStore, "_persist_message_wire", paused)
        message = Message("assistant", "done")
        message._wire_transcript = [Message("assistant", "done", reasoning="wire-round")]
        task = asyncio.create_task(store.save_message(session.id, message) if operation == "save" else store.update_message(old_row, session.id, message))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            # Touch can wait on the SQLite write lock, but cannot commit the other
            # connection's message. Independent read sees no half-written state.
            touch = asyncio.create_task(store.touch(session.id))
            import sqlite3
            with sqlite3.connect(str(tmp_path / "s.db")) as reader:
                assert reader.execute("SELECT content,run_checkpoint FROM messages").fetchall() == expected_rows
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await touch
            with sqlite3.connect(str(tmp_path / "s.db")) as reader:
                assert reader.execute("SELECT content,run_checkpoint FROM messages").fetchall() == expected_rows
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await store.close()
    asyncio.run(run())
