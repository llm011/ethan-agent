# -*- coding: utf-8 -*-
"""图片能力判定：配置声明优先，未声明一律照发图片。

回归背景：
`OpenAICompatProvider._supports_vision()` 此前按硬编码关键词表猜模型名
（"vision"/"gpt-4o"/"gpt-4.1"/"claude"/"gemini"/"glm-4v"…），猜不中就
在 `_transform.to_openai_messages` 里把 image_url block 剥掉。该表必然
滞后于新模型发布——`deepseek-v4.1-flash` 这类新多模态模型不在表内，于是
用户看到的症状是「模型不支持读图」，而模型其实支持，且**没有任何报错**：
图片在客户端就被静默剥掉了，请求根本没带图片到上游。

修复后的判定顺序：
1. `ModelEntry.vision` 显式声明（True/False）——权威；
2. 未声明（None）→ True，照发图片。

第 2 步刻意偏向「可诊断」而非「静默降级」：发出去的代价是上游 400，
agent 层的 `_is_image_error` 会兜底（图片落盘 + 路径提示重试）；剥掉则
是静默失败，无法排查。
"""
from __future__ import annotations

import pytest

from ethan.core.config import Config, ModelEntry, ProviderConfig
from ethan.providers import _transform
from ethan.providers.base import Message


def _image_message() -> Message:
    return Message(
        role="user",
        content="这张图是什么颜色？",
        images=[{"data": "aGVsbG8=", "media_type": "image/png"}],
    )


def _has_image_block(messages: list[dict]) -> bool:
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            if any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
                return True
    return False


# ── _transform 层：能力 bool 直接决定是否剥图 ─────────────────────────


def test_transform_keeps_images_when_vision_true():
    out = _transform.to_openai_messages(
        [_image_message()], include_reasoning=False, supports_vision=True
    )
    assert _has_image_block(out), "vision=True 时图片必须保留"


def test_transform_strips_images_when_vision_false():
    out = _transform.to_openai_messages(
        [_image_message()], include_reasoning=False, supports_vision=False
    )
    assert not _has_image_block(out), "vision=False 时图片应被剥离"
    # 文本部分要保留，不能整条丢空
    assert any("这张图" in str(m.get("content")) for m in out)


# ── provider 层：声明优先 + 未声明照发 ────────────────────────────────


def _provider(model: str, vision: bool | None):
    """构造 provider，但绕开真实 SDK 客户端（只需 _model/_vision/_base_url）。"""
    from ethan.providers.openai_compat import OpenAICompatProvider

    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    p._model = model
    p._vision = vision
    p._base_url = ""
    return p


@pytest.mark.parametrize("model", [
    "deepseek-v4.1-flash",   # 新多模态模型：不在旧关键词表里
    "deepseek-v4-flash",
    "glm-5.3",
    "some-brand-new-model-v9",
])
def test_undeclared_vision_defaults_to_true(model):
    """未声明时照发图片——旧关键词表必然滞后，不能据此静默剥图。"""
    assert _provider(model, None)._supports_vision() is True


@pytest.mark.parametrize("model", ["deepseek-v4.1-flash", "whatever-latest"])
def test_explicit_true_overrides_keyword_miss(model):
    assert _provider(model, True)._supports_vision() is True


@pytest.mark.parametrize("model", ["glm-5.2", "gpt-4o"])
def test_explicit_false_overrides_keyword_hit(model):
    """声明 False 是权威——即使模型名命中旧关键词表也不能发图片。"""
    assert _provider(model, False)._supports_vision() is False


def test_declared_false_actually_strips_images():
    """端到端：声明 False → 经 provider 转换后图片确实被剥掉。"""
    p = _provider("glm-5.2", False)
    out = p._to_openai_messages([_image_message()])
    assert not _has_image_block(out)


def test_undeclared_keeps_images_end_to_end():
    """端到端：未声明 → 图片确实带到请求里。"""
    p = _provider("deepseek-v4.1-flash", None)
    out = p._to_openai_messages([_image_message()])
    assert _has_image_block(out), (
        "未声明的多模态模型图片被剥掉了——这正是本次要修的回归"
    )


# ── config / manager 层：声明真的能传到 provider ──────────────────────


def test_model_entry_vision_defaults_to_none():
    """默认 None（未声明），不是 True——否则「未声明」与「已声明支持」无法区分。"""
    assert ModelEntry(id="x", provider="p").vision is None


def test_vision_flag_reaches_provider(monkeypatch):
    """create_provider 必须把 ModelEntry.vision 透传给 provider。"""
    from ethan.providers import manager

    cfg = Config()
    cfg.models = [
        ModelEntry(id="deepseek-v4.1-flash", provider="openai_compat", vision=None),
        ModelEntry(id="glm-5.2", provider="openai_compat", vision=False),
        ModelEntry(id="mindvlm", provider="openai_compat", vision=True),
    ]
    cfg.providers = {"openai_compat": ProviderConfig(
        api_key="k", base_url="https://example.invalid/v1"
    )}
    monkeypatch.setattr(manager, "get_config", lambda: cfg)

    assert manager.create_provider("deepseek-v4.1-flash")._supports_vision() is True
    assert manager.create_provider("glm-5.2")._supports_vision() is False
    assert manager.create_provider("mindvlm")._supports_vision() is True
