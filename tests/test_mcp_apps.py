"""Tests for MCP Apps (SEP-1865) 交互式图表集成。

覆盖三条链路：
1. UIResourceRegistry：注册 / list / read（含 _meta），未知 uri 返回 None。
2. /api/ui-resources 端点：list 与 read 的形状，未知 uri 报 404。
3. ChartTool 结果只带 {uri, data}，不内联 html（模板与数据分离）。
4. Message.mcp_apps 持久化：save / update / load 全链路回环。
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from ethan.tools.ui_resources import (
    UIResource,
    UIResourceMeta,
    UIResourceRegistry,
)


def test_registry_register_list_read():
    reg = UIResourceRegistry()
    res = UIResource(
        uri="ui://test/foo",
        name="Foo",
        description="a foo",
        html="<html>hi</html>",
        meta=UIResourceMeta(csp={"script-src": ["https://cdn.example.com"]}),
    )
    reg.register(res)

    listed = reg.list_all()
    assert len(listed) == 1
    assert listed[0].to_mcp_resource() == {
        "uri": "ui://test/foo",
        "name": "Foo",
        "description": "a foo",
        "mimeType": "text/html;profile=mcp-app",
    }

    content = reg.read("ui://test/foo")
    assert content is not None
    assert content["uri"] == "ui://test/foo"
    assert content["text"] == "<html>hi</html>"
    assert content["_meta"]["ui"]["csp"] == {"script-src": ["https://cdn.example.com"]}
    assert content["_meta"]["ui"]["prefersBorder"] is True


def test_registry_read_unknown_returns_none():
    reg = UIResourceRegistry()
    assert reg.read("ui://nope") is None
    assert reg.get("ui://nope") is None


def test_resource_read_html_prefers_template_file():
    # template_file 不存在时回退到内联 html
    res = UIResource(uri="ui://t/x", name="X", template_file="__does_not_exist__.html", html="fallback")
    assert res.read_html() == "fallback"


def test_chart_tool_registered():
    # 导入 chart 模块即注册 ui://ethan/chart 到全局 registry
    import ethan.tools.builtin.chart  # noqa: F401
    from ethan.tools.ui_resources import get_ui_registry

    res = get_ui_registry().get("ui://ethan/chart")
    assert res is not None
    assert "chart.js" in res.read_html().lower()


def test_chart_tool_result_has_uri_and_data_no_inline_html():
    from ethan.tools.builtin.chart import ChartTool

    result = asyncio.run(
        ChartTool().run(chart_type="bar", labels=["a", "b"], datasets=[{"data": [1, 2]}])
    )
    assert result.mcp_app is not None
    assert result.mcp_app["uri"] == "ui://ethan/chart"
    assert "chartConfig" in result.mcp_app["data"]
    # 关键：结果里不内联 html，前端按 uri 拉模板
    assert "html" not in result.mcp_app


def test_ui_resources_endpoints():
    from fastapi import HTTPException

    from ethan.interface.routers import ui_resources as uir

    async def main():
        listed = await uir.list_ui_resources()
        uris = [r["uri"] for r in listed["resources"]]
        assert "ui://ethan/chart" in uris

        content = await uir.read_ui_resource(uri="ui://ethan/chart")
        assert content["uri"] == "ui://ethan/chart"
        assert len(content["text"]) > 0

        with pytest.raises(HTTPException) as exc:
            await uir.read_ui_resource(uri="ui://does/not/exist")
        assert exc.value.status_code == 404

    asyncio.run(main())


def test_message_mcp_apps_persistence_roundtrip():
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    async def main():
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(Path(d) / "t.db")
            await store.init()
            session = await store.create(model="test")

            apps = [{"uri": "ui://ethan/chart", "data": {"chartConfig": {"type": "bar"}}}]
            mid = await store.save_message(
                session.id, Message(role="assistant", content="hi", mcp_apps=apps)
            )

            loaded = await store.load(session.id)
            asst = [m for m in loaded.messages if m.role == "assistant"][0]
            assert asst.mcp_apps == apps

            # update 路径（进度行定稿）也保留 mcp_apps
            new_apps = [{"uri": "ui://ethan/chart", "data": {"chartConfig": {"type": "line"}}}]
            await store.update_message(
                mid, session.id, Message(role="assistant", content="final", mcp_apps=new_apps)
            )
            loaded2 = await store.load(session.id)
            asst2 = [m for m in loaded2.messages if m.role == "assistant"][0]
            assert asst2.mcp_apps == new_apps
            assert asst2.content == "final"

            await store.close()

    asyncio.run(main())
