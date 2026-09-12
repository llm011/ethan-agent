"""用户消息「先落库再建 agent」的韧性测试。

背景（用户反馈）：回复失败时，连自己刚发的 query 都找不回来了。
根因：/chat 里用户消息的持久化原本在 `try` 块内、且在 create_agent 之后，
provider 未配置 api_key / model 非法等「建 agent 失败」的场景下，用户消息
根本没进库；前端刷新后从后端拉消息列表，那条 query 就消失了。

修复后：用户消息在 create_agent 之前独立落库，落库失败也不阻断生成。
本测试直接跑真实的 chat 路由（store 指向临时 db），把 create_agent 打桩成
抛异常，断言用户消息仍在 session 的 messages 里。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.interface.routers import chat as chat_mod
from ethan.interface.routers.deps import verify_token
from ethan.memory.session import SessionStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """把 get_session_store 打桩成指向临时 db 的 store。"""
    s = SessionStore(db_path=tmp_path / "sessions.db")

    async def _init():
        await s.init()

    asyncio.run(_init())

    import ethan.interface.routers.chat as cm
    import ethan.memory.session as sess_mod

    async def _fake_store():
        return s

    monkeypatch.setattr(cm, "get_session_store", _fake_store)
    monkeypatch.setattr(sess_mod, "get_session_store", _fake_store)
    yield s
    asyncio.run(s.close())


@pytest.fixture()
def client(store, monkeypatch):
    """只挂 chat 路由的最小 app：跳过鉴权，create_agent 打桩为抛错。"""
    def _boom(*a, **kw):
        raise RuntimeError("provider not configured: missing api_key")

    # chat.py 里是 `from .deps import create_agent`，打桩其模块命名空间即可
    monkeypatch.setattr(chat_mod, "create_agent", _boom)

    app = FastAPI()
    app.include_router(chat_mod.router)
    app.dependency_overrides[verify_token] = lambda: ""
    return TestClient(app, raise_server_exceptions=False)


def _load_messages(store, sid):
    session = asyncio.run(store.load(sid))
    return session.messages if session else []


def test_user_message_persisted_when_create_agent_fails(client, store):
    """create_agent 抛错时，用户消息仍必须落库（否则刷新就找不回 query）。"""
    query = "这是失败也要能找回的 query"
    resp = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": query}],
            "model": "dummy-model",
            "stream": False,
        },
    )
    # 建 agent 失败：非 stream 路径返回带友好 detail 的错误（provider 配置类错误映射为 4xx）
    assert resp.status_code >= 400, resp.text

    sessions = asyncio.run(store.list_recent(limit=10))
    assert sessions, "应至少创建了一个 session"
    sid = sessions[0].id
    contents = [m.content for m in _load_messages(store, sid) if m.role == "user"]
    assert query in contents, f"用户消息必须已落库，实际 user 消息: {contents}"


def test_user_message_persisted_on_stream_setup_error(client, store):
    """stream 模式下建 agent 失败：返回 error 事件流，但 query 同样要落库。"""
    query = "stream 失败也要能找回"
    resp = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": query}],
            "model": "dummy-model",
            "stream": True,
        },
    )
    assert resp.status_code == 200
    assert "provider not configured" in resp.text or "error" in resp.text

    sessions = asyncio.run(store.list_recent(limit=10))
    assert sessions, "应至少创建了一个 session"
    sid = sessions[0].id
    contents = [m.content for m in _load_messages(store, sid) if m.role == "user"]
    assert query in contents, f"用户消息必须已落库，实际 user 消息: {contents}"
