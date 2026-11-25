"""Crash recovery uses committed structured facts, never automatic tool replay."""
import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ethan.core.run_checkpoint import RunCheckpointRecorder, resume_context
from ethan.core.stream_collector import StreamCollector
from ethan.memory.session import SessionStore
from ethan.providers.base import Message, ThinkingEvent, ToolCall
from ethan.tools.registry import ToolExecutor, ToolRegistry


async def make_store(path):
    store = SessionStore(path)
    await store.init()
    session = await store.create("fake")
    row = await store.save_message(session.id, Message("assistant", "", status="running"))
    return store, session, row


def test_committed_prepared_survives_sigkill(tmp_path):
    # Only this child and this temp DB are touched; no daemon, network or model.
    script = '''
import asyncio, sys
from pathlib import Path
from ethan.memory.session import SessionStore
from ethan.providers.base import Message, ToolCall
from ethan.core.run_checkpoint import RunCheckpointRecorder
async def main():
    store=SessionStore(Path(sys.argv[1])); await store.init()
    s=await store.create("fake")
    row=await store.save_message(s.id,Message("assistant","",status="running"))
    c=RunCheckpointRecorder(store,s.id,row,[Message("user","test goal")])
    call=ToolCall("call-1","write",{"file_path":"artifact.txt"})
    await c({"kind":"prepared","iter":2,"messages":[Message("assistant","",tool_calls=[call],reasoning="round-2")]})
    print(s.id,row,flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
'''
    env = {**os.environ, "ETHAN_NO_WATCHDOG": "1", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path / "s.db")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        ready = child.stdout.readline().strip().split()
        assert len(ready) == 2
        sid, row = ready[0], int(ready[1])
        os.kill(child.pid, signal.SIGKILL)
        child.communicate(timeout=10)
        assert child.returncode == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

    async def verify():
        store = SessionStore(tmp_path / "s.db")
        await store.init()
        try:
            checkpoint = await store.load_run_checkpoint(row)
            assert checkpoint["goal"] == "test goal"
            assert checkpoint["iteration"] == 2
            assert checkpoint["inflight"][0]["id"] == "call-1"
            assert "禁止自动重放" in resume_context(checkpoint)
            loaded = await store.load(sid)
            assert loaded.messages[0].status == "interrupted"
            assert loaded.messages[0]._wire_transcript == []  # no invented tool result
        finally:
            await store.close()
    asyncio.run(verify())


def test_round_reasoning_and_ids_survive_real_collector_store_path(tmp_path):
    async def run():
        store, session, row = await make_store(tmp_path / "s.db")
        try:
            recorder = RunCheckpointRecorder(store, session.id, row, [Message("user", "goal")])
            wire = []
            runner = SimpleNamespace(_wire_transcript=wire)
            collector = StreamCollector().bind(runner)
            for index in range(2):
                call = ToolCall(f"call-{index}", "x", {})
                reason = f"reason-{index}"
                collector.feed(ThinkingEvent(reason))
                wire.append(Message("assistant", "", reasoning=reason, tool_calls=[call]))
                await recorder({"kind": "prepared", "iter": index + 1, "messages": wire})
                result = Message("tool", f"result-{index}", tool_call_id=call.id)
                wire.append(result)
                await recorder({"kind": "finished", "iter": index + 1, "messages": wire, "tool_call": call, "result": result})
            wire.append(Message("assistant", "done", reasoning="final-reason"))
            collector.feed("done")
            await recorder({"kind": "generation", "messages": wire})
            assert collector.reasoning == "final-reason"
            await store.update_message(row, session.id, Message("assistant", collector.full, reasoning=collector.reasoning))
            loaded = await store.load(session.id)
            restored = loaded.messages[0]._wire_transcript
            from ethan.core.agent_loop import expand_wire_history
            expanded = expand_wire_history(loaded.messages)
            assert expanded == restored
            assert [m.reasoning for m in expanded if m.role == "assistant"] == ["reason-0", "reason-1", "final-reason"]
            assert [m.tool_call_id for m in expanded if m.role == "tool"] == ["call-0", "call-1"]
            assert not (await store.load_run_checkpoint(row))["inflight"]
        finally:
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize("termination", ["completed", "error", "cancelled"])
def test_real_producer_persists_wire_and_terminal_paths(tmp_path, monkeypatch, termination):
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
            assert (await store.load_run_checkpoint(bubble.id))["phase"] == ("completed" if termination == "completed" else "interrupted")
            if termination == "completed":
                assert bubble.reasoning == "final-reason"
                # A NEW actual agent request expands DB history, not handmade history.
                async for _ in agent.stream_chat([*loaded.messages, Message("user", "continue fixture")]):
                    pass
                assert any(m.get("tool_calls") for m in provider.captured[-1])
        finally:
            await store.close()
    asyncio.run(run())


