# -*- coding: utf-8 -*-
"""models 路由批量接口测试（PR #270 review 回归）。

核心回归点：delete-batch 必须区分「真删掉几个」(deleted) 和「勾了但配置里已没有
几个」(missing)。勾选的模型可能刚被别的窗口/设备删掉，此时 deleted < 勾选数，
后端只回 deleted 的话前端就只会提示「已删除 M 个」，没删掉的被静默吞掉。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.core.config import Config, ModelEntry
from ethan.interface.routers import models as models_router
from ethan.interface.routers.deps import verify_token


def _config_with(*models: tuple[str, str]) -> Config:
    """造一份只含指定 (provider, id) 模型的内存配置。"""
    cfg = Config()
    cfg.models = [ModelEntry(id=mid, provider=prov) for prov, mid in models]
    return cfg


@pytest.fixture()
def client(monkeypatch):
    """只挂 models 路由的最小 app：config 走内存，save/reload 打桩，不碰真实配置。"""
    cfg = _config_with(("p1", "a"), ("p1", "b"), ("p2", "c"))
    saves = []
    monkeypatch.setattr(models_router, "get_config", lambda: cfg)
    monkeypatch.setattr(models_router, "save_config", lambda c: saves.append(len(c.models)))
    monkeypatch.setattr(models_router, "reload_config", lambda: cfg)

    app = FastAPI()
    app.include_router(models_router.router)
    app.dependency_overrides[verify_token] = lambda: ""
    c = TestClient(app)
    c._saves = saves  # type: ignore[attr-defined]
    return c


def test_delete_batch_reports_missing_when_partially_gone(client):
    """勾 5 个、其中 2 个已不存在：deleted=3、missing=2，不能只回 deleted。"""
    r = client.post("/models/delete-batch", json={
        "items": [
            {"provider": "p1", "id": "a"},
            {"provider": "p1", "id": "b"},
            {"provider": "p2", "id": "c"},
            {"provider": "p1", "id": "gone-1"},
            {"provider": "p2", "id": "gone-2"},
        ]
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["deleted"] == 3
    assert body["missing"] == 2  # 关键：没匹配到的 2 个必须回给前端
    assert len(client._saves) == 1  # type: ignore[attr-defined]


def test_delete_batch_all_gone_returns_missing_not_bare_error(client):
    """勾的全都不存在：仍要带 missing，前端才能提示刷新而不是报个含糊的错。"""
    r = client.post("/models/delete-batch", json={
        "items": [{"provider": "p1", "id": "gone-1"}, {"provider": "p2", "id": "gone-2"}]
    })
    body = r.json()
    assert body["ok"] is False
    assert body["deleted"] == 0
    assert body["missing"] == 2
    assert client._saves == []  # type: ignore[attr-defined]  没删到东西就不写盘


def test_delete_batch_all_matched_has_zero_missing(client):
    """全部命中：missing=0，前端不该画蛇添足提示「已不存在」。"""
    r = client.post("/models/delete-batch", json={
        "items": [{"provider": "p1", "id": "a"}, {"provider": "p1", "id": "b"}]
    })
    body = r.json()
    assert body["ok"] is True
    assert body["deleted"] == 2
    assert body["missing"] == 0


def test_delete_batch_empty_items_rejected(client):
    r = client.post("/models/delete-batch", json={"items": []})
    assert r.json()["ok"] is False
