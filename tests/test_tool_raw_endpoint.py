"""Tests for GET /sessions/{id}/messages/{mid}/tool-raw — 工具原始参数/结果。

覆盖：按 index / tool_call_id 定位、args JSON 格式化、result 匹配 tool 消息、
各类 404 / 400。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.interface.routers import sessions
from ethan.memory.session import Session
from ethan.providers.base import Message, ToolCall


def _make_session() -> Session:
    return Session(
        id="s_test",
        title="t",
        model="m",
        created_at=0.0,
        updated_at=0.0,
        messages=[
            Message(role="user", content="hi", id=1),
            Message(
                role="assistant",
                content="",
                id=2,
                tool_calls=[
                    ToolCall(id="tc_1", name="shell", arguments={"cmd": "ls"}),
                    ToolCall(id="tc_2", name="web_search", arguments={"query": "x"}),
                ],
            ),
            Message(role="tool", content="a.txt\nb.txt", id=3, tool_call_id="tc_1"),
        ],
    )


@pytest.fixture()
def client(monkeypatch):
    session = _make_session()

    class FakeStore:
        async def load(self, session_id: str):
            return session if session_id == "s_test" else None

    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr(sessions, "get_session_store", fake_get_store)

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[sessions.verify_token] = lambda: "u1"
    return TestClient(app)


def test_args_by_index(client):
    res = client.get("/sessions/s_test/messages/2/tool-raw", params={"field": "args", "index": 1})
    assert res.status_code == 200
    body = res.json()
    assert '"query": "x"' in body["args"]


def test_result_by_tool_call_id(client):
    res = client.get("/sessions/s_test/messages/2/tool-raw", params={"field": "result", "tool_call_id": "tc_1"})
    assert res.status_code == 200
    assert res.json()["result"] == "a.txt\nb.txt"


def test_both_fields(client):
    res = client.get("/sessions/s_test/messages/2/tool-raw", params={"field": "both", "index": 0})
    assert res.status_code == 200
    body = res.json()
    assert '"cmd": "ls"' in body["args"]
    assert body["result"] == "a.txt\nb.txt"


def test_result_missing_tool_message_both_returns_null(client):
    res = client.get("/sessions/s_test/messages/2/tool-raw", params={"field": "both", "index": 1})
    assert res.status_code == 200
    assert res.json()["result"] is None


def test_session_not_found(client):
    assert client.get("/sessions/s_none/messages/2/tool-raw").status_code == 404


def test_message_without_tool_calls(client):
    assert client.get("/sessions/s_test/messages/1/tool-raw").status_code == 404


def test_index_out_of_range(client):
    assert client.get("/sessions/s_test/messages/2/tool-raw", params={"index": 9}).status_code == 404


def test_invalid_field(client):
    assert client.get("/sessions/s_test/messages/2/tool-raw", params={"field": "bogus"}).status_code == 400
