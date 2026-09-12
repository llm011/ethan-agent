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


# 1x1 透明 PNG
B64_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def test_user_message_quote_and_images_persisted_with_correct_shape(client, store):
    """quote 与 images 的落库格式必须与改造前一致（本 PR 换了落库实现，最易静默回归）。

    用户消息来源从 Message 对象换成了 req.messages 里的 raw dict，且 path 的取值
    逻辑变了。这里锁死三件事：
      - quote 非空，且内容正确（刷新后仍能渲染引用气泡）；
      - images 落成 [{path, media_type}]，不是原始 base64；
      - 不把 base64 的 data 字段写进库（否则 DB 体积膨胀、且渲染层拿到的是错的）。
    """
    query = "带引用和图片的 query"
    resp = client.post(
        "/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": query,
                    "images": [{"data": B64_PNG, "media_type": "image/png"}],
                }
            ],
            "quote": {"role": "assistant", "content": "被引用的内容"},
            "model": "dummy-model",
            "stream": False,
        },
    )
    assert resp.status_code >= 400, resp.text

    sessions = asyncio.run(store.list_recent(limit=10))
    assert sessions, "应至少创建了一个 session"
    sid = sessions[0].id
    user_msgs = [m for m in _load_messages(store, sid) if m.role == "user"]
    assert user_msgs, "用户消息必须已落库"
    msg = user_msgs[0]

    assert msg.quote, "引用信息必须落库，刷新后仍能渲染引用气泡"
    assert msg.quote.get("content") == "被引用的内容"

    assert msg.images, "图片必须落库"
    first = msg.images[0]
    assert first.get("path"), f"图片必须以 path 格式落库，实际: {first}"
    assert "data" not in first, "不应把原始 base64 写进库"
