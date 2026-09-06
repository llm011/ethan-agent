# -*- coding: utf-8 -*-
"""带 "/" 的 model id 全链路测试。

约定：复合键 provider/id 按第一个 "/" 拆分——前面是 provider 名，后面整段都是
model id，id 本身允许再含 "/"（聚合网关的 "trae/glm-5.3-flash" 命名方式）。

回归背景：
- 模型 id 含 "/" 时（provider "trae" + id "trae/glm-5.3-flash"），前端选中键是
  "trae/trae/glm-5.3-flash"。此前单个删除/更新走 /models/{provider}/{model_id}
  路径参数路由，uvicorn 会把 %2F 提前解码成 "/"，路径段匹配不到，设置页删不掉
  也改不了这类模型 → 改为 query 参数 / body 定位。
- 添加时的 id 必须原样完整落盘 config.yaml，不允许被拆分或截断。
"""
from __future__ import annotations

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.core.config import Config, ModelEntry, ProviderConfig
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
    cfg = _config_with(("trae", "glm-5.3-flash"), ("trae", "trae/glm-5.3-flash"))
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


# ── 解析规则：第一个 "/" 前是 provider，后面整段是 id ───────────────────


def test_get_model_first_slash_is_provider():
    """trae/glm-5.3-flash → provider=trae + id=glm-5.3-flash（不带前缀的条目）。"""
    cfg = _config_with(("trae", "glm-5.3-flash"), ("trae", "trae/glm-5.3-flash"))
    entry = cfg.get_model("trae/glm-5.3-flash")
    assert entry is not None
    assert (entry.provider, entry.id) == ("trae", "glm-5.3-flash")


def test_get_model_slash_id_selected_by_doubled_prefix():
    """trae/trae/glm-5.3-flash → 命中 id 本身带 "/" 的条目，id 完整保留。"""
    cfg = _config_with(("trae", "glm-5.3-flash"), ("trae", "trae/glm-5.3-flash"))
    entry = cfg.get_model("trae/trae/glm-5.3-flash")
    assert entry is not None
    assert (entry.provider, entry.id) == ("trae", "trae/glm-5.3-flash")


def test_create_provider_keeps_full_slash_id(monkeypatch):
    """带 "/" 的 id 必须原样传给 provider（发上游的 model 字段），前缀不被剥掉。"""
    import ethan.providers.manager as manager

    cfg = _config_with(("trae", "trae/glm-5.3-flash"))
    cfg.providers["trae"] = ProviderConfig(api_key="sk-test", base_url="https://gw.example.com/v1")
    monkeypatch.setattr(manager, "get_config", lambda: cfg)

    provider = manager.create_provider("trae/trae/glm-5.3-flash")
    assert provider.model == "trae/glm-5.3-flash"


# ── models API：带 "/" 的 id 可添加、更新、删除 ─────────────────────────


def test_batch_add_stores_slash_id_verbatim(client):
    """添加时 id 原样入库，不得拆分/截断。"""
    r = client.post("/models/batch", json={
        "models": [{"id": "openai/gpt-4o", "provider": "trae", "description": "", "alias": [], "vision": True}]
    })
    assert r.json() == {"ok": True, "added": 1, "skipped": []}
    assert "openai/gpt-4o" in [m.id for m in models_router.get_config().models]


def test_delete_slash_id_via_query_params(client):
    """单个删除走 query 参数：id 里的 "/" 不再破坏路由匹配。"""
    r = client.delete("/models", params={"provider": "trae", "id": "trae/glm-5.3-flash"})
    assert r.json()["ok"] is True
    assert [m.id for m in models_router.get_config().models] == ["glm-5.3-flash"]
    assert len(client._saves) == 1  # type: ignore[attr-defined]


def test_delete_slash_id_not_found(client):
    r = client.delete("/models", params={"provider": "trae", "id": "trae/nope"})
    assert r.json() == {"ok": False, "error": "model not found"}


def test_update_slash_id_via_body(client):
    """单个更新走 body 定位（req.provider + req.id）。"""
    r = client.put("/models", json={
        "id": "trae/glm-5.3-flash", "provider": "trae",
        "description": "GLM 5.3 Flash via Trae", "alias": [], "vision": False,
    })
    assert r.json()["ok"] is True
    entry = models_router.get_config().get_model("trae/trae/glm-5.3-flash")
    assert entry is not None
    assert entry.description == "GLM 5.3 Flash via Trae"
    assert entry.vision is False


# ── provider 名仍禁止含 "/"（复合键的第一段必须无歧义）──────────────────


def test_provider_key_with_slash_rejected(monkeypatch):
    """设置页新建 provider 时 key 带 "/" 要被拒绝（与 rename 同规则）。"""
    from ethan.interface.routers import settings as settings_router

    cfg = Config()
    monkeypatch.setattr(settings_router, "get_config", lambda: cfg)
    monkeypatch.setattr(settings_router, "save_config", lambda c: None)
    monkeypatch.setattr(settings_router, "reload_config", lambda: cfg)

    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[verify_token] = lambda: ""
    c = TestClient(app, raise_server_exceptions=False)

    r = c.patch("/settings/providers", json={"a/b": {"api_key": "sk-test"}})
    assert r.status_code == 400
    assert "a/b" not in cfg.providers

    # 已存在的正常 provider 不受影响
    r2 = c.patch("/settings/providers", json={"trae": {"api_key": "sk-test"}})
    assert r2.status_code == 200
    assert "trae" in cfg.providers


# ── 落盘往返：带 "/" 的 id 在 config.yaml 中完整保留 ────────────────────


def test_slash_id_survives_config_yaml_round_trip(monkeypatch, tmp_path):
    """save_config → config.yaml → load：id 不被拆分或截断。"""
    import ethan.core.config as config_mod

    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)

    cfg = _config_with(("trae", "trae/glm-5.3-flash"))
    cfg.providers["trae"] = ProviderConfig(api_key="sk-test", base_url="https://gw.example.com/v1")
    config_mod.save_config(cfg)

    raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    assert raw["models"][0]["id"] == "trae/glm-5.3-flash"

    reloaded = Config.model_validate(raw)
    entry = reloaded.get_model("trae/trae/glm-5.3-flash")
    assert entry is not None
    assert entry.id == "trae/glm-5.3-flash"
