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


def test_organize_collapse_default_omitted(monkeypatch):
    """不传 collapse 时不带该字段,由扩展侧按 auto 处理。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "group", "title": "Work", "tabs": [102]}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops))

    _, params = hub.calls[0]
    assert "collapse" not in params, "未显式传 collapse 时不应塞默认值"


def test_organize_collapse_false_forwarded(monkeypatch):
    """collapse=false 应透传,让扩展侧跳过自动折叠。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "group", "title": "Work", "tabs": [102]}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops, collapse=False))

    _, params = hub.calls[0]
    assert params["collapse"] is False


def test_organize_collapse_true_forwarded(monkeypatch):
    """collapse=true 应透传（强制折叠含活跃组）。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "group", "title": "Work", "tabs": [102]}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops, collapse=True))

    _, params = hub.calls[0]
    assert params["collapse"] is True



def test_organize_collapse_string_forwarded(monkeypatch):
    """'auto'/'none' 字符串要能透传（schema 只声明 boolean 时模型表达不出来）。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "ungroup_all", "title": "Work"}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops, collapse="none"))

    _, params = hub.calls[0]
    assert params["collapse"] == "none"


def test_organize_collapse_auto_string_forwarded(monkeypatch):
    """显式传 'auto' 与不传等价，但应当原样透传而不是被丢掉。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "ungroup_all", "title": "Work"}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops, collapse="auto"))

    _, params = hub.calls[0]
    assert params["collapse"] == "auto"


def test_organize_collapse_quoted_bool_forwarded(monkeypatch):
    """schema 同时声明了 string 类型,客户端可能发 "true"/"false" 字符串。

    工具侧原样透传(不在这里做类型判断),由扩展侧的 normalizeTabOrganizeParams
    归一成布尔 —— 那一侧同样接受 "true"/"false"（见 browser-extension 的
    normalize-tabs 单测）。这里只钉住「工具不会把它丢掉或改写成别的值」。
    """
    for raw in ("true", "false"):
        set_session_id("e1")
        hub = _FakeHub(ORGANIZE_RESULT)
        _patch(monkeypatch, hub, SessionMap())

        ops = [{"op": "group", "title": "Work", "tabs": [102]}]
        asyncio.run(BrowserTabTool().run(action="organize", ops=ops, collapse=raw))

        _, params = hub.calls[0]
        assert params["collapse"] == raw, f"{raw!r} 应原样透传到扩展侧"


def test_organize_rest_op_forwarded(monkeypatch):
    """rest op 原样透传,工具侧不自己判断该不该休息(判据在扩展里)。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "rest", "tabs": [102, 103]}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops))

    method, params = hub.calls[0]
    assert method == "tabs.organize"
    assert params["ops"] == [{"op": "rest", "tabs": [102, 103]}]


def test_organize_rest_auto_op_forwarded(monkeypatch):
    """rest_auto(整组按时间休息)也要透传。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "rest_auto", "groupId": 5}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops))

    _, params = hub.calls[0]
    assert params["ops"] == [{"op": "rest_auto", "groupId": 5}]


def test_organize_rest_mode_default_omitted(monkeypatch):
    """不传 rest_mode 时不带该字段,由扩展侧读 popup 开关(默认开启)。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "rest_auto", "groupId": 5}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops))

    _, params = hub.calls[0]
    assert "restMode" not in params, "未显式传 rest_mode 时不应塞默认值"


def test_organize_rest_mode_off_forwarded(monkeypatch):
    """rest_mode='off' 应当以 restMode 键传给扩展。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "rest_auto", "groupId": 5}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops, rest_mode="off"))

    _, params = hub.calls[0]
    assert params["restMode"] == "off"


def test_organize_rest_mode_yesterday_forwarded(monkeypatch):
    """显式传 'yesterday' 时原样透传,不被丢掉。"""
    set_session_id("e1")
    hub = _FakeHub(ORGANIZE_RESULT)
    _patch(monkeypatch, hub, SessionMap())

    ops = [{"op": "rest_auto", "groupId": 5}]
    asyncio.run(BrowserTabTool().run(action="organize", ops=ops, rest_mode="yesterday"))

    _, params = hub.calls[0]
    assert params["restMode"] == "yesterday"
