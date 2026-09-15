"""多浏览器客户端连接同一 server 时的稳定性测试。

背景:两台浏览器装同一路扩展连同一 server 时操作非常不稳定,三个根因:
  1. 同名 last-wins 互相顶替——两台机器抢同一个名字,谁也用不成;
     现在靠 instanceId 区分「同一浏览器重连」(顶替)和「两台撞名」(拒绝新连接)。
  2. resolve_client 把「只有一个在线」的临时选择持久化,那台掉线后静默漂到
     另一台;现在临时选中不落 _session_clients,歧义始终显式暴露。
  3. session_list 只查活跃客户端,另一台浏览器里的 session 不可见 → agent
     误判不存在而重复 create,留下重复 tab group;现在全端查询合并去重。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from ethan.browser.hub import BrowserClientNameConflictError, BrowserError, BrowserHub
from ethan.browser.session_map import SessionMap
from ethan.browser.ws_route import _normalize_instance_id
from ethan.core.context import set_session_id
from ethan.tools.builtin import browser as browser_mod
from ethan.tools.builtin.browser import (
    BrowserClientTool,
    BrowserSessionTool,
    _clients_hint,
    _describe_clients,
    _list_sessions_all_clients,
)


class _FakeWs:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


async def _roundtrip(hub: BrowserHub, conn, result: dict) -> dict:
    """向 conn 发一次 call 并立刻以假扩展身份回包,验证该连接确实可用。"""
    task = asyncio.create_task(hub.call("ping", {}, client_name=conn.name))
    for _ in range(3):
        await asyncio.sleep(0)
    ((req_id, _),) = conn.pending.items()
    hub.on_message(conn, json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}))
    return await task


class _FakeHub:
    """browser.py 用的 hub 替身:list_clients/resolve_client 可用,call 读预设响应。"""

    def __init__(self, responses: dict, single: str | None = None):
        self._responses = responses
        self.single = single  # resolve_client 的返回值(模拟「只有一个在线」)
        self.calls: list[tuple[str, str]] = []

        class _C:
            closed = False

        # 探针路径(_require_owned_or_recover)会遍历 _conns,按 responses 的 key 造一份
        self._conns = {n: _C() for n in responses}

    def list_clients(self) -> list[dict]:
        return [{"name": n, "connected": True} for n in sorted(self._responses)]

    def resolve_client(self, ethan_session_id: str) -> str | None:
        return self.single

    def get_active_client(self, ethan_session_id: str) -> str | None:
        return None

    async def call(self, method: str, params: dict, *, client_name: str | None = None,
                   browser_session_id: str | None = None, timeout: float = 30) -> dict:
        self.calls.append((method, client_name or ""))
        res = self._responses[client_name or ""]
        if isinstance(res, Exception):
            raise res
        if callable(res):
            return res(method, params)
        return res


# ── hub.attach:撞名拒绝 vs 同浏览器重连 ─────────────────────────


def test_attach_same_instance_evicts_old():
    """同名且 instanceId 相同 = 同一浏览器重连 → last-wins 顶掉旧连接。"""

    async def _run():
        hub = BrowserHub()
        old = await hub.attach(_FakeWs(), "mac", instance_id="inst-1")
        # 旧连接上挂一个 in-flight 请求,断开后应被 fail 成可重试错误
        fut = asyncio.get_running_loop().create_future()
        old.pending[7] = fut

        new = await hub.attach(_FakeWs(), "mac", instance_id="inst-1")

        assert old.closed and old.evicted.is_set()
        assert fut.done() and isinstance(fut.exception(), BrowserError)
        assert fut.exception().retryable
        assert hub._conns["mac"] is new and not new.closed
        assert new.instance_id == "inst-1"

    asyncio.run(_run())


def test_attach_conflicting_instance_rejects_new_and_keeps_old():
    """两台不同浏览器撞同一个名 → 拒绝新连接,旧连接继续服务。"""

    async def _run():
        hub = BrowserHub()
        old = await hub.attach(_FakeWs(), "mac", instance_id="inst-A")

        with pytest.raises(BrowserClientNameConflictError):
            await hub.attach(_FakeWs(), "mac", instance_id="inst-B")

        # 旧连接没被顶掉,依然能正常收发
        assert hub._conns["mac"] is old and not old.closed
        assert await _roundtrip(hub, old, {"ok": 1}) == {"ok": 1}

    asyncio.run(_run())


def test_attach_legacy_missing_instance_id_still_evicts():
    """旧版扩展没有 instanceId → 维持 last-wins,不因升级破坏重连。"""

    async def _run():
        hub = BrowserHub()
        old = await hub.attach(_FakeWs(), "mac", instance_id="inst-A")
        new = await hub.attach(_FakeWs(), "mac", instance_id="")
        assert old.closed and hub._conns["mac"] is new

    asyncio.run(_run())


def test_attach_different_names_coexist():
    """不同名字的两个浏览器共存,互不影响。"""

    async def _run():
        hub = BrowserHub()
        await hub.attach(_FakeWs(), "mac", instance_id="inst-A")
        await hub.attach(_FakeWs(), "pc", instance_id="inst-B")
        assert {c["name"] for c in hub.list_clients()} == {"mac", "pc"}

    asyncio.run(_run())


def test_normalize_instance_id():
    assert _normalize_instance_id("abc") == "abc"
    assert _normalize_instance_id("  x  ") == "x"
    assert _normalize_instance_id("x" * 200) == "x" * 128
    for bad in (None, 123, "", "   "):
        assert _normalize_instance_id(bad) == ""


# ── resolve_client:临时选中不持久化 ──────────────────────────────


def test_resolve_single_client_transient_not_persisted():
    """只有一个客户端在线时自动用它,但不写入绑定——那台掉线换台新的,
    resolve 立刻跟随,不会残留指向已死浏览器的绑定。"""

    async def _run():
        hub = BrowserHub()
        conn_a = await hub.attach(_FakeWs(), "a")
        assert hub.resolve_client("s1") == "a"
        assert hub.get_active_client("s1") is None  # 未显式 use → 不落盘

        await hub.detach(conn_a)
        await hub.attach(_FakeWs(), "b")
        assert hub.resolve_client("s1") == "b"

    asyncio.run(_run())


def test_resolve_explicit_use_persists_and_wins():
    """显式 use 过的客户端优先,且再连一个新浏览器不会改变选择。"""

    async def _run():
        hub = BrowserHub()
        await hub.attach(_FakeWs(), "a")
        await hub.attach(_FakeWs(), "b")
        assert hub.set_active_client("s1", "b")
        assert hub.resolve_client("s1") == "b"
        await hub.attach(_FakeWs(), "c")
        assert hub.resolve_client("s1") == "b"

    asyncio.run(_run())


def test_resolve_bound_client_survives_offline_and_reconnect():
    """use 绑定的浏览器瞬时掉线(扩展 SW 回收很常见):跳过但不删绑定,掉线期间
    单客户端在线时临时顶上;重连后绑定自动恢复——use 的选择不能活不过一次断线。"""

    async def _run():
        hub = BrowserHub()
        conn_a = await hub.attach(_FakeWs(), "a")
        await hub.attach(_FakeWs(), "b")
        hub.set_active_client("s1", "a")

        await hub.detach(conn_a)
        # 掉线期间:跳过 a;只剩 b 在线 → 临时用 b;绑定仍保留
        assert hub.resolve_client("s1") == "b"
        assert hub.get_active_client("s1") == "a"

        # 同名重连(同一浏览器恢复)→ 绑定继续生效,无需重新 use
        await hub.attach(_FakeWs(), "a")
        assert hub.resolve_client("s1") == "a"

    asyncio.run(_run())


def test_resolve_ambiguous_returns_none():
    """多个在线且未显式 use → None,由调用方提示 agent 询问用户。"""

    async def _run():
        hub = BrowserHub()
        await hub.attach(_FakeWs(), "a")
        await hub.attach(_FakeWs(), "b")
        assert hub.resolve_client("s1") is None

    asyncio.run(_run())


# ── session_map.owned_by_client ──────────────────────────────────


def test_owned_by_client_groups_by_client():
    smap = SessionMap()
    smap.bind("bs1", "e1", client_name="a")
    smap.bind("bs2", "e1", client_name="a")
    smap.bind("bs3", "e1", client_name="b")
    smap.bind("bs4", "e2", client_name="a")  # 别的对话的,不算
    smap.bind("bs5", "e1")  # 老数据无 client,单独成 "" 组
    assert smap.owned_by_client("e1") == {"a": ["bs1", "bs2"], "b": ["bs3"], "": ["bs5"]}
    assert smap.owned_by_client("e2") == {"a": ["bs4"]}
    assert smap.owned_by_client("missing") == {}


# ── browser.py:全端 session 列表 / 客户端描述 / use 汇报 ──────────


def _patch(monkeypatch, hub, smap) -> None:
    monkeypatch.setattr(browser_mod, "get_hub", lambda: hub)
    monkeypatch.setattr(browser_mod, "get_session_map", lambda: smap)


def test_list_sessions_merges_all_clients_and_tags(monkeypatch):
    """两台浏览器各有 session → 全部可见且带 client 标注,重复 id 去重。"""

    async def _run():
        hub = _FakeHub({
            "a": {"sessions": [{"sessionId": "s1"}, {"sessionId": "s2"}]},
            "b": {"sessions": [{"sessionId": "s2"}, {"sessionId": "s3"}]},
        })
        _patch(monkeypatch, hub, SessionMap())
        out = await _list_sessions_all_clients()
        by_id = {s["sessionId"]: s for s in out["sessions"]}
        assert sorted(by_id) == ["s1", "s2", "s3"]
        assert by_id["s2"]["client"] == "a"  # 先查到的客户端保留
        assert {c for _, c in hub.calls} == {"a", "b"}  # 两端都查了
        assert "_errors" not in out

    asyncio.run(_run())


def test_list_sessions_collects_errors(monkeypatch):
    """一端查询失败不吞掉另一端结果,失败原因进 _errors。"""

    async def _run():
        hub = _FakeHub({
            "a": {"sessions": [{"sessionId": "s1"}]},
            "b": RuntimeError("boom"),
        })
        _patch(monkeypatch, hub, SessionMap())
        out = await _list_sessions_all_clients()
        assert [s["sessionId"] for s in out["sessions"]] == ["s1"]
        assert out["_errors"] == ["b: boom"]

    asyncio.run(_run())


def test_list_sessions_no_clients_raises(monkeypatch):
    async def _run():
        _patch(monkeypatch, _FakeHub({}), SessionMap())
        with pytest.raises(BrowserError):
            await _list_sessions_all_clients()

    asyncio.run(_run())


def test_describe_clients_enriches_owned_and_active_tab(monkeypatch):
    """list/status 能分清哪台是哪台:本对话的 session 归属 + 各端当前页面。"""

    async def _run():
        set_session_id("e1")
        hub = _FakeHub({
            "a": {"tabs": [{"active": True, "title": "GitHub PR",
                            "url": "https://github.com/x/y/pull/9"}]},
            "b": {"tabs": [{"active": False, "title": "后台页", "url": "https://x.com/"}]},
        })
        smap = SessionMap()
        smap.bind("bs1", "e1", client_name="a")
        _patch(monkeypatch, hub, smap)
        clients = await _describe_clients()
        by_name = {c["name"]: c for c in clients}
        assert by_name["a"]["owned_sessions"] == ["bs1"]
        assert by_name["a"]["active_tab"] == {"title": "GitHub PR", "host": "github.com"}
        # b 的 active tab 不在前台 → 无 active_tab 字段,但 owned_sessions 空列表仍在
        assert "active_tab" not in by_name["b"]
        assert by_name["b"]["owned_sessions"] == []

    asyncio.run(_run())


def test_clients_hint_points_at_owner(monkeypatch):
    hint = _clients_hint([
        {"name": "a", "owned_sessions": ["bs1"]},
        {"name": "b", "owned_sessions": []},
    ])
    assert "'a'" in hint and "b" in hint  # 指明 session 在 a 上,b 需先 use


def test_use_reports_bindings_and_persists(monkeypatch):
    """use 切换后汇报两侧 session 分布;绑定本身持久化生效。"""

    async def _run():
        set_session_id("e1")
        hub = BrowserHub()
        smap = SessionMap()
        smap.bind("bs1", "e1", client_name="a")
        smap.bind("bs2", "e1", client_name="b")
        smap.bind("bs3", "e1", client_name="b")
        await hub.attach(_FakeWs(), "a", instance_id="inst-A")
        await hub.attach(_FakeWs(), "b", instance_id="inst-B")
        _patch(monkeypatch, hub, smap)

        out = json.loads(await BrowserClientTool().run(action="use", name="b"))
        assert out["ok"] is True and out["active"] == "b"
        assert out["bound_sessions_here"] == ["bs2", "bs3"]
        assert out["bound_sessions_elsewhere"] == {"a": ["bs1"]}
        assert "旧客户端" in out["_hint"] and "a 1 个" in out["_hint"]
        assert hub.get_active_client("e1") == "b"  # 显式 use 才持久化

    asyncio.run(_run())


def test_use_unknown_client_lists_available(monkeypatch):
    async def _run():
        set_session_id("e1")
        hub = BrowserHub()
        await hub.attach(_FakeWs(), "a")
        _patch(monkeypatch, hub, SessionMap())
        out = json.loads(await BrowserClientTool().run(action="use", name="nope"))
        assert out["ok"] is False
        assert out["available"] == ["a"]

    asyncio.run(_run())


def test_create_binds_same_client_it_routed_to(monkeypatch):
    """create 的路由和绑定必须是同一个 client:绑定成空/绑错浏览器后,
    后续操作要么失路由、要么报「session not found」。"""

    async def _run():
        set_session_id("e1")
        hub = _FakeHub(
            {"a": {"created": True, "session": {"sessionId": "s-new"}}},
            single="a",  # 模拟「只有一个在线」的临时选中
        )
        smap = SessionMap()
        _patch(monkeypatch, hub, smap)
        out = json.loads(await BrowserSessionTool().run(action="create", url="https://x.com"))
        assert out.get("created") is True
        # 新 session 绑给了实际路由到的浏览器,而不是空串
        assert smap.get_client("s-new") == "a"
        assert smap.get_owner("s-new") == "e1"

    asyncio.run(_run())


def test_orphan_binding_is_rehomed_by_probe(monkeypatch):
    """绑定成 "" 的 session:不按当前活跃客户端瞎猜(猜错浏览器扩展会报
    session not found),而是探针查清真实所在并回填绑定。"""

    async def _run():
        set_session_id("e1")
        # session 物理在 b 上;当前临时选中是 a —— 旧逻辑会错误路由到 a
        hub = _FakeHub({
            "a": lambda m, p: {"sessions": []},
            "b": lambda m, p: {"sessions": [{"sessionId": "s-orphan"}]},
        }, single="a")
        smap = SessionMap()
        smap.bind("s-orphan", "e1", client_name="")
        _patch(monkeypatch, hub, smap)

        await browser_mod._call("session_list", {}, browser_session_id="s-orphan")
        assert smap.get_client("s-orphan") == "b"  # 探针回填
        # 后续调用直接路由到 b,不再走探针
        hub.calls.clear()
        await browser_mod._call("session_list", {}, browser_session_id="s-orphan")
        assert [c for _, c in hub.calls] == ["b"]

    asyncio.run(_run())
