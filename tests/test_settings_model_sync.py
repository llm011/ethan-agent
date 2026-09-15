# -*- coding: utf-8 -*-
"""设置页「定时/心跳任务跟随默认模型」开关（defaults.model_sync）测试。

语义：
- 开关打开（默认 true）→ 定时/心跳任务跟随默认模型，PATCH 时清空两字段
- 开关关闭（false）→ 两字段各自独立；留空仍等于跟随默认模型，非空用自身值
- save_config 用 exclude_defaults=True，所以 True 不落盘、False 才写 config.yaml
"""
from __future__ import annotations

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.core.config import Config
from ethan.interface.routers import settings as settings_router
from ethan.interface.routers.deps import verify_token


@pytest.fixture()
def client(monkeypatch):
    """只挂 settings 路由的最小 app：config 走内存，save/reload 打桩，不碰真实配置。"""
    cfg = Config()
    cfg.defaults.model = "claude-sonnet-4.6"
    saves = []

    def _save(c):
        saves.append(c.model_dump(exclude_defaults=True, exclude_none=True))

    monkeypatch.setattr(settings_router, "get_config", lambda: cfg)
    monkeypatch.setattr(settings_router, "save_config", _save)
    monkeypatch.setattr(settings_router, "reload_config", lambda: cfg)

    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[verify_token] = lambda: ""
    c = TestClient(app)
    c._saves = saves  # type: ignore[attr-defined]
    c._cfg = cfg  # type: ignore[attr-defined]
    return c


# ── 默认值 ──────────────────────────────────────────────────────────


def test_default_is_on(client):
    """不配置时默认打开（跟随默认模型）。"""
    assert client._cfg.defaults.model_sync is True
    r = client.get("/settings/agent")
    assert r.status_code == 200
    assert r.json()["model_sync"] is True


def test_default_fields_follow_default_model(client):
    """默认状态下两字段为空 = 跟随默认模型（后端靠 `or None` 兜底）。"""
    assert client._cfg.defaults.schedule_model == ""
    assert client._cfg.defaults.heartbeat.model == ""


# ── 关闭开关：各自独立 ──────────────────────────────────────────────


def test_can_set_independent_models_when_off(client):
    """关掉开关后，两字段可独立写入。"""
    r = client.patch("/settings/agent", json={
        "model_sync": False,
        "schedule_model": "gpt-4o-mini",
        "heartbeat_model": "gemini-3.5-flash",
    })
    assert r.status_code == 200
    assert client._cfg.defaults.model_sync is False
    assert client._cfg.defaults.schedule_model == "gpt-4o-mini"
    assert client._cfg.defaults.heartbeat.model == "gemini-3.5-flash"


def test_off_keeps_blank_as_follow(client):
    """关掉开关但字段留空 → 仍等于跟随默认模型（空串，不写入具体模型）。"""
    client.patch("/settings/agent", json={"model_sync": False})
    assert client._cfg.defaults.model_sync is False
    assert client._cfg.defaults.schedule_model == ""
    assert client._cfg.defaults.heartbeat.model == ""


def test_off_does_not_touch_values(client):
    """关掉开关不应改动已有字段值（只改开关本身）。"""
    client._cfg.defaults.schedule_model = "gpt-4o-mini"
    client._cfg.defaults.heartbeat.model = "gemini-3.5-flash"
    client.patch("/settings/agent", json={"model_sync": False})
    assert client._cfg.defaults.schedule_model == "gpt-4o-mini"
    assert client._cfg.defaults.heartbeat.model == "gemini-3.5-flash"


# ── 打开开关：清空跟随 ──────────────────────────────────────────────


def test_on_clears_independent_models(client):
    """打开开关时清空两字段 → 跟随默认模型，切默认二者一起变。"""
    client._cfg.defaults.model_sync = False
    client._cfg.defaults.schedule_model = "gpt-4o-mini"
    client._cfg.defaults.heartbeat.model = "gemini-3.5-flash"

    r = client.patch("/settings/agent", json={"model_sync": True})

    assert r.status_code == 200
    assert client._cfg.defaults.model_sync is True
    assert client._cfg.defaults.schedule_model == ""
    assert client._cfg.defaults.heartbeat.model == ""


def test_on_clears_even_if_models_sent_in_same_patch(client):
    """同一 PATCH 里既开开关又传了模型 → 开关赢，两字段被清空。

    前端整包提交 agentForm，开关打开时也会把（被禁用但仍有值的）字段一起发上来，
    所以"清空"必须发生在字段写入之后。
    """
    r = client.patch("/settings/agent", json={
        "model_sync": True,
        "schedule_model": "gpt-4o-mini",
        "heartbeat_model": "gemini-3.5-flash",
    })
    assert r.status_code == 200
    assert client._cfg.defaults.schedule_model == ""
    assert client._cfg.defaults.heartbeat.model == ""


# ── 未传 model_sync：不误清空 ──────────────────────────────────────


def test_omitted_model_sync_leaves_fields_alone(client):
    """PATCH 不带 model_sync（老客户端）→ 不应清空字段。"""
    client._cfg.defaults.schedule_model = "gpt-4o-mini"
    client._cfg.defaults.heartbeat.model = "gemini-3.5-flash"

    client.patch("/settings/agent", json={"agent_name": "Ethan2"})

    assert client._cfg.defaults.schedule_model == "gpt-4o-mini"
    assert client._cfg.defaults.heartbeat.model == "gemini-3.5-flash"


# ── 不变量：model_sync 不能走 config_set（无联动钩子）─────────────────


def test_model_sync_not_exposed_to_config_set():
    """model_sync 刻意不进 EDITABLE_FIELDS。

    它打开时必须同时清空 schedule_model / heartbeat.model 才成立。而 config_set
    走的是纯属性写入的 set_value，没有联动钩子——一旦暴露，agent 通过 config_set
    打开开关会留下旧模型值，出现「开关显示跟随、实际仍用旧模型」的静默不一致。
    该开关只在设置页维护。本测试锁住这个决定。
    """
    from ethan.core.config_schema import get_field

    assert get_field("defaults.model_sync") is None


# ── 落盘：exclude_defaults 行为 ────────────────────────────────────


def test_true_not_persisted_false_persisted(monkeypatch, tmp_path):
    """True（默认值）不写进 config.yaml；False 才写。"""
    import ethan.core.config as config_mod

    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)

    # True（默认）→ 不落盘
    config_mod.save_config(Config())
    raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    assert "model_sync" not in (raw.get("defaults") or {})

    # False → 落盘为 false，且 round-trip 后仍是 False
    cfg = Config()
    cfg.defaults.model_sync = False
    config_mod.save_config(cfg)
    raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    assert raw["defaults"]["model_sync"] is False
    assert Config.model_validate(raw).defaults.model_sync is False
