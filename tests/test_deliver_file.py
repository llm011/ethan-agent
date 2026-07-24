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
def client():
    app = FastAPI()
    app.include_router(files_router.router, prefix="/api")
    # 跳过鉴权依赖
    app.dependency_overrides[files_router.verify_token] = lambda: "u1"
    app.dependency_overrides[files_router.verify_token_or_cookie] = lambda: "u1"
    return TestClient(app)


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


def test_download_not_found(client):
    res = client.get(f"/api/files/download?path={Path.home() / 'no_such_xyz.pptx'}")
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
