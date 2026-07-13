"""嵌入路由（embedding-router）插件：注册表、安装派发、状态检测、路由回退。

不依赖网络或模型下载；通过 monkeypatch 隔离安装与模型检查。
"""
from __future__ import annotations

import pytest

import ethan.interface.commands.setup as setup

# 注：EmbeddingRouter 的导入刻意不放在模块级，而是移到用到它的测试函数内部，
# 并在函数内用 pytest.importorskip 保护——避免干净 CI 容器（缺
# onnxruntime / transformers / numpy）在用例收集阶段就因 import 失败而崩溃。
# （本环境的 pytest 不会把「模块级 importorskip」当 skip，会直接抛 Skipped，
#  故采用函数内导入 + 函数内 importorskip 的写法。）

ROUTER_ENTRY = {
    "name": "embedding-router",
    "label": "嵌入路由",
    "description": "语义 skill 路由（BGE 向量 + LR 头），提升泛化召回、减少漏触发",
    "install_type": "optional_dep",
    "pip_packages": [
        "onnxruntime>=1.18.0",
        "transformers>=4.40.0",
        "numpy>=1.26.0",
    ],
    "post_install": "router_pull",
}


def test_preset_table_contains_embedding_router():
    names = [p["name"] for p in setup.PRESET_PLUGINS]
    assert "embedding-router" in names
    entry = next(p for p in setup.PRESET_PLUGINS if p["name"] == "embedding-router")
    assert entry["install_type"] == "optional_dep"
    assert entry["pip_packages"] == ROUTER_ENTRY["pip_packages"]
    assert entry.get("post_install") == "router_pull"
    assert entry.get("label") == "嵌入路由"


def test_do_install_dispatches_optional_dep_and_post_hook(monkeypatch):
    called = {}

    def fake_pip(packages):
        called["pip"] = list(packages)
        return True

    def fake_post():
        called["post"] = True

    monkeypatch.setattr(setup, "_pip_install", fake_pip)
    monkeypatch.setattr(setup, "_post_install_router_pull", fake_post)

    setup._do_install(ROUTER_ENTRY)

    assert called.get("pip") == ROUTER_ENTRY["pip_packages"]
    assert called.get("post") is True


def test_check_installed_requires_deps_and_model(monkeypatch):
    # 依赖已装 + 模型已就位 → 已安装
    monkeypatch.setattr(setup, "_is_optional_dep_installed", lambda p: True)
    monkeypatch.setattr("ethan.skills.router.model_present", lambda: True)
    assert setup._check_plugin_installed(ROUTER_ENTRY) is True

    # 依赖已装 + 模型缺失 → 未安装
    monkeypatch.setattr(setup, "_is_optional_dep_installed", lambda p: True)
    monkeypatch.setattr("ethan.skills.router.model_present", lambda: False)
    assert setup._check_plugin_installed(ROUTER_ENTRY) is False

    # 依赖缺失 → 未安装（不依赖模型）
    monkeypatch.setattr(setup, "_is_optional_dep_installed", lambda p: False)
    monkeypatch.setattr("ethan.skills.router.model_present", lambda: True)
    assert setup._check_plugin_installed(ROUTER_ENTRY) is False


def test_embedding_router_available_falls_back_without_model(monkeypatch):
    # 可选依赖缺失时跳过整条用例（干净 CI 环境），不崩溃收集
    pytest.importorskip("onnxruntime")
    pytest.importorskip("transformers")
    pytest.importorskip("numpy")
    # 模型文件缺失时 available 必须为 False（路由静默回退关键词匹配）
    from ethan.skills.router import EmbeddingRouter
    monkeypatch.setattr("ethan.skills.router.model_present", lambda: False)
    assert EmbeddingRouter().available is False
