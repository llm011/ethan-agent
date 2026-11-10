"""技能列表接口的响应体积。

回归背景：GET /skills 曾返回每个技能的 SKILL.md 全文，167 个技能合计 1.5 MB，
实测该接口稳定慢 5–8 秒。列表页只渲染 name/description/trigger，
正文只在用户点开某个技能时才需要。
"""
from __future__ import annotations

import asyncio
import json


def _call_list(monkeypatch, *, include_content: bool):
    """直接调路由函数，绕开 HTTP 层（鉴权/依赖注入与本次改动无关）。"""
    from ethan.interface.routers import skills as skills_mod

    result = asyncio.run(
        skills_mod.list_skills(include_content=include_content, user_id="")
    )
    return result["skills"]


def test_list_skills_omits_content_by_default(monkeypatch):
    """默认不该带 content —— 它占了响应体积的 90% 以上。"""
    skills = _call_list(monkeypatch, include_content=False)

    assert skills, "至少要有一个技能"
    for item in skills:
        assert item["name"]
        assert "description" in item
        assert "trigger" in item
        assert "content" not in item, f"{item['name']} 不该带正文"


def test_list_skills_include_content_still_works(monkeypatch):
    """显式 include_content=True 保留旧行为（脚本/兼容调用方依赖）。"""
    skills = _call_list(monkeypatch, include_content=True)

    assert any(item.get("content") for item in skills), "include_content=True 时必须带正文"


def test_payload_without_content_is_much_smaller(monkeypatch):
    """体积必须显著下降，否则等于没优化。"""
    lean = json.dumps(_call_list(monkeypatch, include_content=False), ensure_ascii=False)
    full = json.dumps(_call_list(monkeypatch, include_content=True), ensure_ascii=False)

    assert len(lean) * 3 < len(full), (
        f"瘦身后 {len(lean)/1024:.0f}KB vs 完整 {len(full)/1024:.0f}KB，"
        "差距不够大，说明 content 没真正去掉"
    )
