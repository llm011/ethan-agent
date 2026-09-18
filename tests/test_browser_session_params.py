"""缺 session 参数 / 多客户端下 attach 的行为。

两个回归点(来自会话 s_20260918_0950_2183):
  1. 模型调 browser_tab(action=close, tab=...) 时漏传 session,过去报
     「该 browser session 不属于当前对话」——把「漏传参数」误导成「归属出错」,
     模型据此去 attach_current / 切换浏览器,空转 30 步。
  2. attach 用 _call("session_list") 做存在性校验,该方法走 resolve_client,
     两个客户端在线且未 use 时直接抛错,把 attach 整个堵死。
"""
from __future__ import annotations

import asyncio
import json

from ethan.browser.session_map import SessionMap
from ethan.core.context import set_session_id
from ethan.tools.builtin import browser as browser_mod
from ethan.tools.builtin.browser import (
    BrowserPageTool,
    BrowserSessionTool,
    BrowserTabTool,
)


class _FakeHub:
    def __init__(self, responses: dict, single=None):
        self._responses = responses
        self.single = single
        self.calls: list[tuple[str, str]] = []

        class _C:
            closed = False

        self._conns = {n: _C() for n in responses}

    def list_clients(self):
        return [{"name": n, "connected": True} for n in sorted(self._responses)]

    def resolve_client(self, ethan_session_id):
        return self.single

    def get_active_client(self, ethan_session_id):
        return None

    async def call(self, method, params, *, client_name=None, browser_session_id=None, timeout=30):
        self.calls.append((method, client_name or ""))
        res = self._responses[client_name or ""]
        if callable(res):
            return res(method, params)
        return res


def _patch(monkeypatch, hub, smap):
    monkeypatch.setattr(browser_mod, "get_hub", lambda: hub)
    monkeypatch.setattr(browser_mod, "get_session_map", lambda: smap)


TWO_CLIENTS = {"browser-work": {"sessions": []}, "browser-life": {"sessions": []}}


def test_missing_session_reports_missing_not_ownership(monkeypatch):
    """漏传 session 应提示补参数,而不是报归属错误。"""
    set_session_id("e1")
    _patch(monkeypatch, _FakeHub(TWO_CLIENTS), SessionMap())

    out = json.loads(asyncio.run(BrowserTabTool().run(action="close", tab="1341423282")))
    assert "不属于当前对话" not in json.dumps(out, ensure_ascii=False)
    assert "session" in out["error"]
    assert "browser_session" in out["_hint"]  # 给出取 id 的下一步


def test_missing_session_guards_all_requiring_actions(monkeypatch):
    """browser_tab/browser_page/browser_session 的各类需要 session 的动作都要被拦。"""
    set_session_id("e1")
    _patch(monkeypatch, _FakeHub(TWO_CLIENTS), SessionMap())

    async def check():
        for tool, kw in [
            (BrowserTabTool(), {"action": "close", "tab": "1"}),
            (BrowserTabTool(), {"action": "activate", "tab": "1"}),
            (BrowserTabTool(), {"action": "open", "url": "https://x.com"}),
            (BrowserPageTool(), {"action": "snapshot"}),
            (BrowserPageTool(), {"action": "click", "ref": "r1"}),
            (BrowserSessionTool(), {"action": "close"}),
            (BrowserSessionTool(), {"action": "rename", "title": "t"}),
        ]:
            out = json.loads(await tool.run(**kw))
            assert "需要 session 参数" in out.get("error", ""), f"{kw} 未被拦下: {out}"

    asyncio.run(check())


def test_sessionless_actions_still_pass_through(monkeypatch):
    """user_list / find_tab / session list 不需要 session,不能被误拦。"""
    set_session_id("e1")
    hub = _FakeHub({
        "browser-work": lambda m, p: {"tabs": [{"tabId": 1, "active": True, "url": "https://a.com"}]},
        "browser-life": lambda m, p: {"tabs": []},
    }, single="browser-work")
    _patch(monkeypatch, hub, SessionMap())

    async def check():
        out = json.loads(await BrowserTabTool().run(action="user_list"))
        assert "error" not in out and out.get("tabs") is not None
        out = json.loads(await BrowserTabTool().run(action="find_tab", url="https://a.com"))
        assert "error" not in out

    asyncio.run(check())


def test_attach_works_with_two_clients_online(monkeypatch):
    """两个客户端在线且未 use 时,attach 仍应可用,并绑定到 session 真正的归属端。"""
    set_session_id("e1")
    hub = _FakeHub({
        "browser-work": lambda m, p: {"sessions": [{"sessionId": "s-work"}]},
        "browser-life": lambda m, p: {"sessions": [{"sessionId": "s-life"}]},
    }, single=None)  # 未选活跃客户端 → 旧代码在此必然抛错
    smap = SessionMap()
    _patch(monkeypatch, hub, smap)

    out = json.loads(asyncio.run(BrowserSessionTool().run(action="attach", session="s-life")))
    assert out.get("attached") is True
    assert smap.get_client("s-life") == "browser-life"  # 按实际归属端,而非活跃客户端
    assert smap.get_owner("s-life") == "e1"


def test_attach_rejects_unknown_session(monkeypatch):
    """不存在的 session 仍要拒绝,不能假成功。"""
    set_session_id("e1")
    hub = _FakeHub({
        "browser-work": lambda m, p: {"sessions": []},
        "browser-life": lambda m, p: {"sessions": []},
    }, single=None)
    _patch(monkeypatch, hub, SessionMap())

    out = json.loads(asyncio.run(BrowserSessionTool().run(action="attach", session="s-nope")))
    assert "error" in out
    assert "不存在" in out["error"]
