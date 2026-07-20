"""嵌入路由（embedding-router）：已内置，依赖在 dependencies 里，模型首次使用自动下载。

本测试验证：
- embedding-router 不再出现在 PRESET_PLUGINS（已从插件体系移除）
- 模型缺失时路由静默回退关键词匹配
"""
from __future__ import annotations

import pytest


def test_embedding_router_removed_from_preset_plugins():
    """embedding-router 已内置，不应再出现在插件列表里。"""
    import ethan.interface.commands.setup as setup
    names = [p["name"] for p in setup.PRESET_PLUGINS]
    assert "embedding-router" not in names


def test_embedding_router_available_falls_back_without_model(monkeypatch):
    # 可选依赖缺失时跳过整条用例（干净 CI 环境），不崩溃收集
    pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    pytest.importorskip("numpy")
    # 模型文件缺失时 available 必须为 False（路由静默回退关键词匹配）
    from ethan.skills.router import EmbeddingRouter
    monkeypatch.setattr("ethan.skills.router.model_present", lambda: False)
    assert EmbeddingRouter().available is False
