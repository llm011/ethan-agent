"""移动端未读红点依赖的 API 契约。

Android（`app/android/shared/.../SessionUnreadTracker`）与 Web/Desktop 同口径：
**未读 = updated_at > last_read_at**，进入会话时调 `POST /sessions/{id}/read` 把水位
推到 `updated_at`。这两个端点就是红点能不能清掉的命门，所以在这里锁住对外契约：

- `/poll` 必须回 `last_read_at`（客户端靠它判未读；少一个字段就是「红点永远清不掉」）
- `/sessions/{id}/read` 推进水位，之后 `/poll` 看到 updated_at == last_read_at
- 幂等：本来就已读时 advanced=False
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.interface.routers import chat as chat_mod
from ethan.interface.routers import sessions as sessions_mod
from ethan.interface.routers.deps import verify_token
from ethan.memory.session import SessionStore
from ethan.providers.base import Message


@pytest.fixture()
def store(tmp_path, monkeypatch):
    s = SessionStore(db_path=tmp_path / "sessions.db")

    async def _init():
        await s.init()

    asyncio.run(_init())

    async def _fake_store():
        return s

    monkeypatch.setattr(sessions_mod, "get_session_store", _fake_store)
    monkeypatch.setattr(chat_mod, "get_session_store", _fake_store)
    yield s
    asyncio.run(s.close())


@pytest.fixture()
def client(store):
    app = FastAPI()
    app.include_router(sessions_mod.router)
    app.include_router(chat_mod.router)
    app.dependency_overrides[verify_token] = lambda: "u1"
    return TestClient(app, raise_server_exceptions=False)


def _seed(store, sid="s1"):
    """建会话 + 落一条后台回复 + touch（制造未读）。"""
    async def _run():
        await store.create_with_id(sid, model="m", source="web", mode="")
        await store.save_message(sid, Message(role="assistant", content="后台回复"))
        await store.touch(sid)

    asyncio.run(_run())


def _poll_by_id(client, sid):
    body = client.get("/poll").json()
    return next(s for s in body["sessions"] if s["id"] == sid)


def test_poll_exposes_last_read_at(client, store):
    """抽屉/侧边栏的未读判定完全依赖 /poll 的这个字段。"""
    _seed(store)
    row = _poll_by_id(client, "s1")
    assert "last_read_at" in row, "/poll 少回 last_read_at → 客户端红点判定失真"
    assert row["last_read_at"] < row["updated_at"], "前置：应有未读"


def test_mark_read_endpoint_advances_poll_watermark(client, store):
    """进入会话 → POST /read → 下一次 /poll 必须已读（updated_at == last_read_at）。"""
    _seed(store)

    resp = client.post("/sessions/s1/read")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "advanced": True}

    row = _poll_by_id(client, "s1")
    assert row["last_read_at"] == row["updated_at"], "红点应被清除"

    # 幂等：已读再调不报错、不重复推进
    assert client.post("/sessions/s1/read").json() == {"ok": True, "advanced": False}


def test_new_message_after_read_creates_unread_again(client, store):
    """清掉红点后新到的消息仍要能重新点亮（别把水位「锁死」）。"""
    _seed(store)
    client.post("/sessions/s1/read")

    async def _new_message():
        await store.save_message("s1", Message(role="assistant", content="又一条"))
        await store.touch("s1")

    asyncio.run(_new_message())

    row = _poll_by_id(client, "s1")
    assert row["updated_at"] > row["last_read_at"], "新消息应重新产生未读"


def test_sessions_list_carries_last_read_at(client, store):
    """「全部对话」列表走 /sessions，也要带水位（Android 主列表读的就是它）。"""
    _seed(store)
    client.post("/sessions/s1/read")
    row = client.get("/sessions").json()["sessions"][0]
    assert row["last_read_at"] == row["updated_at"]
