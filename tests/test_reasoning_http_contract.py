"""Offline real HTTP/SDK contract, never official live acceptance."""
import asyncio

import pytest

from ethan.providers.base import Message, ToolCall, ToolDefinition
from tests.thinking_http_fixture import FINAL_REASON, REASONS, local_provider, strict_peer

TOOLS = [ToolDefinition("fixture_read", "synthetic read", {"type": "object", "properties": {}})]


@pytest.mark.parametrize("transport", ["chat", "stream"])
@pytest.mark.parametrize("final_reason", [FINAL_REASON, ""])
def test_producer_sqlite_next_actual_http(tmp_path, monkeypatch, transport, final_reason):
    """Actual stream producer persists; new Agent/provider reopens and uses chat AND SSE."""
    from ethan.core.agent import Agent
    from ethan.core.run_manager import ChatRun
    from ethan.interface.routers import producers
    from ethan.memory.session import SessionStore
    from ethan.tools.base import BaseTool
    from ethan.tools.registry import ToolRegistry

    async def noop(*args, **kwargs):
        pass

    for name in ("_maybe_consolidate", "_maybe_generate_skill", "_maybe_regen_title", "_close_browser_sessions"):
        monkeypatch.setattr(producers, name, noop)
    monkeypatch.setattr(producers, "_RunManager_schedule_removal", lambda *args: None)
    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path / "data"))
    import ethan.core.paths as paths
    monkeypatch.setattr(paths, "user_procedures_path", lambda: tmp_path / "procedures.json")

    class Tool(BaseTool):
        name = "fixture_read"
        description = "synthetic read"
        parameters = {"type": "object", "properties": {}}
        no_compress = True

        async def run(self, **kwargs):
            return "fixture result"

    def agent_for(provider):
        registry = ToolRegistry()
        registry.register(Tool())
        agent = Agent(tool_registry=registry)
        agent._provider = provider
        agent._select_route = lambda messages: ("full", "fixture system", [registry.get("fixture_read")], 5)
        agent._provider_for_route = lambda route: provider
        agent._prepare_session_memory = noop
        agent._skills = None
        # Normal nonempty check remains real; any actual fallback is forbidden.
        async def forbidden(*args, **kwargs):
            raise AssertionError("fixture fallback forbidden")
        agent._minimal_retry = forbidden
        agent._get_timeout_fallback = lambda *args: (_ for _ in ()).throw(AssertionError("fallback forbidden"))
        return agent

    async def run(peer, transport, final_reason):
        path = tmp_path / f"{transport}-{bool(final_reason)}.db"
        store = SessionStore(path)
        await store.init()
        session = await store.create("deepseek-flash")
        provider = await local_provider(peer)
        try:
            await asyncio.wait_for(producers._run_generation(
                ChatRun(session.id), agent_for(provider), [Message("user", "synthetic fixture goal")],
                store, session.id), 10)
            assert peer.accepted == 3 and peer.rejected == 0
        finally:
            await provider._client.close()
            await store.close()
        # Close/reopen both SQLite and SDK/provider: no in-memory transcript shortcut.
        store = SessionStore(path)
        await store.init()
        provider = await local_provider(peer)
        try:
            loaded = await store.load(session.id)
            assert len(loaded.messages) == 1
            assert loaded.messages[0].status == "completed"
            wire = loaded.messages[0]._wire_transcript
            assert [m.reasoning for m in wire if m.tool_calls] == REASONS
            assert [m.tool_call_id for m in wire if m.role == "tool"] == ["call-1", "call-2"]
            assert wire[-1].reasoning == (final_reason or None)
            next_agent = agent_for(provider)
            history = [*loaded.messages, Message("user", "continue synthetic fixture")]
            if transport == "chat":
                await asyncio.wait_for(next_agent.chat(history), 10)
            else:
                async def consume():
                    async for _ in next_agent.stream_chat(history):
                        pass
                await asyncio.wait_for(consume(), 10)
            assert peer.accepted == peer.requests == 4
            assert peer.rejected == 0
            assert peer.streaming == [True, True, True, transport == "stream"]
        finally:
            await provider._client.close()
            await store.close()

    with strict_peer(final_reason) as peer:
        asyncio.run(run(peer, transport, final_reason))


