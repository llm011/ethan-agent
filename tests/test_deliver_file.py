"""deliver_file 工具 + /api/files 路由测试。"""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.interface.routers import files as files_router
from ethan.tools.builtin.deliver_file import DeliverFileTool


def _run(coro):
    return asyncio.run(coro)


# ── deliver_file 工具 ────────────────────────────────────────────────

def test_deliver_file_jail_rejects_outside(tmp_path):
    t = DeliverFileTool()
    r = _run(t.run("/etc/passwd"))
    assert isinstance(r, str)
    assert "Deliver failed" in r


def test_deliver_file_not_found():
    t = DeliverFileTool()
    r = _run(t.run(str(Path.home() / "no_such_file_xyz.pptx")))
    assert "not found" in r


def test_deliver_file_ext_whitelist(tmp_path):
    t = DeliverFileTool()
    bad = Path("/tmp/deliver_test.exe")
    bad.write_bytes(b"x")
    r = _run(t.run(str(bad)))
    assert "unsupported file type" in r


def test_deliver_file_card_fields(tmp_path):
    t = DeliverFileTool()
    # 项目制 deck：pptx + deck.json + pages/
    d = Path("/tmp/deliver_proj")
    (d / "pages").mkdir(parents=True, exist_ok=True)
    (d / "deck.json").write_text(json.dumps({"version": 1, "theme": {}}), encoding="utf-8")
    (d / "pages" / "01_a.json").write_text(json.dumps({"id": "s1", "elements": []}), encoding="utf-8")
    (d / "pages" / "02_b.json").write_text(json.dumps({"id": "s2", "elements": []}), encoding="utf-8")
    pptx = d / "deliver_proj.pptx"
    pptx.write_bytes(b"x" * 2048)

    r = _run(t.run(str(pptx), title="测试报告"))
    assert r.cards and len(r.cards) == 1
    card = r.cards[0]
    assert card["type"] == "file"
    assert card["filename"] == "deliver_proj.pptx"
    assert card["title"] == "测试报告"
    assert card["kind"] == "pptx"
    assert card["size_kb"] == 2.0
    assert card["project_dir"] == str(d.resolve())
    assert card["page_count"] == 2


def test_deliver_file_non_project_no_preview():
    t = DeliverFileTool()
    f = Path("/tmp/deliver_plain.pptx")
    f.write_bytes(b"x" * 1024)
    r = _run(t.run(str(f)))
    card = r.cards[0]
    assert "project_dir" not in card
    assert "page_count" not in card


# ── /api/files 路由 ─────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(files_router.router, prefix="/api")
    # 跳过鉴权依赖
    app.dependency_overrides[files_router.verify_token] = lambda: "u1"
    app.dependency_overrides[files_router.verify_token_or_cookie] = lambda: "u1"
    # session 授权打桩：默认放行 /tmp 下一切（请求时才 glob，测试里先建文件再请求）
    async def _grants(session_id: str):
        tmp = Path("/tmp")
        files = {str(p.resolve()) for p in tmp.rglob("*") if p.is_file()}
        dirs = {str(p.resolve()) for p in tmp.rglob("*") if p.is_dir()}
        return files, dirs
    monkeypatch.setattr(files_router, "_session_grants", _grants)
    return TestClient(app)


def test_session_grants_from_real_store(tmp_path, monkeypatch):
    """_session_grants 从真实 SessionStore 的 cards 列派生授权集合。"""
    import ethan.memory.session as session_mod
    from ethan.memory.session import Message, SessionStore

    async def _go():
        store = SessionStore(db_path=tmp_path / "s.db")
        await store.init()
        s = await store.create(model="m")
        card = {"type": "file", "path": "/tmp/grants_a.pptx", "project_dir": "/tmp/grants_proj"}
        await store.save_message(s.id, Message(role="assistant", content="ok", cards=[card]))
        await store.save_message(s.id, Message(role="assistant", content="no cards"))
        return store, s.id

    store, sid = _run(_go())

    async def _fake_store():
        return store

    monkeypatch.setattr(session_mod, "get_session_store", _fake_store)
    files, dirs = _run(files_router._session_grants(sid))
    assert files == {str(Path("/tmp/grants_a.pptx").resolve())}
    assert dirs == {str(Path("/tmp/grants_proj").resolve())}

    # 未知 session → 403；空 session_id → 400
    with pytest.raises(Exception) as e1:
        _run(files_router._session_grants("no-such-session"))
    assert "403" in str(e1.value)
    with pytest.raises(Exception) as e2:
        _run(files_router._session_grants(""))
    assert "400" in str(e2.value)
    _run(store.close())  # aiosqlite 连接线程非 daemon，不关进程退不出


