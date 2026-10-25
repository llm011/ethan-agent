"""聊天附件（非图片上传）的存储、归属与访问契约。

锁住的是「上传 → 落盘 → 归属会话 → 落库 → GET 回读 → 直链下载」这条链，
历史上断在中间好几处（前端没传 files、后端不认字段、上传落在系统临时目录），
所以这里从最底层的 store 到 HTTP 路由逐段验证：

- `store_upload` 落在 `user_uploads_dir()` 下，而不是 /tmp
- 文件名清洗：路径分隔符、控制字符不会穿透成目录
- `/api/upload` 超限 413、返回的 rel_path 能直接拼 `/api/assets/uploads/...`
- `/api/chat` 落库时把 `_pending/` 里的文件搬进 `<session_id>/`
- `GET /sessions/{id}` 回读 files（含 size / rel_path）
- `/api/assets/uploads/...` 越权会话 404、`..` 穿越 400
- 删除会话连带清理 uploads/<session_id>/
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.core import uploads as uploads_mod
from ethan.interface.routers import assets as assets_mod
from ethan.interface.routers import chat as chat_mod
from ethan.interface.routers import sessions as sessions_mod
from ethan.interface.routers import settings as settings_mod
from ethan.interface.routers.deps import verify_token
from ethan.memory.session import SessionStore
from ethan.providers.base import Message


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """把 profile 数据根指到 tmp：uploads/ 与 sessions.db 都落在这里。

    paths.py 在 import 时就把 CONFIG_DIR 从环境变量读进来了，所以只改 env 没用，
    必须同时改 `ethan.core.config.CONFIG_DIR` 与 paths.py 里的同名导入——
    否则会往真实的 ~/.ethan/uploads 里写（测试污染用户数据）。
    """
    import ethan.core.config as config_mod
    import ethan.core.paths as paths_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "CONFIG_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "sessions.db")

    async def _init():
        await s.init()

    asyncio.run(_init())
    yield s
    asyncio.run(s.close())


@pytest.fixture()
def store_handle(store):
    async def _fake_store():
        return store

    return _fake_store


@pytest.fixture()
def client(data_dir, store_handle, monkeypatch):
    monkeypatch.setattr(settings_mod, "get_session_store", store_handle, raising=False)
    # chat 路由用的是 `from ethan.memory.session import get_session_store` 的模块级名字
    monkeypatch.setattr(chat_mod, "get_session_store", store_handle)
    monkeypatch.setattr(sessions_mod, "get_session_store", store_handle)
    # assets 路由在函数体内 `from ethan.memory.session import get_session_store`，
    # 每次调用都现取模块属性 → 必须打在源头模块上
    import ethan.memory.session as session_mod

    monkeypatch.setattr(session_mod, "get_session_store", store_handle)
    # 建 agent 必然失败（本机 provider 配置与测试无关）：用户消息在它之前落库，
    # 失败只会让请求返回错误，不影响本文件要验证的落库/归属逻辑。
    monkeypatch.setattr(
        chat_mod, "create_agent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("provider not configured"))
    )

    async def _uid():
        return ""

    app = FastAPI()
    app.include_router(chat_mod.router)
    app.include_router(settings_mod.router)
    app.include_router(sessions_mod.router)
    app.include_router(assets_mod.router)
    app.dependency_overrides[verify_token] = _uid
    app.dependency_overrides[assets_mod._verify_token_or_cookie] = _uid
    return TestClient(app, raise_server_exceptions=False)


# ── 存储层 ────────────────────────────────────────────────────────


def test_store_upload_lands_in_profile_uploads(data_dir):
    from ethan.core.paths import user_uploads_dir

    root = user_uploads_dir()
    meta = uploads_mod.store_upload(b"# hi", "需求 文档.md", session_id="s_a")
    assert (root / "s_a").is_dir()
    assert meta["rel_path"] == f"s_a/{meta['rel_path'].split('/', 1)[1]}"
    assert meta["path"].startswith(str(root / "s_a"))
    assert meta["size"] == 4
    assert meta["media_type"] == "text/markdown"
    # 正文只在文件里，元数据里不带正文
    with open(meta["path"], "rb") as fh:
        assert fh.read() == b"# hi"


def test_store_upload_without_session_goes_pending(data_dir):
    meta = uploads_mod.store_upload(b"x", "a.txt")
    assert meta["rel_path"].startswith(f"{uploads_mod.PENDING_DIRNAME}/")


def test_safe_name_strips_separators_and_control_chars():
    assert "/" not in uploads_mod.safe_name("../../etc/passwd")
    assert uploads_mod.safe_name("a\\b\x00c.txt") == "a_b_c.txt"
    assert uploads_mod.safe_name("") == "upload"


def test_upload_file_path_rejects_traversal(data_dir):
    meta = uploads_mod.store_upload(b"x", "a.txt", session_id="s_a")
    stored = meta["rel_path"].split("/", 1)[1]
    assert uploads_mod.upload_file_path(f"s_a/{stored}") is not None
    assert uploads_mod.upload_file_path(f"s_a/../../evil.txt") is None
    assert uploads_mod.upload_file_path("../outside.txt") is None


# ── 上传路由 ──────────────────────────────────────────────────────


def test_upload_route_returns_rel_path(client, data_dir):
    res = client.post("/upload", files={"file": ("说明.md", b"# title", "text/markdown")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["filename"] == "说明.md"
    assert body["size"] == 7
    assert body["rel_path"].startswith(f"{uploads_mod.PENDING_DIRNAME}/")
    from ethan.core.paths import user_uploads_dir

    assert body["path"].startswith(str(user_uploads_dir()))


def test_upload_route_rejects_oversize(client, monkeypatch):
    monkeypatch.setattr(uploads_mod, "MAX_UPLOAD_BYTES", 10)
    res = client.post("/upload", files={"file": ("big.bin", b"x" * 100, "application/octet-stream")})
    assert res.status_code == 413


def test_download_route_serves_with_original_filename(client, data_dir):
    up = client.post("/upload", files={"file": ("报告.md", b"# hi", "text/markdown")}).json()
    res = client.get(f"/assets/uploads/{up['rel_path']}")
    assert res.status_code == 200
    assert res.content == b"# hi"
    # 落盘名带 uuid 前缀，下载时还原成原始文件名（非 ASCII 走 RFC 5987 编码）
    from urllib.parse import unquote

    assert "报告.md" in unquote(res.headers.get("content-disposition", ""))


def test_download_route_with_unknown_session_404(client, data_dir):
    up = client.post("/upload", files={"file": ("a.md", b"x", "text/markdown")}).json()
    stored = up["rel_path"].split("/", 1)[1]
    assert client.get(f"/assets/uploads/s_not_exist/{stored}").status_code == 404


def test_download_route_rejects_traversal(client, data_dir):
    assert client.get("/assets/uploads/s_a/..%2f..%2fetc%2fpasswd").status_code in (400, 404)


# ── 落库 / 回读 ───────────────────────────────────────────────────


def test_store_roundtrip_files(store):
    """save_message → load 的 files 必须原样回来（列追加在末尾，不能错位）。"""
    files = [{"name": "a.md", "path": "/x/a.md", "rel_path": "s1/a.md", "size": 3, "media_type": "text/markdown"}]

    async def _run():
        await store.create_with_id("s1", model="m", source="web", mode="")
        await store.save_message("s1", Message(role="user", content="q", images=["/img.png"], files=files))
        return await store.load("s1")

    s = asyncio.run(_run())
    assert s.messages[0].files == files
    # 原有字段不能被新列挤歪
    assert s.messages[0].images == ["/img.png"]
    assert s.messages[0].content == "q"


def test_chat_adopts_pending_upload(store, client, data_dir, monkeypatch):
    """上传（无 session）→ /chat 落库：文件搬进 <session_id>/，元数据写进 messages.files。"""
    up = client.post("/upload", files={"file": ("计划.md", b"# plan", "text/markdown")}).json()

    async def _mk():
        await store.create_with_id("s_chat", model="m", source="web", mode="")

    asyncio.run(_mk())
    res = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "看看这个", "files": [{"name": "计划.md", "path": up["path"], "rel_path": up["rel_path"]}]}],
            "session_id": "s_chat",
            "stream": False,
        },
    )
    # 只要用户消息先落库即可：建 agent 成败取决于本机配置，不在此断言
    assert res.status_code < 600, res.text

    detail = client.get("/sessions/s_chat").json()
    assert detail["messages"], (res.status_code, res.text[:300], detail)
    user = detail["messages"][0]
    assert len(user["files"]) == 1
    f = user["files"][0]
    assert f["name"] == "计划.md"
    assert f["rel_path"].startswith("s_chat/")
    assert f["size"] == 6
    from ethan.core.paths import user_uploads_dir

    assert (user_uploads_dir() / f["rel_path"]).is_file()
    # _pending 里的原文件已被搬走
    assert not (user_uploads_dir() / up["rel_path"]).exists()
    # 直链能下载
    assert client.get(f"/assets/uploads/{f['rel_path']}").status_code == 200


def test_adopt_uploads_works_with_only_path(store, data_dir):
    """前端早期版本只传 {name, path}（不带 rel_path）：靠 path 反推 rel_path 并完成归位。"""
    meta = uploads_mod.store_upload(b"# hi", "计划.md")
    adopted = uploads_mod.adopt_uploads("s_only_path", [{"name": "计划.md", "path": meta["path"]}])
    assert len(adopted) == 1
    assert adopted[0]["rel_path"] == f"s_only_path/{Path(meta['path']).name}"
    assert Path(adopted[0]["path"]).parent.name == "s_only_path"


def test_chat_drops_files_that_no_longer_exist(store, client, data_dir, monkeypatch):
    async def _mk():
        await store.create_with_id("s_gone", model="m", source="web", mode="")

    asyncio.run(_mk())
    client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "q", "files": [{"name": "ghost.md", "path": "/nope/ghost.md"}]}],
            "session_id": "s_gone",
        },
    )
    detail = client.get("/sessions/s_gone").json()
    # 宁可少一个 chip，也不要留一个必 404 的链接
    assert detail["messages"][0]["files"] == []


def test_delete_session_cleans_uploads(store, data_dir):
    async def _run():
        await store.create_with_id("s_del", model="m", source="web", mode="")
        return await store.delete("s_del")

    meta = uploads_mod.store_upload(b"x", "a.md", session_id="s_del")
    from ethan.core.paths import user_uploads_dir

    assert (user_uploads_dir() / meta["rel_path"]).is_file()
    assert asyncio.run(_run()) is True
    assert not (user_uploads_dir() / "s_del").exists()