@pytest.fixture(autouse=True)
def no_connect_retries(monkeypatch):
    import ethan.providers.openai_compat as module
    monkeypatch.setattr(module, "_MAX_CONNECT_RETRIES", 0)
    monkeypatch.setattr(module, "_MAX_TIMEOUT_RETRIES", 0)
    monkeypatch.setattr(module, "_MAX_STREAM_BREAK_RETRIES", 0)


def history_and_expected(peer):
    history = [Message("user", "synthetic fixture")]
    for index, reason in enumerate(REASONS, 1):
        history.extend([Message("assistant", "", reasoning=reason,
                                tool_calls=[ToolCall(f"call-{index}", "fixture_read", {})]),
                        Message("tool", "fixture result", tool_call_id=f"call-{index}")])
        peer.expected.append({"role": "assistant", "content": None, "reasoning_content": reason,
                              "tool_calls": [{"id": f"call-{index}", "type": "function",
                                              "function": {"name": "fixture_read", "arguments": "{}"}}]})
    return history


@pytest.mark.parametrize("transport", ["chat", "stream"])
@pytest.mark.parametrize("mutation", ["drop", "swap", "truncate"])
def test_strict_raw_http_rejects_reasoning_mutations(transport, mutation):
    from openai import BadRequestError

    async def run(peer):
        history = history_and_expected(peer)
        provider = await local_provider(peer, mutation=mutation)
        try:
            with pytest.raises(BadRequestError) as error:
                if transport == "chat":
                    await provider.chat(history, tools=TOOLS)
                else:
                    async for _ in provider.stream_chat(history, tools=TOOLS):
                        pass
            assert error.value.status_code == 400
            assert peer.requests == peer.rejected == 1
            assert peer.accepted == 0
        finally:
            await provider._client.close()

    with strict_peer() as peer:
        asyncio.run(run(peer))


@pytest.mark.parametrize("transport", ["chat", "stream"])
@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-pro"])
def test_empty_second_tool_round_keeps_earlier_reasoning(transport, model):
    async def run(peer):
        history = history_and_expected(peer)
        history[-2].reasoning = None
        peer.expected[-1]["reasoning_content"] = ""
        provider = await local_provider(peer, model=model)
        try:
            if transport == "chat":
                await provider.chat(history, tools=TOOLS)
            else:
                async for _ in provider.stream_chat(history, tools=TOOLS):
                    pass
            assert peer.accepted == peer.requests == 1
            assert peer.rejected == 0
        finally:
            await provider._client.close()
    with strict_peer() as peer:
        asyncio.run(run(peer))


@pytest.mark.parametrize("base_url,model", [
    ("https://relay.test/v1", "deepseek-flash"),
    ("https://evil.deepseek.com", "deepseek-flash"),
    ("https://api.deepseek.com.evil.test", "deepseek-flash"),
    ("https://api.deepseek.com", "gpt-4o"),
    ("https://api.deepseek.com", "deepseek-future-unknown"),
])
def test_unknown_endpoint_or_non_deepseek_model_keeps_legacy_gate(base_url, model):
    """No new unknown gateway forwarding and no mixed-model pollution."""
    async def run(peer):
        provider = await local_provider(peer, base_url=base_url, model=model)
        try:
            history = [Message("assistant", "old", reasoning=REASONS[0]),
                       Message("assistant", "plain")]
            # Capture serialization policy without issuing a request to any endpoint.
            assert provider._include_reasoning(history, TOOLS) is False
            assert provider._include_reasoning(history, None) is False
            assert provider._include_reasoning([Message("assistant", "plain")], TOOLS) is False
        finally:
            await provider._client.close()
    with strict_peer() as peer:
        asyncio.run(run(peer))
