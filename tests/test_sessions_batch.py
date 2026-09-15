# -*- coding: utf-8 -*-
"""「全部对话」页批量操作的后端契约（POST /sessions/delete-batch、toggle-done-batch）。

跑真实路由 + 临时 SQLite（同 test_api_session_paging.py），锁住三件事：

1. **missing 要如实回报**：勾选的会话可能刚被别的窗口删掉，前端要靠 deleted/missing
   分开提示「另有 N 个已不存在」，而不是把没删掉的静默吞掉（同 /models/delete-batch）。
2. **受保护前缀不能被污染**：[定时]/[后台]/[心跳] 是系统会话的识别标记，批量打勾
   必须跳过它们并计入 skipped，否则系统会话会在列表里"隐身"或被误处理。
3. **✅ 前缀的边界**：空标题回退「新对话」——去掉 "✅" 会变空串，后端 rename 会 400。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.interface.routers import sessions as sessions_mod
from ethan.interface.routers.deps import verify_token
from ethan.memory.session import SessionStore


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


def _seed(store, *ids_and_titles):
    """建若干会话，title 为 None 时保持默认「新对话」。"""
    async def _run():
        for sid, title in ids_and_titles:
            await store.create_with_id(sid, model="m", source="web", mode="")
            if title is not None:
                await store.update_title(sid, title)

    asyncio.run(_run())


def _titles(store, *ids) -> dict[str, str]:
    async def _run():
        out = {}
        for sid in ids:
            s = await store.load(sid)
            out[sid] = s.title if s else None
        return out

    return asyncio.run(_run())


# ── 批量删除 ──────────────────────────────────────────────────────


def test_delete_batch_reports_missing_when_partially_gone(client, store):
    """勾 3 个、其中 1 个已不存在：deleted=2、missing=1。"""
    _seed(store, ("s1", "A"), ("s2", "B"), ("s3", "C"))
    r = client.post("/sessions/delete-batch", json={"ids": ["s1", "s2", "gone"]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["deleted"] == 2
    assert body["missing"] == 1


def test_delete_batch_actually_removes_rows(client, store):
    """删掉之后会话真的没了（不能只回个数字，DB 里还留着）。"""
    _seed(store, ("s1", "A"), ("s2", "B"))
    client.post("/sessions/delete-batch", json={"ids": ["s1"]})
    assert _titles(store, "s1", "s2") == {"s1": None, "s2": "B"}


def test_delete_batch_empty_ids_rejected(client):
    """空 ids 不报 500，回 ok=False，前端好提示。"""
    body = client.post("/sessions/delete-batch", json={"ids": []}).json()
    assert body["ok"] is False
    assert body["deleted"] == 0


def test_delete_batch_duplicate_ids_counted_once(client, store):
    """重复 id 去重：deleted 不该因重复项虚高，missing 也不能算成负数。"""
    _seed(store, ("s1", "A"))
    body = client.post("/sessions/delete-batch", json={"ids": ["s1", "s1", "s1"]}).json()
    assert body["deleted"] == 1
    assert body["missing"] == 0


def test_delete_batch_all_gone_returns_missing(client):
    """勾的全都不存在：仍带 missing，前端可提示刷新而不是含糊报错。"""
    body = client.post("/sessions/delete-batch", json={"ids": ["g1", "g2"]}).json()
    assert body["deleted"] == 0
    assert body["missing"] == 2


def test_delete_batch_clears_session_grants(client, store, monkeypatch):
    """批量删除必须和单条删除一样清掉授权记忆（否则同 id 复用会残留旧授权）。"""
    cleared = []
    monkeypatch.setattr("ethan.core.consent.clear_session_grants", cleared.append)
    _seed(store, ("s1", "A"), ("s2", "B"))
    client.post("/sessions/delete-batch", json={"ids": ["s1", "s2"]})
    assert sorted(cleared) == ["s1", "s2"]


def test_delete_batch_does_not_clear_grants_for_missing(client, store, monkeypatch):
    """没删掉的（不存在的）不该被清授权——clear 只对真实删除的 id 调。"""
    cleared = []
    monkeypatch.setattr("ethan.core.consent.clear_session_grants", cleared.append)
    _seed(store, ("s1", "A"))
    client.post("/sessions/delete-batch", json={"ids": ["s1", "gone"]})
    assert cleared == ["s1"]


# ── 批量标记完成 ──────────────────────────────────────────────────


def test_toggle_done_adds_prefix(client, store):
    """批量标记完成 = 标题加 ✅ 前缀（数据层没有 status 字段）。"""
    _seed(store, ("s1", "写周报"), ("s2", "看论文"))
    body = client.post("/sessions/toggle-done-batch", json={"ids": ["s1", "s2"], "done": True}).json()
    assert body["ok"] is True
    assert body["updated"] == 2
    assert body["missing"] == 0
    assert _titles(store, "s1", "s2") == {"s1": "✅ 写周报", "s2": "✅ 看论文"}


def test_toggle_done_removes_prefix(client, store):
    """取消完成 = 去掉 ✅ 前缀，恢复原标题。"""
    _seed(store, ("s1", "✅ 写周报"))
    body = client.post("/sessions/toggle-done-batch", json={"ids": ["s1"], "done": False}).json()
    assert body["updated"] == 1
    assert _titles(store, "s1") == {"s1": "写周报"}


def test_toggle_done_is_idempotent(client, store):
    """已经是目标状态：算成功（幂等），但标题不该被叠成「✅ ✅ x」。"""
    _seed(store, ("s1", "✅ 写周报"))
    body = client.post("/sessions/toggle-done-batch", json={"ids": ["s1"], "done": True}).json()
    assert body["updated"] == 1
    assert _titles(store, "s1") == {"s1": "✅ 写周报"}


def test_toggle_done_empty_title_falls_back(client, store):
    """标题只剩 "✅" 时取消完成 → 回退「新对话」，不能变成空串（后端 rename 会 400）。"""
    _seed(store, ("s1", "✅"))
    client.post("/sessions/toggle-done-batch", json={"ids": ["s1"], "done": False})
    assert _titles(store, "s1") == {"s1": "新对话"}


def test_toggle_done_default_title_gets_prefix(client, store):
    """默认标题「新对话」标记完成 → 「✅ 新对话」。"""
    _seed(store, ("s1", None))
    client.post("/sessions/toggle-done-batch", json={"ids": ["s1"], "done": True})
    assert _titles(store, "s1") == {"s1": "✅ 新对话"}


def test_toggle_done_skips_protected_prefixes(client, store):
    """[定时]/[后台]/[心跳] 不被 ✅ 污染，计入 skipped。"""
    _seed(store, ("s1", "[定时] 每日总结"), ("s2", "[后台] 跑任务"), ("s3", "[心跳] ping"), ("s4", "普通会话"))
    body = client.post(
        "/sessions/toggle-done-batch",
        json={"ids": ["s1", "s2", "s3", "s4"], "done": True},
    ).json()
    assert body["updated"] == 1
    assert body["skipped"] == 3
    assert _titles(store, "s1", "s2", "s3", "s4") == {
        "s1": "[定时] 每日总结",
        "s2": "[后台] 跑任务",
        "s3": "[心跳] ping",
        "s4": "✅ 普通会话",
    }


def test_toggle_done_counts_missing(client, store):
    """不存在的会话计入 missing，不因找不到就静默略过。"""
    _seed(store, ("s1", "A"))
    body = client.post("/sessions/toggle-done-batch", json={"ids": ["s1", "gone"], "done": True}).json()
    assert body["updated"] == 1
    assert body["missing"] == 1
    assert body["skipped"] == 0


def test_toggle_done_empty_ids_rejected(client):
    body = client.post("/sessions/toggle-done-batch", json={"ids": [], "done": True}).json()
    assert body["ok"] is False


def test_toggle_done_duplicate_ids_applied_once(client, store):
    """重复 id 去重：不会加两次 ✅（"✅ ✅ x"）。"""
    _seed(store, ("s1", "写周报"))
    client.post("/sessions/toggle-done-batch", json={"ids": ["s1", "s1"], "done": True})
    assert _titles(store, "s1") == {"s1": "✅ 写周报"}
