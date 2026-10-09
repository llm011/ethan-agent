r"""Tests for Ethan ACP server（ethan/acp_server/）。

覆盖：
1. mapping.py 纯映射：内容块转换、ToolEvent→ACP update（含 sessionUpdate 判别字段）、
   ToolKind/Status 映射
2. EthanACPAgent 协议层：initialize/new_session/prompt/cancel
   —— 用 FakeTransport 直发 JSON-RPC（进程内，不 spawn 子进程、不发真 LLM）
3. stdout 纪律：spawn 真子进程跑 initialize roundtrip，stdout 每行都是合法 JSON-RPC
4. ACPConsentProvider：outcome → allowed/denied 映射

背景：ACP v1 = JSON-RPC 2.0 over stdio（newline-delimited）。Multica daemon 以
custom runtime profile（protocol_family=kimi，走标准 ACP）拉起 `ethan acp`。

async 测试写法：项目未装 pytest-asyncio，统一用 asyncio.run(run()) 包装
（与 test_agent_consent_reject.py 同款）。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from acp.agent.connection import AgentSideConnection
from acp.schema import (
    AllowedOutcome,
    DeniedOutcome,
    RequestPermissionResponse,
)

from ethan.acp_server import mapping
from ethan.acp_server.server import EthanACPAgent
from ethan.providers.base import ThinkingEvent, ToolEvent

# ── mapping.py：内容块转换 ───────────────────────────────────────────


class _B:
    """轻量内容块桩（避免依赖 SDK 具体类型的构造约束）。"""

    def __init__(self, type: str, **kw: Any):
        self.type = type
        self.__dict__.update(kw)


def test_blocks_text_only():
    text, images = mapping.blocks_to_text_and_images([_B("text", text="hello"), _B("text", text="world")])
    assert text == "hello\nworld"
    assert images == []


def test_blocks_image():
    blocks = [_B("text", text="看这张图"), _B("image", data="aGk=", mime_type="image/png")]
    text, images = mapping.blocks_to_text_and_images(blocks)
    assert text == "看这张图"
    assert images == [{"data": "aGk=", "media_type": "image/png"}]


def test_blocks_unsupported_type_noted():
    text, images = mapping.blocks_to_text_and_images([_B("audio", data="xx")])
    assert "audio" in text
    assert images == []


def test_blocks_empty():
    assert mapping.blocks_to_text_and_images([]) == ("", [])


# ── mapping.py：session_update 事件构造（判别字段必须存在）────────────


def test_message_chunk_has_discriminator():
    m = mapping.message_chunk("hi")
    dumped = m.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["sessionUpdate"] == "agent_message_chunk"
    assert dumped["content"] == {"text": "hi", "type": "text"}


def test_thought_chunk_has_discriminator():
    m = mapping.thought_chunk("thinking")
    dumped = m.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["sessionUpdate"] == "agent_thought_chunk"


def test_user_chunk_has_discriminator():
    m = mapping.user_chunk("q")
    dumped = m.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["sessionUpdate"] == "user_message_chunk"


def test_tool_call_start_fields():
    m = mapping.tool_call_start("tc1", "shell", "ls -la")
    dumped = m.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["sessionUpdate"] == "tool_call"
    assert dumped["toolCallId"] == "tc1"
    assert dumped["kind"] == "execute"
    assert dumped["status"] == "in_progress"
    assert "shell" in dumped["title"] and "ls -la" in dumped["title"]


def test_tool_call_progress_done():
    m = mapping.tool_call_update("done", "tc1", "web_search", "3 results")
    dumped = m.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["sessionUpdate"] == "tool_call_update"
    assert dumped["status"] == "completed"
    # content 元素是 ContentToolCallContent 包一层：{"type": "content", "content": {...}}
    assert dumped["content"][0]["type"] == "content"
    assert dumped["content"][0]["content"]["text"] == "3 results"


def test_tool_call_progress_done_no_result():
    """无 result_preview 时 content 为空列表（exclude_none 后消失）。"""
    m = mapping.tool_call_update("done", "tc1", "shell", "")
    dumped = m.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["status"] == "completed"
    assert dumped.get("content") in (None, [])


def test_tool_call_progress_error():
    m = mapping.tool_call_update("error", "tc1", "shell", "boom")
    assert m.model_dump(mode="json", by_alias=True, exclude_none=True)["status"] == "failed"


# ── mapping.py：ToolKind 映射 ────────────────────────────────────────


@pytest.mark.parametrize(
    "tool,kind",
    [
        ("file_read", "read"),
        ("file_write", "edit"),
        ("shell", "execute"),
        ("rg_search", "search"),
        ("web_fetch", "fetch"),
        ("ask_user", "think"),
        ("deliver_file", "move"),
        ("totally_unknown_tool", "other"),
    ],
)
def test_tool_kind_mapping(tool, kind):
    assert mapping.tool_kind(tool) == kind


def test_image_blocks_from_message_images_valid_and_broken():
    """合法 base64 转换；缺 data / base64 损坏的条目跳过不抛。"""
    blocks = mapping.image_blocks_from_message_images(
        [
            {"data": "aGk=", "media_type": "image/png"},
            {"data": "", "media_type": "image/png"},
            {"data": "not!!base64", "media_type": "image/jpeg"},
        ]
    )
    assert len(blocks) == 1
    assert blocks[0].data == "aGk="
    assert blocks[0].mime_type == "image/png"


# ── 测试脚手架：FakeTransport + stub stream_chat ─────────────────────


class FakeTransport:
    """进程内 transport：记录 agent 发出的 JSON-RPC 消息 + JSON 可编码守卫。"""

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, message: dict) -> None:
        json.dumps(message)  # 任何发出去的消息必须可 JSON 编码（stdio 纪律）
        self.sent.append(message)

    async def receive(self) -> dict | None:
        return None

    async def close(self) -> None: ...


class FakeStreamAgent:
    """替换真 Agent：stream_chat 按脚本产出事件序列（不触达 LLM/网络）。"""

    def __init__(self, script: list):
        self.script = script
        self.usage = type("U", (), {"input_tokens": 0, "output_tokens": 0, "cache_tokens": 0})()
        self.session_id = ""
        self.is_owner = True

    async def stream_chat(self, messages):
        for item in self.script:
            if isinstance(item, Exception):
                raise item
            yield item


class FakeStore:
    """sessions.db 桩：记录 save_message 供断言。"""

    def __init__(self):
        self.saved: list[tuple[str, Any]] = []

    async def create_with_id(self, sid, model, source="web", mode=""):
        assert source == "acp", f"ACP 会话 source 必须是 acp，得到 {source}"

    async def load(self, sid):
        return None

    async def save_message(self, sid, msg):
        self.saved.append((sid, msg))
        return 1

    async def touch(self, sid):
        return None

    async def update_title(self, sid, title):
        return None


def _make_agent_with_script(script: list, monkeypatch) -> FakeStore:
    """patch ACPSession._make_agent 与 get_session_store，返回 FakeStore 供断言。"""
    store = FakeStore()

    async def fake_make_agent(self):
        return FakeStreamAgent(script)

    monkeypatch.setattr("ethan.acp_server.session.ACPSession._make_agent", fake_make_agent)

    async def fake_get_store():
        return store

    monkeypatch.setattr("ethan.memory.session.get_session_store", fake_get_store)
    return store


# ── EthanACPAgent 协议层（FakeTransport 直发 JSON-RPC）────────────────


def _new_server_connection() -> tuple[EthanACPAgent, AgentSideConnection, FakeTransport]:
    transport = FakeTransport()
    agent = EthanACPAgent()
    conn = AgentSideConnection(agent, transport, listening=False)
    return agent, conn, transport


def _route(conn: AgentSideConnection, method: str, params: dict) -> Any:
    """绕过 Connection，直接走 router（_execute_request 的 handler 调用路径）。"""
    return conn._conn._handler(method, params, False)


def _notify(conn: AgentSideConnection, method: str, params: dict) -> Any:
    """notification 路径（session/cancel 等无 id 消息）。"""
    return conn._conn._handler(method, params, True)


def test_initialize_roundtrip():
    async def run():
        agent, conn, _ = _new_server_connection()
        resp = await _route(conn, "initialize", {"protocolVersion": 1})
        assert resp.protocol_version == 1
        assert resp.agent_capabilities.load_session is True

    asyncio.run(run())


def test_new_session_returns_id(monkeypatch, tmp_path):
    async def run():
        _make_agent_with_script([], monkeypatch)
        agent, conn, _ = _new_server_connection()
        resp = await _route(conn, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        assert resp.session_id.startswith("s_")

    asyncio.run(run())


def test_prompt_streams_updates(monkeypatch, tmp_path):
    async def run():
        script = [
            ThinkingEvent(delta="想一下"),
            ToolEvent(tool_name="shell", args_summary="ls", state="start", tool_call_id="t1"),
            ToolEvent(tool_name="shell", args_summary="ls", state="done", result_preview="a.txt", tool_call_id="t1"),
            "答案：两个文件",
        ]
        _make_agent_with_script(script, monkeypatch)
        agent, conn, transport = _new_server_connection()
        new = await _route(conn, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        sid = new.session_id
        resp = await _route(conn, "session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "hi"}]})
        assert resp.stop_reason == "end_turn"

        updates = [m for m in transport.sent if m.get("method") == "session/update"]
        kinds = [m["params"]["update"]["sessionUpdate"] for m in updates]
        # thought → tool_call → tool_call_update → message_chunk 顺序到达
        assert kinds == ["agent_thought_chunk", "tool_call", "tool_call_update", "agent_message_chunk"]
        assert updates[3]["params"]["update"]["content"]["text"] == "答案：两个文件"

    asyncio.run(run())


def test_prompt_unknown_session_creates_implicitly(monkeypatch):
    async def run():
        _make_agent_with_script(["ok"], monkeypatch)
        agent, conn, _ = _new_server_connection()
        resp = await _route(
            conn, "session/prompt", {"sessionId": "s_manual_01", "prompt": [{"type": "text", "text": "?"}]}
        )
        assert resp.stop_reason == "end_turn"
        assert "s_manual_01" in agent._sessions

    asyncio.run(run())


def test_prompt_empty_content_short_circuits(monkeypatch, tmp_path):
    """prompt 内容块为空：直接 end_turn，不跑 agent。"""
    async def run():
        store = _make_agent_with_script(["should-not-run"], monkeypatch)
        agent, conn, _ = _new_server_connection()
        new = await _route(conn, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        resp = await _route(conn, "session/prompt", {"sessionId": new.session_id, "prompt": []})
        assert resp.stop_reason == "end_turn"
        assert store.saved == []  # agent 没跑

    asyncio.run(run())


def test_cancel_cancels_running_prompt(monkeypatch, tmp_path):
    async def run():
        started = asyncio.Event()

        class SlowAgent(FakeStreamAgent):
            async def stream_chat(self, messages):
                started.set()
                await asyncio.sleep(30)
                yield "never"

        async def fake_make_agent(self):
            return SlowAgent([])

        monkeypatch.setattr("ethan.acp_server.session.ACPSession._make_agent", fake_make_agent)
        monkeypatch.setattr(
            "ethan.memory.session.get_session_store", _fake_get_store
        )

        agent, conn, _ = _new_server_connection()
        new = await _route(conn, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        sid = new.session_id

        # prompt 在后台 task 里跑，cancel 通知应让它收到 CancelledError
        prompt_task = asyncio.create_task(
            _route(conn, "session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": "hi"}]})
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        await _notify(conn, "session/cancel", {"sessionId": sid})
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(prompt_task, timeout=5)

    asyncio.run(run())


async def _fake_get_store():
    return FakeStore()


def test_tool_call_id_fallback_for_missing_id(monkeypatch, tmp_path):
    """无 tool_call_id 的 ToolEvent（旧形态）也要能发 tool_call start/update。"""
    async def run():
        script = [
            ToolEvent(tool_name="web_search", args_summary="q", state="start"),
            ToolEvent(tool_name="web_search", args_summary="q", state="done", result_preview="r"),
        ]
        _make_agent_with_script(script, monkeypatch)
        agent, conn, transport = _new_server_connection()
        new = await _route(conn, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        await _route(
            conn, "session/prompt", {"sessionId": new.session_id, "prompt": [{"type": "text", "text": "hi"}]}
        )
        kinds = [m["params"]["update"]["sessionUpdate"] for m in transport.sent if m.get("method") == "session/update"]
        assert kinds == ["tool_call", "tool_call_update"]

    asyncio.run(run())


def test_prompt_exception_still_returns_end_turn(monkeypatch, tmp_path):
    """stream_chat 中途异常：不崩、返回 end_turn（正文已尽力推送）。"""
    async def run():
        script = ["部分输出", RuntimeError("upstream boom")]
        _make_agent_with_script(script, monkeypatch)
        agent, conn, transport = _new_server_connection()
        new = await _route(conn, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        resp = await _route(
            conn, "session/prompt", {"sessionId": new.session_id, "prompt": [{"type": "text", "text": "hi"}]}
        )
        assert resp.stop_reason == "end_turn"
        # 异常前的部分输出已流式送达
        texts = [
            m["params"]["update"]["content"]["text"]
            for m in transport.sent
            if m.get("method") == "session/update" and m["params"]["update"]["sessionUpdate"] == "agent_message_chunk"
        ]
        assert texts == ["部分输出"]

    asyncio.run(run())


def test_assistant_message_saved_after_prompt(monkeypatch, tmp_path):
    """prompt 结束后 collector.full 落库为 assistant 消息。"""
    async def run():
        store = _make_agent_with_script(["最终回复"], monkeypatch)
        agent, conn, _ = _new_server_connection()
        new = await _route(conn, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        await _route(conn, "session/prompt", {"sessionId": new.session_id, "prompt": [{"type": "text", "text": "hi"}]})
        asst = [m for _, m in store.saved if m.role == "assistant"]
        assert len(asst) == 1
        assert asst[0].content == "最终回复"

    asyncio.run(run())


# ── spawn 真子进程：stdout 纪律 + 完整 roundtrip ──────────────────────


def test_subprocess_stdout_is_pure_jsonrpc():
    """spawn `ethan acp`：initialize roundtrip，stdout 每行都是合法 JSON-RPC。"""
    async def run():
        proc = await asyncio.create_subprocess_exec(
            ".venv/bin/ethan", "acp",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            req = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": 1}}
            proc.stdin.write((json.dumps(req) + "\n").encode())
            await proc.stdin.drain()
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            data = json.loads(line)  # 非法 JSON / 空 stdout 会直接抛
            assert data["id"] == 0
            assert data["result"]["protocolVersion"] == 1
        finally:
            proc.kill()
            await proc.wait()

    asyncio.run(run())


# ── ACPConsentProvider：outcome 映射 ─────────────────────────────────


class FakeConsentConn:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls: list[dict] = []

    async def request_permission(self, session_id, tool_call, options, **kw):
        self.calls.append({"session_id": session_id, "tool_call": tool_call, "options": options})
        return self._outcome


def _make_provider(outcome):
    from ethan.acp_server.consent import ACPConsentProvider

    return ACPConsentProvider(conn=FakeConsentConn(outcome), acp_session_id="s_x", session_id="s_x")


def test_consent_allowed_once():
    async def run():
        provider = _make_provider(
            RequestPermissionResponse(outcome=AllowedOutcome(outcome="selected", option_id="approve_once"))
        )
        event, fut = provider.create("读密钥", "get_secret")
        assert await asyncio.wait_for(fut, timeout=5) is True

    asyncio.run(run())


def test_consent_allowed_session():
    async def run():
        provider = _make_provider(
            RequestPermissionResponse(outcome=AllowedOutcome(outcome="selected", option_id="approve_session"))
        )
        event, fut = provider.create("读密钥", "get_secret")
        assert await asyncio.wait_for(fut, timeout=5) is True

    asyncio.run(run())


def test_consent_denied():
    async def run():
        provider = _make_provider(RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled")))
        event, fut = provider.create("读密钥", "get_secret")
        assert await asyncio.wait_for(fut, timeout=5) is False

    asyncio.run(run())


def test_consent_always_hides_session_option():
    """高危（always=True）不给 approve_session 选项，逼 daemon 逐次放行。"""
    async def run():
        provider = _make_provider(
            RequestPermissionResponse(outcome=AllowedOutcome(outcome="selected", option_id="approve_once"))
        )
        event, fut = provider.create("rm -rf", "shell", always=True)
        await asyncio.wait_for(fut, timeout=5)
        fake = provider._conn
        kinds = [o.kind for o in fake.calls[0]["options"]]
        assert "allow_always" not in kinds

    asyncio.run(run())


def test_consent_request_error_denies():
    """conn.request_permission 抛异常（client 不支持）→ 按拒绝处理，不挂起。"""
    async def run():
        class BrokenConn:
            async def request_permission(self, **kw):
                raise RuntimeError("method not found")

        from ethan.acp_server.consent import ACPConsentProvider

        provider = ACPConsentProvider(conn=BrokenConn(), acp_session_id="s_x", session_id="s_x")
        event, fut = provider.create("读密钥", "get_secret")
        assert await asyncio.wait_for(fut, timeout=5) is False

    asyncio.run(run())


def test_consent_event_is_streamed_shape():
    """Provider 是 streamed=True：agent loop 会走 create() + await 路径。

    create() 依赖 running loop（生产中在 stream_chat 内被调），测试也须在 loop 内。"""
    async def run():
        provider = _make_provider(None)
        assert provider.streamed is True
        event, fut = provider.create("d", "t")
        assert event.request_id and event.tool == "t"
        provider.cancel_all()  # 清理未决 task

    asyncio.run(run())