def test_nonstream_message_transcript_and_plan_artifacts(tmp_path, monkeypatch):
    import ethan.core.paths as paths
    from ethan.core.agent import Agent
    from ethan.providers._transform import to_openai_messages
    monkeypatch.setattr(paths, "user_procedures_path", lambda: tmp_path / "procedures.json")
    async def run():
        store, session, row = await make_store(tmp_path / "s.db")
        try:
            agent = Agent(tool_registry=ToolRegistry())
            async def noop(*args):
                pass
            class Provider:
                model = "fake"
                calls = 0
                async def chat(self, messages, **kwargs):
                    self.calls += 1
                    if self.calls == 1:
                        return Message("assistant", "", reasoning="nonstream-reason", tool_calls=[ToolCall("nonstream-1", "unknown_fixture", {})])
                    outgoing = to_openai_messages(messages, True, False)
                    assistant = next(m for m in outgoing if m.get("tool_calls"))
                    assert assistant["reasoning_content"] == "nonstream-reason"
                    return Message("assistant", "done", reasoning="nonstream-final")
            provider = Provider()
            agent._provider = provider
            agent._provider_for_route = lambda route: provider
            agent._select_route = lambda messages: ("full", "fixture", [], 5)
            agent._prepare_session_memory = noop
            agent._skills = None
            response = await agent.chat([Message("user", "fixture")])
            assert response._wire_transcript
            await store.update_message(row, session.id, response)
            restored = (await store.load(session.id)).messages[0]._wire_transcript
            assert restored[0].reasoning == "nonstream-reason"
            assert restored[1].tool_call_id == "nonstream-1"

            recorder = RunCheckpointRecorder(store, session.id, row, [Message("user", "goal")])
            for name, args in [("plan_write", {"steps": ["inspect", "deliver"]}),
                               ("plan_update", {"idx": 1, "status": "done", "note": "checked"}),
                               ("deliver_file", {"path": "/tmp/fixture.txt"})]:
                call = ToolCall(name, name, args)
                await recorder({"kind": "finished", "tool_call": call, "result": Message("tool", "ok", tool_call_id=name)})
            uncertain = ToolCall("uncertain", "shell", {"command": "fixture only"})
            await recorder({"kind": "started", "tool_call": uncertain})
            await recorder({"kind": "cancelled", "tool_call": uncertain})
            await recorder({"kind": "prepared", "tool_calls": [{"id": "next", "name": "x", "arguments": {}}]})
            checkpoint = await store.load_run_checkpoint(row)
            assert checkpoint["todos"][0]["status"] == "done"
            assert checkpoint["todos"][1]["status"] == "pending"
            assert checkpoint["artifacts"] == ["/tmp/fixture.txt"]
            assert checkpoint["inflight"][0]["state"] == "cancelled_uncertain"
        finally:
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize("channel", ["schedule", "heartbeat", "lark", "repl", "acp", "wechat"])
def test_automatic_native_session_checkpoint_merges_progress_and_final(tmp_path, monkeypatch, channel):
    import ethan.memory.session as sessions
    from ethan.core.checkpoint_lifecycle import begin_checkpoint, end_checkpoint
    async def run():
        store, session, old_row = await make_store(tmp_path / "s.db")
        await store.delete_message_by_id(old_row)
        async def get_store():
            return store
        monkeypatch.setattr(sessions, "get_session_store", get_store)
        agent = SimpleNamespace(session_id=session.id, _wire_transcript=[], _channel=channel)
        try:
            recorder = await begin_checkpoint(agent, [Message("user", "fixture goal")])
            assert recorder is not None
            call = ToolCall("fixture", "fixture_read", {})
            agent._wire_transcript.append(Message("assistant", "", reasoning="fixture-reason", tool_calls=[call]))
            await agent._checkpoint_callback({"kind": "prepared", "messages": agent._wire_transcript})
            progress = await store.save_message(session.id, Message("assistant", "", tool_steps=[{"tool": "fixture_read"}]))
            assert progress == recorder.message_id
            agent._wire_transcript.append(Message("tool", "ok", tool_call_id=call.id))
            await agent._checkpoint_callback({"kind": "finished", "messages": agent._wire_transcript, "tool_call": call, "result": agent._wire_transcript[-1]})
            agent._wire_transcript.append(Message("assistant", "done", reasoning="final-reason"))
            await agent._checkpoint_callback({"kind": "generation", "messages": agent._wire_transcript})
            agent._wire_transcript.append(Message("assistant", "minimal-tail", reasoning="minimal-own-reason"))
            await end_checkpoint(agent, recorder, "completed")
            await store.update_message(progress, session.id, Message("assistant", "done"))
            loaded = await store.load(session.id)
            assert len(loaded.messages) == 1
            assert loaded.messages[0].content == "done"
            assert loaded.messages[0]._wire_transcript[0].reasoning == "fixture-reason"
            assert loaded.messages[0]._wire_transcript[-1].content == "minimal-tail"
            checkpoint = await store.load_run_checkpoint(progress)
            assert checkpoint["phase"] == "completed"
            assert checkpoint["transcript"][-1]["reasoning"] == "minimal-own-reason"
        finally:
            await store.close()
    asyncio.run(run())


