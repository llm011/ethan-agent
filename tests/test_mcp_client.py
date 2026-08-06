"""Tests for MCP client — 外部 MCP server 集成（滴答清单用的 streamable-http 路径）。

覆盖：
1. HTTP 传输：本地起一个 FastMCP server（streamable-http），验证连接、工具发现、调用。
2. Bearer Token：校验 client 确实把 Authorization: Bearer <token> 发给了 server。
3. 工具命名：外部工具带 server 前缀（dida365_*）。
4. 无配置时 get_tools() 返回空，不产生连接。
5. 配置解析：Config 能接受 tools.mcp.servers。
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from ethan.core.config import MCPConfig, MCPServerConfig, ToolsConfig
from ethan.tools.mcp_client import MCPManager

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

captured_headers: dict[str, str] = {}


class _HeaderCapture:
    """包装 ASGI app，记录最近一次 HTTP 请求的 Authorization 头。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode(): v.decode() for k, v in scope["headers"]}
            captured_headers["auth"] = headers.get("authorization")
        await self.app(scope, receive, send)


def _build_test_server():
    mcp = FastMCP("dida365-test")

    @mcp.tool()
    def get_tasks() -> str:
        return "任务列表: [买牛奶, 准备会议材料]"

    @mcp.tool()
    def add_task(title: str, priority: str = "low") -> str:
        return f"已创建任务: {title} ({priority})"

    return _HeaderCapture(mcp.streamable_http_app())


@pytest.fixture()
def http_server():
    app = _build_test_server()
    config_ = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config_)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    try:
        yield server
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _stop_loop(mgr: MCPManager) -> None:
    """停掉管理器常驻事件循环线程，避免 pytest 挂住。"""
    if mgr._loop is not None and mgr._loop.is_running():
        mgr._loop.call_soon_threadsafe(mgr._loop.stop)
        if mgr._thread is not None:
            mgr._thread.join(timeout=5)


def test_config_accepts_mcp_servers():
    cfg = MCPServerConfig(name="dida365", url="https://mcp.dida365.com", bearer_token="tk")
    tools = ToolsConfig(mcp=MCPConfig(servers=[cfg]))
    assert tools.mcp.servers[0].name == "dida365"
    assert tools.mcp.servers[0].bearer_token == "tk"
    assert tools.mcp.servers[0].enabled is True
    # 缺省 enabled=True
    assert MCPServerConfig(name="x", url="u").enabled is True


def test_no_config_returns_empty():
    mgr = MCPManager()
    mgr._configured_servers = lambda: []  # noqa: E731
    assert mgr.get_tools() == []
    _stop_loop(mgr)


def test_http_connect_and_tool_call(http_server):
    cfg = MCPServerConfig(name="dida365", url=BASE, bearer_token="test-token")
    mgr = MCPManager()
    mgr._configured_servers = lambda: [cfg]  # noqa: E731
    try:
        tools = mgr.get_tools()
        names = sorted(t.name for t in tools)
        assert names == ["dida365_add_task", "dida365_get_tasks"]

        # Bearer Token 确实随请求发出
        assert captured_headers.get("auth") == "Bearer test-token"

        # 调用工具：走常驻循环桥接，返回文本
        add = [t for t in tools if t.name == "dida365_add_task"][0]
        out = asyncio.run(add.run(title="写周报", priority="high"))
        assert "写周报" in out and "high" in out

        get = [t for t in tools if t.name == "dida365_get_tasks"][0]
        out2 = asyncio.run(get.run())
        assert "买牛奶" in out2

        # 缓存命中：第二次 get_tools 不重连
        tools2 = mgr.get_tools()
        assert len(tools2) == 2
    finally:
        mgr.disconnect_all()
        _stop_loop(mgr)


def test_bad_server_skipped_not_reported(http_server):
    bad = MCPServerConfig(name="bad", url="http://127.0.0.1:1")
    good = MCPServerConfig(name="dida365", url=BASE)
    mgr = MCPManager()
    mgr._configured_servers = lambda: [bad, good]  # noqa: E731
    try:
        tools = mgr.get_tools()
        # 坏的 server 被跳过，好的 server 工具正常注册
        assert [t.name for t in tools] == ["dida365_add_task", "dida365_get_tasks"]
    finally:
        mgr.disconnect_all()
        _stop_loop(mgr)