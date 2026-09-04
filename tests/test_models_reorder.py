# -*- coding: utf-8 -*-
"""models 路由 reorder 接口测试（settings 页拖拽排序）。

核心回归点：
1. 重排后顺序与 items 一致；
2. items 里不存在的 (provider, id) 跳过不报错（别的窗口刚删过）；
3. items 没提到的模型（别的窗口刚加的）按原相对顺序追加末尾，不丢失。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.core.config import Config, ModelEntry
from ethan.interface.routers import models as models_router
from ethan.interface.routers.deps import verify_token


@pytest.fixture()
def client(monkeypatch):
    """只挂 models 路由的最小 app：config 走内存，save/reload 打桩，不碰真实配置。"""
    cfg = Config()
    cfg.models = [ModelEntry(id=mid, provider=prov) for prov, mid in
                  [("p1", "a"), ("p1", "b"), ("p2", "c"), ("p2", "d")]]
    saves = []
    monkeypatch.setattr(models_router, "get_config", lambda: cfg)
    monkeypatch.setattr(models_router, "save_config", lambda c: saves.append(len(c.models)))
    monkeypatch.setattr(models_router, "reload_config", lambda: cfg)

    app = FastAPI()
    app.include_router(models_router.router)
    app.dependency_overrides[verify_token] = lambda: ""
    c = TestClient(app)
    c._saves = saves  # type: ignore[attr-defined]
    c._cfg = cfg  # type: ignore[attr-defined]
    return c


def _ids(cfg) -> list[str]:
    return [m.id for m in cfg.models]


def test_reorder_applies_new_order(client):
    r = client.post("/models/reorder", json={
        "items": [
            {"provider": "p2", "id": "c"},
            {"provider": "p1", "id": "a"},
            {"provider": "p2", "id": "d"},
            {"provider": "p1", "id": "b"},
        ]
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert _ids(client._cfg) == ["c", "a", "d", "b"]
    assert len(client._saves) == 1  # type: ignore[attr-defined]


def test_reorder_skips_unknown_items(client):
    """items 里带已不存在的模型：跳过，其余照常重排。"""
    r = client.post("/models/reorder", json={
        "items": [
            {"provider": "p2", "id": "gone"},
            {"provider": "p2", "id": "d"},
            {"provider": "p1", "id": "a"},
        ]
    })
    body = r.json()
    assert body["ok"] is True
    assert body["skipped"] == 1
    # b、c 不在 items 里，按原相对顺序（b 在 c 前）追加末尾
    assert _ids(client._cfg) == ["d", "a", "b", "c"]


def test_reorder_partial_items_appends_rest(client):
    """items 只包含部分模型时，剩下的不能丢。"""
    r = client.post("/models/reorder", json={
        "items": [{"provider": "p2", "id": "d"}]
    })
    assert r.json()["ok"] is True
    assert _ids(client._cfg) == ["d", "a", "b", "c"]


def test_reorder_dedupes_repeated_items(client):
    """同一模型出现两次：只生效一次。"""
    r = client.post("/models/reorder", json={
        "items": [
            {"provider": "p1", "id": "b"},
            {"provider": "p1", "id": "b"},
            {"provider": "p1", "id": "a"},
        ]
    })
    assert r.json()["ok"] is True
    assert _ids(client._cfg) == ["b", "a", "c", "d"]


def test_reorder_empty_items_rejected(client):
    r = client.post("/models/reorder", json={"items": []})
    assert r.json()["ok"] is False
    assert client._saves == []  # type: ignore[attr-defined]  没东西就不写盘
