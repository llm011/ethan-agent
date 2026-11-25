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


@pytest.mark.parametrize("termination", ["completed", "error", "stopped"])
@pytest.mark.parametrize("progress", [False, True])
def test_real_producer_persists_wire_and_terminal_paths(tmp_path, monkeypatch, termination, progress):
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

    monkeypatch.setattr(producers, "_RunManager_schedule_removal", lambda *args: None)

    class Consent:
        def policy_check(self, *args):
            return None

        def cancel_all(self):
            pass

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
                if termination == "stopped":
                    # Leave partial visible text for the non-progress stop path.
                    yield StreamChunk("fixture partial")
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
            chat_run.stop_requested = termination == "stopped"
            task = producers._run_generation(
                chat_run, agent, [Message("user", "fixture goal")], store, session.id,
                consent=Consent() if progress else None,
            )
            if termination == "stopped":
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            loaded = await store.load(session.id)
            assert len(loaded.messages) == 1
            bubble = loaded.messages[0]
            assert bubble.status == {"completed": "completed", "error": "interrupted", "stopped": "stopped"}[termination]
            wire = bubble._wire_transcript
            assert [m.reasoning for m in wire if m.tool_calls] == ["reason-1", "reason-2"]
            assert [m.tool_call_id for m in wire if m.role == "tool"] == ["call-1", "call-2"]
            if termination == "completed":
                assert bubble.reasoning == "final-reason"
            # A NEW actual agent request expands DB history for every terminal path.
            async for _ in agent.stream_chat([*loaded.messages, Message("user", "continue fixture")]):
                pass
            assert any(m.get("tool_calls") for m in provider.captured[-1])
        finally:
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("retry_content", ["  recovered answer  ", ""])
def test_minimal_retry_round_survives_load_and_next_request(tmp_path, monkeypatch, streaming, retry_content):
    import ethan.core.paths as paths
    from ethan.core.agent import Agent
    from ethan.core.stream_collector import StreamCollector
    from ethan.providers.base import StreamChunk

    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(paths, "user_procedures_path", lambda: tmp_path / "procedures.json")

    async def noop(*args, **kwargs):
        pass

    class Provider:
        model = "fake"

        def __init__(self):
            self.captured = []
            self.retry_response = None

        async def chat(self, messages, tools=None, system=None, **kwargs):
            self.captured.append(list(messages))
            if system.startswith("请用中文简洁回答"):
                self.retry_response = Message("assistant", retry_content, reasoning="retry-own-reasoning")
                return self.retry_response
            return Message("assistant", "", reasoning="empty-round-reasoning")

        async def stream_chat(self, messages, **kwargs):
            self.captured.append(list(messages))
            yield StreamChunk("", reasoning="empty-round-reasoning", is_final=True)

    async def run():
        store = SessionStore(tmp_path / "s.db")
        await store.init()
        session = await store.create("fake")
        try:
            agent = Agent(tool_registry=ToolRegistry())
            provider = Provider()
            agent._provider = provider
            agent._select_route = lambda messages: ("full", "fixture system", [], 1)
            agent._provider_for_route = lambda route: provider
            agent._prepare_session_memory = noop
            agent._skills = None
            initial = [Message("user", "fixture goal")]
            if streaming:
                collector = StreamCollector().bind(agent)
                async for item in agent.stream_chat(initial):
                    collector.feed(item)
                bubble = Message("assistant", collector.full, reasoning=collector.reasoning)
                bubble._wire_transcript = collector.wire_transcript
            else:
                bubble = await agent.chat(initial)
            expected = retry_content.strip() if retry_content else bubble.content
            assert bubble.content == expected
            assert expected
            assert any(message is provider.retry_response for message in bubble._wire_transcript)
            await store.save_message(session.id, bubble)
            loaded = await store.load(session.id)
            wire = loaded.messages[0]._wire_transcript
            assert any(m.content == retry_content and m.reasoning == "retry-own-reasoning" for m in wire)
            if not retry_content:
                assert wire[-1].content == expected
            next_messages = [*loaded.messages, Message("user", "continue fixture")]
            first_request = len(provider.captured)
            if streaming:
                async for _ in agent.stream_chat(next_messages):
                    pass
            else:
                await agent.chat(next_messages)
            outgoing = provider.captured[first_request]
            assert any(m.content.strip() == expected for m in outgoing)
            assert any(m.content == retry_content and m.reasoning == "retry-own-reasoning" for m in outgoing)
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
