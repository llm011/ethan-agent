"""OCR 工具与「优先模型识图」约定的测试。

要锁三条：

1. **OCR 只在配了 key 时注册**——没 key 时注册它等于给模型一个必然失败的工具。
2. **system prompt 里必须写明「优先模型识图」**——否则模型会对每张图都调 OCR，
   又慢又费钱（OCR 按请求计费，模型读图免费）。
3. **上传用户文件前要授权**——这是把本地文件内容发给第三方，性质与本地读文件不同。
"""
from __future__ import annotations

import pytest

from ethan.core import system_prompt as sp
from ethan.tools.builtin.ocr import OcrTool

# ── 工具元信息 ───────────────────────────────────────────────


def test_tool_metadata():
    t = OcrTool()
    assert t.name == "ocr_extract_text"
    assert t.side_effect is True, "OCR 会产生 API 费用，必须标 side_effect"
    assert t.cacheable is False, "每次上传都计费，不能缓存"
    assert t.no_compress is True, "识别结果是给模型读的正文"


def test_tool_description_tells_model_to_prefer_native_vision():
    """工具描述本身也要劝退——模型选工具主要看描述。"""
    desc = OcrTool.description
    assert "优先直接把图片交给模型" in desc
    assert "计费" in desc


def test_consent_required_before_upload():
    """上传用户文件到云端必须授权：用户有权知道文档会被发出去。"""
    msg = OcrTool().consent_check(path="/tmp/a.pdf")
    assert msg is not None
    assert "上传" in msg and "计费" in msg


# ── 参数与限制 ───────────────────────────────────────────────


def test_missing_file(tmp_path):
    import asyncio

    r = asyncio.run(OcrTool().run(path=str(tmp_path / "nope.pdf")))
    assert "不存在" in r.content


def test_empty_file(tmp_path):
    import asyncio

    f = tmp_path / "empty.pdf"
    f.write_bytes(b"")
    r = asyncio.run(OcrTool().run(path=str(f)))
    assert "为空" in r.content


def test_unknown_purpose_rejected(tmp_path):
    import asyncio

    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    r = asyncio.run(OcrTool().run(path=str(f), purpose="whatever"))
    assert "未知 purpose" in r.content


def test_missing_api_key_gives_actionable_hint(monkeypatch, tmp_path):
    """没配 key 时要告诉用户配在哪，而不是一句「失败」。

    注意：不能 monkeypatch 配置对象上的字段——`load_config()` 每次都重新读文件，
    改内存里那份实例不生效（实测踩到）。这里 patch 掉 load_config 返回值。
    """
    import asyncio
    from types import SimpleNamespace

    import ethan.core.config as cfg_mod

    fake = SimpleNamespace(
        tools=SimpleNamespace(web_fetch=SimpleNamespace(api_key="", base_url="")),
        network=SimpleNamespace(proxy=None),
    )
    monkeypatch.setattr(cfg_mod, "load_config", lambda: fake)

    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    r = asyncio.run(OcrTool().run(path=str(f)))
    assert "未配置" in r.content
    assert "api_key" in r.content


# ── 响应解析 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload,expect",
    [
        ({"text": "PLAIN"}, "PLAIN"),
        ({"content": "CONTENT"}, "CONTENT"),
        ({"markdown": "MD"}, "MD"),
        ({"result": "RES"}, "RES"),
    ],
)
def test_extract_text_top_level_fields(payload, expect):
    assert OcrTool._extract_text(payload) == expect


def test_extract_text_pages_structure():
    """逐页识别时响应是 pages 数组，要按页保留并可读。"""
    out = OcrTool._extract_text(
        {"pages": [{"text": "page one"}, {"content": "page two"}]}
    )
    assert "第 1 页" in out and "page one" in out
    assert "第 2 页" in out and "page two" in out


def test_extract_text_falls_back_gracefully():
    """结构未知时不丢内容，也不抛异常。"""
    assert OcrTool._extract_text({"weird": "VALUE"}) == "weird: VALUE"
    assert OcrTool._extract_text({}) == ""


# ── system prompt 的优先级约定 ───────────────────────────────


def test_image_priority_protocol_content():
    p = sp._image_priority_protocol()
    assert "直接把图片交给模型" in p
    assert "ocr_extract_text" in p
    assert "计费" in p


def test_protocol_injected_into_full_prompt(monkeypatch):
    """真正的约束在 system prompt 里——只靠工具描述不够。

    之前的实现只注入到「精简模式」分支，full 分支漏了，等于对正常对话完全无效。
    """
    from ethan.core.agent import Message
    from ethan.core.agent_factory import create_agent

    monkeypatch.setattr(sp, "_ocr_available", lambda: True)
    a = create_agent(channel="repl")
    prompt = a._build_system([Message(role="user", content="看下这张图")])
    assert "<image_protocol>" in prompt


def test_protocol_absent_when_ocr_unavailable(monkeypatch):
    """OCR 没注册时不能注入——否则教模型去用一个不存在的工具。"""
    from ethan.core.agent import Message
    from ethan.core.agent_factory import create_agent

    monkeypatch.setattr(sp, "_ocr_available", lambda: False)
    a = create_agent(channel="repl")
    prompt = a._build_system([Message(role="user", content="看下这张图")])
    assert "<image_protocol>" not in prompt


def test_ocr_registered_only_with_key(monkeypatch):
    """没 key 时不该注册 OCR（会诱导模型尝试必然失败的工具）。"""
    from ethan.core.agent_factory import build_tool_registry
    from ethan.core.config import get_config

    cfg = get_config()
    old = cfg.tools.web_fetch.api_key
    try:
        cfg.tools.web_fetch.api_key = ""
        names = [t.name for t in build_tool_registry(channel="repl").all()]
        assert "ocr_extract_text" not in names

        cfg.tools.web_fetch.api_key = "sk-test"
        names = [t.name for t in build_tool_registry(channel="repl").all()]
        assert "ocr_extract_text" in names
    finally:
        cfg.tools.web_fetch.api_key = old