def test_message_wire_transaction_cannot_be_committed_by_touch(tmp_path, monkeypatch):
    async def run():
        store, session, old_row = await make_store(tmp_path / "s.db")
        await store.delete_message_by_id(old_row)
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
        task = asyncio.create_task(store.save_message(session.id, message))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            # Touch can wait on the SQLite write lock, but cannot commit the other
            # connection's message. Independent read sees no half-written state.
            touch = asyncio.create_task(store.touch(session.id))
            import sqlite3
            with sqlite3.connect(str(tmp_path / "s.db")) as reader:
                assert reader.execute("SELECT content,run_checkpoint FROM messages").fetchall() == []
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await touch
            with sqlite3.connect(str(tmp_path / "s.db")) as reader:
                assert reader.execute("SELECT content,run_checkpoint FROM messages").fetchall() == []
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure_phase", ["started", "finished"])
def test_checkpoint_failure_cancels_and_drains_sibling_tools(failure_phase):
    from ethan.tools.base import BaseTool
    from ethan.tools.registry import ToolExecutor
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        effects = []
        class Tool(BaseTool):
            name = "fixture_read"
            description = "fixture"
            parameters = {"type": "object", "properties": {"which": {"type": "string"}}}
            no_compress = True
            async def run(self, which):
                if which == "live":
                    entered.set()
                    await release.wait()
                    effects.append("live")
                return "ok"
        registry = ToolRegistry()
        registry.register(Tool())
        executor = ToolExecutor(registry)
        tracked = SimpleNamespace(tool_tasks={}, cancelled_tool_ids=set())
        executor.current_run = tracked
        async def hook(kind, call, result):
            if call.id == "fail" and kind == failure_phase:
                await entered.wait()
                raise OSError("checkpoint unavailable")
        executor.checkpoint_hook = hook
        with pytest.raises(OSError):
            await executor.execute([ToolCall("fail", "fixture_read", {"which": "fail"}),
                                    ToolCall("live", "fixture_read", {"which": "live"})])
        release.set()
        assert effects == []
        assert tracked.tool_tasks == {}
    asyncio.run(run())


def test_checkpoint_failure_prevents_tool_dispatch():
    async def run():
        executor = ToolExecutor(ToolRegistry())
        called = []
        async def fail(kind, call, result):
            raise RuntimeError("checkpoint disk failed")
        async def tool(call):
            called.append(call)
        executor.checkpoint_hook = fail
        executor._run_one = tool
        with pytest.raises(RuntimeError, match="checkpoint disk failed"):
            await executor.execute([ToolCall("x", "side_effect", {})])
        assert called == []
    asyncio.run(run())


def test_single_tool_completion_is_not_delayed_by_batch():
    async def run():
        executor = ToolExecutor(ToolRegistry())
        blocked = asyncio.Event()
        finished = asyncio.Event()
        events = []
        async def tool(call):
            if call.id == "slow":
                await blocked.wait()
            return Message("tool", "ok", tool_call_id=call.id)
        async def hook(kind, call, result):
            events.append((kind, call.id))
            if kind == "finished" and call.id == "fast":
                finished.set()
        executor._run_one = tool
        executor.checkpoint_hook = hook
        task = asyncio.create_task(executor.execute([ToolCall("slow", "x", {}), ToolCall("fast", "x", {})]))
        await asyncio.wait_for(finished.wait(), 2)
        assert not task.done()
        assert ("finished", "fast") in events
        blocked.set()
        await task
    asyncio.run(run())
