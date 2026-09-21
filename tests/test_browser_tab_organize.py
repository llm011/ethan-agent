"""browser_tab(action="organize") 的行为测试。

验证点:
1. organize 发出 tabs.organize RPC
2. ops 正确透传
3. 缺少 ops 参数时直接返回错误,不调用 hub
4. organize 不需要 session 参数
"""
from __future__ import annotations

import asyncio
import json

from ethan.browser.session_map import SessionMap
from ethan.core.context import set_session_id
from ethan.tools.builtin import browser as browser_mod
from ethan.tools.builtin.browser import BrowserTabTool


class _FakeHub:
    def __init__(self, response):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

        class _C:
            closed = False

        self._conns = {"browser-1": _C()}

    def list_clients(self):
        return [{"name": "browser-1", "connected": True}]

    def resolve_client(self, ethan_session_id):
        return "browser-1"

    def get_active_client(self, ethan_session_id):
        return "browser-1"

    async def call(self, method, params, *, client_name=None, browser_session_id=None, timeout=30):
        self.calls.append((method, params))
        if callable(self._response):
            return self._response(method, params)
        return self._response


def _patch(monkeypatch, hub, smap):
    monkeypatch.setattr(browser_mod, "get_hub", lambda: hub)
    monkeypatch.setattr(browser_mod, "get_session_map", lambda: smap)


ORGANIZE_RESULT = {
    "organized": True,
    "applied": {
        "closed": [101],
        "grouped": [{"title": "Work", "groupId": 5, "tabs": [102, 103]}],
        "ungrouped": [],
    },
}


def test_organize_sends_tabs_organize_rpc(monkeypatch):
    """organize action 应发送 tabs.organize RPC 调用。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "close", "tabs": [101]}]
    out = json.loads(asyncio.run(BrowserTabTool().run(action="organize", ops=ops)))

    assert out.get("organized") is True
    assert len(hub.calls) == 1
    method, params = hub.calls[0]
    assert method == "tabs.organize"


def test_organize_ops_forwarded_correctly(monkeypatch):
    """ops 参数应原样传给 RPC。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [
        {"op": "close", "tabs": [101]},
        {"op": "group", "title": "Work", "tabs": [102, 103], "color": "blue"},
    ]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops))

    _, params = hub.calls[0]
    assert params["ops"] == ops


def test_organize_missing_ops_returns_error_without_hub_call(monkeypatch):
    """缺少 ops 参数时应直接返回错误,不调用 hub。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    out = json.loads(asyncio.run(BrowserTabTool().run(action="organize")))

    assert "error" in out
    assert len(hub.calls) == 0, "缺 ops 时不应调用 hub"


def test_organize_does_not_require_session(monkeypatch):
    """organize 不需要 session 参数,不应被 _missing_session 拦截。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "close", "tabs": [101]}]
    # 故意不传 session
    out = json.loads(asyncio.run(BrowserTabTool().run(action="organize", ops=ops)))

    # 不应含「需要 session」的错误
    assert "需要 session" not in json.dumps(out, ensure_ascii=False)
    assert out.get("organized") is True


def test_organize_ungroup_op(monkeypatch):
    """ungroup op 正确透传。"""
    set_session_id("e1")
    ungroup_result = {
        "organized": True,
        "applied": {"closed": [], "grouped": [], "ungrouped": [201, 202]},
    }
    hub = _FakeHub(ungroup_result)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "ungroup", "tabs": [201, 202]}]
    out = json.loads(asyncio.run(BrowserTabTool().run(action="organize", ops=ops)))

    assert out.get("organized") is True
    assert out["applied"]["ungrouped"] == [201, 202]
    _, params = hub.calls[0]
    assert params["ops"] == ops


def test_organize_empty_ops_returns_error(monkeypatch):
    """空列表 ops 也应返回错误,不调用 hub。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    out = json.loads(asyncio.run(BrowserTabTool().run(action="organize", ops=[])))

    assert "error" in out
    assert len(hub.calls) == 0