def test_grants_isolated_between_users(tmp_path, monkeypatch):
    """用户隔离：user B 的库没有 user A 的 session，拿 A 的 session_id + 路径也是 403。

    走真实 get_session_store（per-user db 路径由 ContextVar 里的 user_id 决定），
    不 mock _session_grants 本身，验证链路闭合。整个用例跑在单个事件循环里
    （get_session_store 的单例锁/连接与 loop 绑定，拆多个 asyncio.run 会挂）。
    """
    import ethan.core.paths as paths_mod
    import ethan.memory.session as session_mod
    from ethan.core.context import set_user_id
    from ethan.memory.session import Message, SessionStore

    # get_session_store 内部 from ethan.core.paths import user_sessions_db_path，
    # patch 模块属性即可按当前 ContextVar user 分发到不同库
    def _per_user_db() -> Path:
        from ethan.core.context import get_user_id
        uid = get_user_id() or "a"
        d = tmp_path / uid / "db"
        d.mkdir(parents=True, exist_ok=True)
        return d / "sessions.db"

    monkeypatch.setattr(paths_mod, "user_sessions_db_path", _per_user_db)

    async def _mk(db: Path, with_card: bool) -> str:
        store = SessionStore(db_path=db)
        await store.init()
        s = await store.create(model="m")
        if with_card:
            card = {"type": "file", "path": "/tmp/userA_secret.pptx"}
            await store.save_message(s.id, Message(role="assistant", content="ok", cards=[card]))
        return s.id

    async def _go():
        sid_a = await _mk(tmp_path / "a" / "db" / "sessions.db", True)
        await _mk(tmp_path / "b" / "db" / "sessions.db", False)

        set_user_id("a")  # user A 自己的库：能拿到 grants
        files, _ = await files_router._session_grants(sid_a)
        assert files == {str(Path("/tmp/userA_secret.pptx").resolve())}

        set_user_id("b")  # user B：同样的 session_id + 文件路径也查不到 → 403
        with pytest.raises(Exception) as e:
            await files_router._session_grants(sid_a)
        assert "403" in str(e.value)
        set_user_id("")

        # aiosqlite 连接线程非 daemon，不关 pytest 进程退不出
        for st in session_mod._session_stores.values():
            await st.close()
        session_mod._session_stores.clear()

    _run(_go())


def test_session_isolation(client, monkeypatch):
    """别的 session 没交付过这个文件 → 403。"""
    f = Path("/tmp/files_route_isolation.pptx")
    f.write_bytes(b"x")

    async def _grants(session_id: str):
        if session_id == "session-A":
            return {str(f.resolve())}, set()
        return set(), set()  # session-B 什么都没交付过

    monkeypatch.setattr(files_router, "_session_grants", _grants)
    ok = client.get(f"/api/files/download?path={f}&session_id=session-A")
    assert ok.status_code == 200
    denied = client.get(f"/api/files/download?path={f}&session_id=session-B")
    assert denied.status_code == 403
    missing = client.get(f"/api/files/download?path={f}")
    assert missing.status_code in (400, 403, 422)


def test_download_ok(client):
    f = Path("/tmp/files_route_test.pptx")
    f.write_bytes(b"pptx-bytes")
    res = client.get(f"/api/files/download?path={f}")
    assert res.status_code == 200
    assert res.content == b"pptx-bytes"
    assert "attachment" in res.headers.get("content-disposition", "")


def test_download_jail_rejects(client):
    res = client.get("/api/files/download?path=/etc/passwd")
    assert res.status_code in (400, 403)


def test_download_ext_rejects(client):
    f = Path("/tmp/files_route_test.exe")
    f.write_bytes(b"x")
    res = client.get(f"/api/files/download?path={f}")
    assert res.status_code == 400


def test_download_not_found(client, monkeypatch):
    # 已授权但文件被删 → 404；未授权的一律 403（不暴露文件存在性）
    ghost = Path("/tmp/files_route_ghost.pptx")

    async def _grants(session_id: str):
        return {str(ghost.resolve())}, set()

    monkeypatch.setattr(files_router, "_session_grants", _grants)
    res = client.get(f"/api/files/download?path={ghost}&session_id=s1")
    assert res.status_code == 404


def test_deck_returns_pages(client):
    d = Path("/tmp/files_deck_test")
    (d / "pages").mkdir(parents=True, exist_ok=True)
    (d / "deck.json").write_text(json.dumps({"version": 1, "theme": {"backgroundColor": "#fff"}}), encoding="utf-8")
    (d / "pages" / "01_a.json").write_text(json.dumps({"id": "s1", "elements": [{"id": "t1", "type": "text"}]}), encoding="utf-8")
    (d / "pages" / "02_b.json").write_text(json.dumps({"id": "s2", "elements": []}), encoding="utf-8")
    (d / "files_deck_test.pptx").write_bytes(b"x")

    res = client.get(f"/api/files/deck?path={d / 'files_deck_test.pptx'}")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "files_deck_test"
    assert data["page_count"] == 2
    assert data["pages"][0]["id"] == "s1"
    assert data["pptx_path"].endswith("files_deck_test.pptx")


