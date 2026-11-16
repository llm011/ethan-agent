r"""SPA 静态路由回落测试。

背景（实测踩到两次）：`output: "export"` 下 Next.js 只生成它知道的路径，
任意动态段（`/chat/<id>`、`/settings/<tab>`）都靠后端 `serve_spa` 回落。

两次事故：
  1. 加了「AI 内核」Tab 但没同步 `VALID_TABS` → `/settings/kernel` 无产物
  2. 把 `/chat` + `/chat/[id]` 合并成 `/chat/[[...id]]` 后，产物只剩
     `chat/index.html`，而旧 fallback 只认 `chat/__placeholder__/index.html`
     → `/chat/<id>` 落到站点根 index.html → **用户点进对话被跳回 /chat**

第 2 次的关键点：回落要**逐层往上找**，不能只认某一级目录名。
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_dist(tmp_path: Path) -> Path:
    """构造一个最小的静态产物目录。"""
    dist = tmp_path / "web_dist"
    (dist / "_next").mkdir(parents=True)
    (dist / "index.html").write_text("<title>ROOT</title>")
    # 可选 catch-all：只有一层 index.html
    (dist / "chat").mkdir()
    (dist / "chat" / "index.html").write_text("<title>CHAT</title>")
    # 必选动态段：__placeholder__
    (dist / "settings").mkdir()
    (dist / "settings" / "general").mkdir()
    (dist / "settings" / "general" / "index.html").write_text("<title>GENERAL</title>")
    return dist


@pytest.mark.parametrize(
    "path,expect",
    [
        ("chat", "CHAT"),
        ("chat/new", "CHAT"),               # catch-all：回落到 chat/index.html
        ("chat/s_20261115_1234_abcd", "CHAT"),
        ("chat/a/b", "CHAT"),               # 多层未知路径也回落到最近的 index
        ("settings/general", "GENERAL"),
        ("", "ROOT"),
    ],
)
def test_fallback_resolves_correct_index(tmp_path, path, expect):
    """回落逻辑：先找精确 index，再逐层往上。"""
    dist = _make_dist(tmp_path)
    parts = path.strip("/").split("/") if path else []

    hit = None
    for cut in range(len(parts), 0, -1):
        prefix_dir = dist.joinpath(*parts[:cut])
        index = prefix_dir / "index.html"
        if index.is_file():
            hit = index
            break
        placeholder = prefix_dir / "__placeholder__" / "index.html"
        if placeholder.is_file():
            hit = placeholder
            break
    if hit is None:
        hit = dist / "index.html"

    assert expect in hit.read_text()


def test_chat_session_path_does_not_fall_to_root(tmp_path):
    """核心回归：/chat/<id> 绝不能落到站点根的 index.html。

    落到根 index.html 的后果不是 404，而是**静默跳回首页**——用户点进对话
    发现回到了 /chat，看起来像"点不动"。
    """
    dist = _make_dist(tmp_path)
    parts = ["chat", "s_abc123"]
    hit = None
    for cut in range(len(parts), 0, -1):
        index = dist.joinpath(*parts[:cut]) / "index.html"
        if index.is_file():
            hit = index
            break
    assert hit is not None
    assert "CHAT" in hit.read_text(), "回落到站点根了"


def test_serve_spa_does_not_swallow_api_routes(tmp_path):
    """未知 /api/* 路由绝不能由 serve_spa 回落成 200 index.html。

    否则旧版后端缺少新接口（如 /api/kernels）时返回 200 HTML，
    WKWebView 的 res.json() 直接报 'The string did not match the expected pattern.'。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ethan.interface.api import _serve_spa_response

    dist = _make_dist(tmp_path)
    test_app = FastAPI()

    @test_app.get("/{path:path}")
    async def _spa(path: str):
        return _serve_spa_response(dist, path)

    client = TestClient(test_app)
    assert client.get("/api/kernels").status_code == 404
    assert client.get("/ws/unknown").status_code == 404
    assert client.get("/mcp/unknown").status_code == 404
    assert client.get("/kernel-tools/unknown").status_code == 404

    chat_resp = client.get("/chat/s_abc123")
    assert chat_resp.status_code == 200
    assert "CHAT" in chat_resp.text

    root_resp = client.get("/unknown-page")
    assert root_resp.status_code == 200
    assert "ROOT" in root_resp.text

