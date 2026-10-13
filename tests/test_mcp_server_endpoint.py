"""Tests for the built-in MCP server endpoint (`/mcp` on the main API app).

回归背景：`/mcp` 是 mount 到主 FastAPI app 上的子应用，而 Starlette 的 `Mount` **不会**
转发子应用的 lifespan。`streamable_http_app()` 把 session manager 的启动放在它自己那个
Starlette 的 lifespan 里，所以只要没人从顶层 lifespan 进去，session manager 的 task group
就从未初始化 —— 此时**每一个**请求（含 initialize）都抛
`RuntimeError: Task group is not initialized. Make sure to use run().`，MCP 端点整体 500。

这个测试锁住的就是「session manager 真的被启动了」这件事：它必须走真实的
`interface.api.app`（含它的 lifespan），而不是把 MCP 子应用单独拿出来测 ——
单独测的话子应用自己的 lifespan 会被 TestClient 执行，恰好掩盖这个 bug。
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

# SSE 响应必须同时接受这两种 content-type，否则 streamable-http 会 406
ACCEPT = "application/json, text/event-stream"
HEADERS = {"Accept": ACCEPT, "Content-Type": "application/json"}

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}


@pytest.fixture
def client(monkeypatch):
    """真实的 interface.api.app（含它的 lifespan），关掉 DNS-rebinding 校验。

    每个用例**重建** MCP 的 app 与 session manager：`StreamableHTTPSessionManager.run()`
    每实例只能调用一次，复用会让第二个用例在进入 lifespan 时抛
    "run() can only be called once per instance"。重建必须走 api 模块自己的路径，
    这样 `_MCP_APP`（mount 出去的）与 lifespan 驱动的才是同一个实例。
    """
    from ethan.interface.routers import mcp_server as mcp_mod

    monkeypatch.setattr(
        mcp_mod.mcp_server.settings.transport_security,
        "enable_dns_rebinding_protection",
        False,
    )

    import ethan.interface.api as api_mod

    # 重建 MCP 子应用：session manager 的 .run() 每实例只能调一次，跨用例复用会抛
    # "run() can only be called once per instance"。这里换成新的 app 并同步 _MCP_APP，
    # 保证「mount 出去的」与「lifespan 驱动的」仍是同一个实例 —— 这正是被测的契约。
    mcp_mod.mcp_server._session_manager = None
    new_app = mcp_mod.get_mcp_app()
    monkeypatch.setattr(api_mod, "_MCP_APP", new_app)
    api_mod.app.router.routes = [
        r for r in api_mod.app.router.routes
        if getattr(r, "path", None) != "/mcp"
    ]
    api_mod.app.mount("/mcp", new_app)

    with TestClient(api_mod.app) as c:
        yield c


def test_initialize_succeeds(client):
    """这个请求在修复前必定 500（Task group is not initialized）。"""
    r = client.post("/mcp/", json=INITIALIZE, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert '"name":"Ethan"' in r.text
    assert "Task group is not initialized" not in r.text


def test_tools_list_exposes_ask_ethan(client):
    r = client.post(
        "/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=HEADERS
    )
    assert r.status_code == 200, r.text
    assert "ask_ethan" in r.text


def test_auth_middleware_401_without_or_with_wrong_key(client, monkeypatch):
    """配了 mcp_api_key 之后，无 token / 错 token → 401；正确 token → 200。"""
    from ethan.core.config import get_config

    cfg = get_config()
    monkeypatch.setattr(cfg.network, "mcp_api_key", "secret123", raising=False)

    r = client.post(
        "/mcp/", json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, headers=HEADERS
    )
    assert r.status_code == 401, r.text

    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        headers={**HEADERS, "Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401, r.text

    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
        headers={**HEADERS, "Authorization": "Bearer secret123"},
    )
    assert r.status_code == 200, r.text
    assert "ask_ethan" in r.text


def test_mcp_lifespan_is_entered_by_top_level_app(client):
    """直接断言 session manager 的 task group 已就绪。

    比只看 HTTP 200 更贴近根因：即便将来有人把 lifespan 又挪回子应用，只要没有顶层
    lifespan 驱动，这里就会是 False，而 HTTP 层则会 500。
    """
    from ethan.interface.routers import mcp_server as mcp_mod

    mgr = mcp_mod.mcp_server.session_manager
    assert mgr._task_group is not None, "session manager 的 task group 未初始化"


def test_ask_ethan_declares_read_only(client):
    """codex 等非交互客户端对未声明只读的工具会自动取消审批，表现为工具调不通。"""
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=HEADERS)
    tool = next(t for t in _parse_sse_all(r)[-1]["result"]["tools"] if t["name"] == "ask_ethan")
    assert tool["annotations"]["readOnlyHint"] is True
    assert "ctx" not in tool["inputSchema"]["properties"]


def test_ask_ethan_streams_progress_before_result(client, monkeypatch):
    """进度通知必须带 related_request_id 走本次 tools/call 的 SSE，先于最终 result 到达。"""
    from types import SimpleNamespace

    import ethan.interface.routers.deps as deps
    from ethan.providers.base import ToolEvent

    class _FakeAgent:
        session_id = None
        is_owner = True
        usage = SimpleNamespace(input_tokens=0, output_tokens=0, cache_tokens=0)

        async def stream_chat(self, messages):
            yield ToolEvent(tool_name="shell", args_summary="date", state="start", intent="查时间")
            yield ToolEvent(tool_name="shell", args_summary="date", state="done")
            yield "现在是凌晨两点。"

    monkeypatch.setattr(deps, "create_agent", lambda **kw: _FakeAgent())
    body = {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "ask_ethan", "arguments": {"prompt": "几点了"}, "_meta": {"progressToken": "p1"}},
    }
    r = client.post("/mcp/", json=body, headers=HEADERS)
    events = _parse_sse_all(r)
    methods = [e.get("method") or ("result" if "result" in e else "?") for e in events]
    assert methods[-1] == "result"
    progress = [e["params"]["message"] for e in events if e.get("method") == "notifications/progress"]
    assert any("shell" in m and "查时间" in m for m in progress)
    assert any("凌晨两点" in m for m in progress)
    assert "凌晨两点" in events[-1]["result"]["content"][0]["text"]


def _parse_sse_all(r) -> list[dict]:
    import json
    return [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
