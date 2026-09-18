"""浏览器 session 收尾清理:用户选「保留」时不得丢掉后端绑定。

现场(会话 s_20260918_0950_2183):
  _close_browser_sessions 在 finally 里无条件 smap.unbind(bsid),
  于是用户点「保留」后,扩展侧仍追踪该 session,但 ethan 的 session_map 已经
  忘了它。下一轮 browser_session(list) 返回 {"sessions": []},agent 判定
  「没有可用 session」→ 去 attach/create → 在多客户端下撞上「请先 use 选一个」,
  整个标签整理流程空转 30 步,报出的却是「该 browser session 不属于当前对话」。
"""
from __future__ import annotations

import asyncio

from ethan.browser import hub as hub_mod
from ethan.browser import session_map as smap_mod
from ethan.browser.session_map import SessionMap


class _FakeHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def connected(self) -> bool:
        return True

    async def call(self, method, params, *, client_name=None, browser_session_id=None, timeout=30):
        self.calls.append((method, client_name or ""))
        if method == "sessions.list":
            return {"sessions": [{"sessionId": "s-1", "title": "T", "tabCount": 2}]}
        return {"ok": True}


def _patch(monkeypatch, hub: _FakeHub, smap: SessionMap) -> None:
    monkeypatch.setattr(hub_mod, "get_hub", lambda: hub)
    monkeypatch.setattr(smap_mod, "get_session_map", lambda: smap)


def _run_cleanup(session_id: str, action: str, monkeypatch, smap: SessionMap, hub: _FakeHub):
    """跑一次 _close_browser_sessions，并让确认卡片立即返回 action。"""
    from ethan.browser import cleanup_confirm
    from ethan.interface.routers import producers

    async def fake_await_confirm(req, timeout=None):
        cleanup_confirm._PENDING.pop(req.request_id, None)
        return action

    class _Req:
        request_id = "rid-1"

    def fake_create_confirm(ethan_session_id, sessions):
        # create_confirm 是同步函数（非 async），这里必须同步返回
        return _Req()

    monkeypatch.setattr(cleanup_confirm, "await_confirm", fake_await_confirm)
    monkeypatch.setattr(cleanup_confirm, "create_confirm", fake_create_confirm)
    monkeypatch.setattr(
        cleanup_confirm, "TIMEOUT_SECONDS", 120, raising=False,
    )
    asyncio.run(producers._close_browser_sessions(session_id))


def test_keep_preserves_binding(monkeypatch):
    """用户选「保留」→ 绑定必须留着，否则下一轮 ethan 查不到自己的 session。"""
    hub = _FakeHub()
    smap = SessionMap()
    smap.bind("s-1", "e1", client_name="browser-work")
    _patch(monkeypatch, hub, smap)

    _run_cleanup("e1", "keep", monkeypatch, smap, hub)

    assert "s-1" in smap.list_for("e1"), "保留后绑定丢了 → 下一轮 list 会是空的"
    assert smap.get_client("s-1") == "browser-work"
    assert smap.is_keep_alive("s-1") is True, "保留的 session 应标记 keep_alive，避免下轮又弹卡片"
    # 保留不应调 session_close（不能真关掉用户要留的 tab）
    assert not [m for m, _ in hub.calls if m == "sessions.close"]


def test_close_unbinds_and_calls_close(monkeypatch):
    """用户选「关闭」→ 真关 tab group 且解绑（与扩展状态一致）。"""
    hub = _FakeHub()
    smap = SessionMap()
    smap.bind("s-1", "e1", client_name="browser-work")
    _patch(monkeypatch, hub, smap)

    _run_cleanup("e1", "close", monkeypatch, smap, hub)

    assert smap.list_for("e1") == []
    assert "sessions.close" in [m for m, _ in hub.calls]


def test_keep_then_list_still_visible(monkeypatch):
    """回归：保留后本对话仍能列出该 session（这是空转的直接原因）。"""
    hub = _FakeHub()
    smap = SessionMap()
    smap.bind("s-1", "e1", client_name="browser-work")
    _patch(monkeypatch, hub, smap)

    _run_cleanup("e1", "keep", monkeypatch, smap, hub)

    owned = smap.owned_by_client("e1")
    assert owned.get("browser-work") == ["s-1"]
