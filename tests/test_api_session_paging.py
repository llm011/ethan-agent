"""GET /sessions/{id} 的分页契约。

前端「上滚加载更早消息」完全依赖这个端点返回的 has_more / oldest_id，
所以这里直接跑真实路由（store 指向临时 db），锁住对外契约：

- 不传 limit/before → 全量返回，has_more 恒为 False（兼容老前端）
- 传 limit → 只返回最近 N 条，且仍是时间正序
- 传 before → 严格早于该 id
- oldest_id 是本次返回的最旧一条的 id，前端把它原样当下次的 before
- 一页页往回翻能无重无漏覆盖全部消息
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    yield s
    asyncio.run(s.close())


@pytest.fixture()
def client(store):
    app = FastAPI()
    app.include_router(sessions_mod.router)
    app.dependency_overrides[verify_token] = lambda: ""
    return TestClient(app, raise_server_exceptions=False)


def _seed(store, sid="s1", n=10):
    """写入 n 条消息，返回它们的 id（正序）。"""
    async def _run():
        await store.create_with_id(sid, model="m", source="web", mode="")
        ids = []
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            ids.append(await store.save_message(sid, Message(role=role, content=f"msg-{i}")))
        return ids

    return asyncio.run(_run())


def test_no_params_returns_everything_and_has_more_false(client, store):
    """不带参数 = 全量，has_more 必须是 False（老前端据此不会继续请求）。"""
    ids = _seed(store, n=10)
    body = client.get("/sessions/s1").json()
    assert [m["id"] for m in body["messages"]] == ids
    assert body["has_more"] is False
    assert body["oldest_id"] == ids[0]


def test_limit_returns_recent_page_in_ascending_order(client, store):
    """limit 取最近 N 条，且仍按时间正序（前端直接渲染，不做反转）。"""
    ids = _seed(store, n=10)
    body = client.get("/sessions/s1", params={"limit": 3}).json()
    assert [m["id"] for m in body["messages"]] == ids[-3:]
    assert body["oldest_id"] == ids[-3]


def test_has_more_true_when_older_messages_exist(client, store):
    """只取一页时必须告诉前端「还有更早的」，否则上滚就停住了。"""
    _seed(store, n=10)
    body = client.get("/sessions/s1", params={"limit": 3}).json()
    assert body["has_more"] is True


def test_has_more_false_when_page_covers_start(client, store):
    """一页就装下了全部消息 → has_more=False，前端不再多打一次空请求。"""
    ids = _seed(store, n=3)
    body = client.get("/sessions/s1", params={"limit": 10}).json()
    assert [m["id"] for m in body["messages"]] == ids
    assert body["has_more"] is False


def test_before_is_exclusive(client, store):
    """before 是严格早于：不会把边界那条重复返回给前端。"""
    ids = _seed(store, n=10)
    body = client.get("/sessions/s1", params={"limit": 2, "before": ids[4]}).json()
    got = [m["id"] for m in body["messages"]]
    assert got == ids[2:4]
    assert all(mid < ids[4] for mid in got)


def test_before_without_limit_returns_all_earlier(client, store):
    """只传 before 不传 limit：返回全部更早消息，不能 500。

    limit / before 是各自独立的可选参数，契约上允许只传 before。
    store 层若对 None 直接 int() 会 TypeError → 500（项目没有全局异常处理器兜底）。
    """
    ids = _seed(store, n=10)
    res = client.get("/sessions/s1", params={"before": ids[5]})
    assert res.status_code == 200
    body = res.json()
    assert [m["id"] for m in body["messages"]] == ids[:5]
    assert body["oldest_id"] == ids[0]
    assert body["has_more"] is False


def test_paging_walks_all_messages_without_gaps_or_dupes(client, store):
    """用 oldest_id 当游标一页页往回翻，能无重无漏覆盖全部消息。

    这是前端 handleLoadOlder 的确切用法：before 传上一页的 oldest_id。
    """
    ids = _seed(store, n=10)
    collected: list[int] = []
    before = None
    for _ in range(20):  # 上界防御：逻辑写错时不至于死循环
        params: dict = {"limit": 3}
        if before is not None:
            params["before"] = before
        body = client.get("/sessions/s1", params=params).json()
        page = [m["id"] for m in body["messages"]]
        if not page:
            break
        collected = page + collected
        before = body["oldest_id"]
        if not body["has_more"]:
            break
    assert collected == ids


def test_empty_session_paging_is_safe(client, store):
    """空会话（新建但还没说话）分页不报错，返回空数组。"""
    async def _mk():
        await store.create_with_id("empty", model="m", source="web", mode="")

    asyncio.run(_mk())
    body = client.get("/sessions/empty", params={"limit": 30}).json()
    assert body["messages"] == []
    assert body["has_more"] is False
    assert body["oldest_id"] is None


def test_missing_session_404(client, store):
    assert client.get("/sessions/nope").status_code == 404


def test_tool_role_messages_do_not_break_oldest_id(client, store):
    """只有 user/assistant 会返回给前端，oldest_id 必须取自返回集，
    否则游标会指向一条前端看不见的消息，导致翻页卡死或跳页。"""
    async def _run():
        await store.create_with_id("s2", model="m", source="web", mode="")
        await store.save_message("s2", Message(role="user", content="q1"))
        await store.save_message("s2", Message(role="tool", content="tool out", tool_call_id="t1"))
        await store.save_message("s2", Message(role="assistant", content="a1"))

    asyncio.run(_run())
    body = client.get("/sessions/s2", params={"limit": 2}).json()
    returned = [m["id"] for m in body["messages"]]
    assert body["oldest_id"] == returned[0]
    assert all(m["role"] in ("user", "assistant") for m in body["messages"])