def test_deck_not_project(client):
    d = Path("/tmp/files_not_deck")
    d.mkdir(exist_ok=True)
    res = client.get(f"/api/files/deck?path={d}")
    assert res.status_code == 404


def test_asset_only_under_assets(client):
    # assets/ 内的图片可以取
    d = Path("/tmp/files_asset_test")
    (d / "assets").mkdir(parents=True, exist_ok=True)
    (d / "assets" / "pic.png").write_bytes(b"png")
    res = client.get(f"/api/files/asset?path={d / 'assets' / 'pic.png'}")
    assert res.status_code == 200
    # assets/ 外的文件拒绝
    (d / "secret.png").write_bytes(b"x")
    res2 = client.get(f"/api/files/asset?path={d / 'secret.png'}")
    assert res2.status_code == 403


# ── 短期签名 URL（替代 ?token= 长效 token 直链）─────────────────────

@pytest.fixture
def signed_client(monkeypatch):
    """不覆盖鉴权依赖，走真实 verify_token_or_cookie + UserStore 打桩。"""
    import ethan.core.users as users_mod
    from ethan.core.users import UserConfig, UserStore

    store = UserStore([UserConfig(id="u1", web_token="tok-u1")])
    monkeypatch.setattr(users_mod, "get_user_store", lambda: store)

    app = FastAPI()
    app.include_router(files_router.router, prefix="/api")

    async def _grants(session_id: str):
        tmp = Path("/tmp")
        files = {str(p.resolve()) for p in tmp.rglob("*") if p.is_file()}
        return files, set()
    monkeypatch.setattr(files_router, "_session_grants", _grants)
    return TestClient(app)


def test_signed_url_unit(monkeypatch):
    import ethan.core.users as users_mod
    from ethan.core.signed_url import sign_path, verify_path_sig
    from ethan.core.users import UserConfig, UserStore

    store = UserStore([UserConfig(id="u1", web_token="tok-u1")])
    store.set_default_tokens(web_token="tok-default")
    monkeypatch.setattr(users_mod, "get_user_store", lambda: store)

    tok = sign_path("u1", "/tmp/a.pptx", now=1000)
    assert verify_path_sig("u1", "/tmp/a.pptx", tok, now=1000)
    assert not verify_path_sig("u1", "/tmp/a.pptx", tok, now=1000 + 601)  # 过期
    assert not verify_path_sig("u1", "/tmp/b.pptx", tok, now=1000)  # 路径不符
    assert not verify_path_sig("u2", "/tmp/a.pptx", tok, now=1000)  # 用户不符
    assert not verify_path_sig("u1", "/tmp/a.pptx", "garbage", now=1000)
    # default profile（user_id=""）用 default token 做 key
    tok0 = sign_path("", "/tmp/a.pptx", now=1000)
    assert verify_path_sig("", "/tmp/a.pptx", tok0, now=1000)
    # 无 token 的用户签不出来
    with pytest.raises(ValueError):
        sign_path("ghost", "/tmp/a.pptx")


def test_signed_url_flow(signed_client):
    f = Path("/tmp/signed_dl.pptx")
    f.write_bytes(b"pptx-bytes")
    # 1. 无 Bearer → /sign 401
    assert signed_client.post("/api/files/sign", json={"paths": [str(f)]}).status_code == 401
    # 2. Bearer 换签名
    r = signed_client.post("/api/files/sign", json={"paths": [str(f)]},
                           headers={"Authorization": "Bearer tok-u1"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == "u1"
    sig = body["signatures"][str(f)]
    # 3. 签名 URL 直接下载（无 header 无 cookie）
    d = signed_client.get(f"/api/files/download?path={f}&session_id=s1&user=u1&sig={sig}")
    assert d.status_code == 200 and d.content == b"pptx-bytes"
    # 4. 路径被改 / 换用户 → 401
    f2 = Path("/tmp/signed_dl2.pptx")
    f2.write_bytes(b"y")
    assert signed_client.get(f"/api/files/download?path={f2}&session_id=s1&user=u1&sig={sig}").status_code == 401
    assert signed_client.get(f"/api/files/download?path={f}&session_id=s1&user=u2&sig={sig}").status_code == 401
    # 5. ?token= 长效 token 通道已移除
    assert signed_client.get(f"/api/files/download?path={f}&session_id=s1&token=tok-u1").status_code == 401
