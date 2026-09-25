# -*- coding: utf-8 -*-
"""用户头像 / 显示名 的设置与读写回归测试。

覆盖三层：
1. profile.py 的显示名锚点读写（含老文件无锚点、overwrite 模式、清空）
2. assets.py 的头像存取（解码校验、旧文件清理、URL 拼装）
3. settings 路由的四个接口（上传/清除/读身份/写名字）

头像存的是「用户级资产」，显示名存在画像文档里 —— 这两个分开存是刻意的，
测试里也分开断言，避免以后有人把其中一处改成另一处的存储方式。
"""
from __future__ import annotations

import asyncio
import io

import pytest

# ── 测试辅助 ──────────────────────────────────────────────────────


def _png_bytes(w: int = 64, h: int = 64, color=(255, 0, 0, 255)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def profile_env(tmp_path, monkeypatch):
    """把 CONFIG_DIR 指到 tmp_path，返回 (paths, user_id)。

    paths 函数的返回值都是 CONFIG_DIR 下的路径，改掉 CONFIG_DIR 就等于给
    每次测试一个干净的数据目录 —— 绝不碰开发机上真实的 ~/.ethan。
    """
    import ethan.core.assets as assets_mod
    import ethan.core.config as config_mod
    import ethan.core.paths as paths

    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    # assets.py 在 import 时把 ASSETS_DIR / IMAGES_DIR 算成了模块常量，
    # 只改 CONFIG_DIR 不会生效，必须一并 patch。
    images_dir = tmp_path / "assets" / "images"
    monkeypatch.setattr(assets_mod, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(assets_mod, "IMAGES_DIR", images_dir)
    return paths, ""


# ── profile.py：显示名锚点 ────────────────────────────────────────


def test_display_name_roundtrip_on_fresh_profile():
    import tempfile
    from pathlib import Path

    from ethan.core.services.profile import SECTIONS, ensure_profile, get_display_name, set_display_name

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "user_profile.md"
        content = ensure_profile(p)

        # 新画像没有显示名，读到空串（而不是异常或 None）
        assert get_display_name(content) == ""

        content = set_display_name(content, "小明")
        assert get_display_name(content) == "小明"
        # 写进的是「基础特征」章节，且没有破坏别的 section
        assert "## 基础特征" in content
        assert "- 显示名：小明" in content
        for s in SECTIONS:
            assert f"## {s}" in content


def test_display_name_overwrite_does_not_duplicate():
    import tempfile
    from pathlib import Path

    from ethan.core.services.profile import ensure_profile, get_display_name, set_display_name

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "user_profile.md"
        content = ensure_profile(p)

        content = set_display_name(content, "小明")
        content = set_display_name(content, "小红")

        assert get_display_name(content) == "小红"
        # 关键：改名字不能攒出第二条锚点，否则读取端永远取到旧值
        assert content.count("- 显示名：") == 1


def test_display_name_clear_removes_bullet():
    import tempfile
    from pathlib import Path

    from ethan.core.services.profile import ensure_profile, get_display_name, set_display_name

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "user_profile.md"
        content = ensure_profile(p)
        content = set_display_name(content, "小明")
        content = set_display_name(content, "")

        assert get_display_name(content) == ""
        assert "显示名：" not in content
        # section 本身不能被清掉
        assert "## 基础特征" in content


def test_display_name_tolerates_legacy_profile_without_anchor():
    """老用户的画像没有「显示名」这条，第一次写入要能补上而不是报错。"""
    from ethan.core.services.profile import get_display_name, set_display_name

    legacy = "# 用户画像\n\n## 基础特征\n- 喜欢喝咖啡\n\n## 心理与情绪\n"
    content = set_display_name(legacy, "老王")

    assert get_display_name(content) == "老王"
    assert "- 喜欢喝咖啡" in content  # 原有内容不能丢
    assert "- 显示名：老王" in content


def test_display_name_collapses_newlines():
    """名字里带换行会把 bullet 拆断、污染后续解析，必须折叠成空格。"""
    import tempfile
    from pathlib import Path

    from ethan.core.services.profile import ensure_profile, get_display_name, set_display_name

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "user_profile.md"
        content = set_display_name(ensure_profile(p), "小\n明  阿")

        assert get_display_name(content) == "小 明 阿"


def test_display_name_survives_consolidation_rewrite():
    """每日 consolidation 会整段重写 section，锚点 bullet 不能被当成噪声丢掉。"""
    from ethan.core.services.profile import (
        PROFILE_GROUP_IDENTITY,
        get_display_name,
        section_bullets,
        set_display_name,
        set_section_bullets,
    )

    content = "# 用户画像\n\n## 基础特征\n"
    content = set_display_name(content, "小明")
    # 模拟 daily consolidation：读 bullets → 压缩 → 写回（保留全部 bullet）
    bullets = section_bullets(content, "基础特征")
    content = set_section_bullets(content, "基础特征", bullets)

    assert get_display_name(content) == "小明"
    assert "基础特征" in PROFILE_GROUP_IDENTITY


# ── assets.py：头像存取 ───────────────────────────────────────────


def test_save_avatar_writes_png_and_returns_url(profile_env):
    from ethan.core.assets import avatar_url, save_avatar

    assert avatar_url() == ""  # 未设置时不返回悬空 URL

    url = save_avatar(_png_bytes(1024, 1024), "image/png")

    assert url == "images/img_avatar.png"
    assert avatar_url() == url
    from ethan.core.assets import avatar_path

    assert avatar_path().is_file()


def test_save_avatar_downscales_to_bound(profile_env):
    from PIL import Image

    from ethan.core.assets import AVATAR_MAX_DIM, avatar_path, save_avatar

    save_avatar(_png_bytes(2048, 1024), "image/png")

    with Image.open(avatar_path()) as img:
        assert max(img.size) == AVATAR_MAX_DIM


def test_save_avatar_replaces_previous_file(profile_env):
    from ethan.core.assets import AVATAR_PREFIX, IMAGES_DIR, save_avatar

    save_avatar(_png_bytes(), "image/png")
    # 手造一个历史遗留的其他扩展名，模拟旧版本或手工放进去的文件
    stale = IMAGES_DIR / f"{AVATAR_PREFIX}.jpeg"
    stale.write_bytes(_png_bytes())

    save_avatar(_png_bytes(), "image/png")

    leftovers = [p.name for p in IMAGES_DIR.glob(f"{AVATAR_PREFIX}.*")]
    assert leftovers == ["img_avatar.png"], leftovers


def test_save_avatar_rejects_non_image(profile_env):
    from ethan.core.assets import avatar_url, save_avatar

    with pytest.raises(ValueError):
        save_avatar(b"this is not an image", "text/plain")

    # 拒绝之后不能留下半个文件
    assert avatar_url() == ""


def test_save_avatar_rejects_empty_and_oversized(profile_env):
    from ethan.core.assets import MAX_AVATAR_BYTES, save_avatar

    with pytest.raises(ValueError):
        save_avatar(b"", "image/png")
    with pytest.raises(ValueError):
        save_avatar(b"\x00" * (MAX_AVATAR_BYTES + 1), "image/png")


def test_save_avatar_normalizes_gif_to_png(profile_env):
    """GIF/SVG 这类可能带动画或脚本的格式统一转 PNG，不原样落到静态目录。"""
    from PIL import Image

    from ethan.core.assets import avatar_path, save_avatar

    buf = io.BytesIO()
    Image.new("P", (32, 32)).save(buf, format="GIF")

    url = save_avatar(buf.getvalue(), "image/gif")

    assert url.endswith(".png")
    assert avatar_path().suffix == ".png"


def test_delete_avatar_clears_url(profile_env):
    from ethan.core.assets import avatar_url, delete_avatar, save_avatar

    save_avatar(_png_bytes(), "image/png")
    assert delete_avatar() is True
    assert avatar_url() == ""
    # 幂等：没有头像时再删一次不该炸
    assert delete_avatar() is False


def test_avatar_is_per_profile(profile_env, monkeypatch):
    """头像按 profile 隔离 —— 两个用户的头像不能互相覆盖。"""
    import ethan.core.assets as assets_mod
    import ethan.core.config as config_mod
    import ethan.core.paths as paths
    from ethan.core.assets import avatar_url, save_avatar
    from ethan.core.context import ETHAN_USER_ID

    tmp = paths.CONFIG_DIR

    token = ETHAN_USER_ID.set("")
    try:
        save_avatar(_png_bytes(color=(255, 0, 0, 255)), "image/png")
        a_url = avatar_url()
    finally:
        ETHAN_USER_ID.reset(token)

    # 切到命名 profile：CONFIG_DIR 不变，但数据根目录换成 profiles/<id>/
    monkeypatch.setattr(assets_mod, "IMAGES_DIR", tmp / "profiles" / "u2" / "assets" / "images")
    token = ETHAN_USER_ID.set("u2")
    try:
        assert avatar_url() == ""  # 新 profile 还没有头像
        save_avatar(_png_bytes(color=(0, 255, 0, 255)), "image/png")
        b_url = avatar_url()
    finally:
        ETHAN_USER_ID.reset(token)

    assert a_url == b_url == "images/img_avatar.png"
    assert config_mod.CONFIG_DIR == tmp  # 确认测试没有把 CONFIG_DIR 改乱


# ── settings 路由 ─────────────────────────────────────────────────


def _client(monkeypatch, user_id: str = ""):
    """构造一个只挂了 settings 路由的 TestClient，鉴权直接放行。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ethan.interface.routers import settings as settings_router
    from ethan.interface.routers.deps import verify_token

    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: user_id
    return TestClient(app)


def test_identity_endpoint_defaults_to_empty(profile_env, monkeypatch):
    client = _client(monkeypatch)
    body = client.get("/api/user/identity").json()

    assert body["avatar_url"] == ""
    assert body["display_name"] == ""


def test_upload_avatar_then_identity_reports_it(profile_env, monkeypatch):
    client = _client(monkeypatch)
    res = client.put("/api/user/avatar", files={"file": ("a.png", _png_bytes(), "image/png")})

    assert res.status_code == 200, res.text
    assert res.json()["avatar_url"] == "images/img_avatar.png"
    assert client.get("/api/user/identity").json()["avatar_url"] == "images/img_avatar.png"


def test_upload_avatar_rejects_non_image(profile_env, monkeypatch):
    client = _client(monkeypatch)
    res = client.put("/api/user/avatar", files={"file": ("evil.txt", b"nope", "text/plain")})

    assert res.status_code == 400


def test_delete_avatar_endpoint(profile_env, monkeypatch):
    client = _client(monkeypatch)
    client.put("/api/user/avatar", files={"file": ("a.png", _png_bytes(), "image/png")})

    res = client.patch("/api/user/avatar", json={"avatar_url": ""})

    assert res.status_code == 200
    assert client.get("/api/user/identity").json()["avatar_url"] == ""


def test_delete_avatar_endpoint_rejects_setting_a_url(profile_env, monkeypatch):
    """只允许清空：改头像必须走上传，避免后端把任意 URL 当头像存下来。"""
    client = _client(monkeypatch)
    res = client.patch("/api/user/avatar", json={"avatar_url": "https://evil.example/x.png"})

    assert res.status_code == 400


def test_name_endpoint_roundtrip_and_validation(profile_env, monkeypatch):
    client = _client(monkeypatch)

    res = client.patch("/api/user/name", json={"display_name": "  小明  "})
    assert res.status_code == 200
    assert res.json()["display_name"] == "小明"
    assert client.get("/api/user/identity").json()["display_name"] == "小明"

    # 超长名字会挤坏气泡布局，必须在写进去之前拒掉
    assert client.patch("/api/user/name", json={"display_name": "x" * 65}).status_code == 400

    # 清空
    assert client.patch("/api/user/name", json={"display_name": "  "}).status_code == 200
    assert client.get("/api/user/identity").json()["display_name"] == ""


def test_name_is_written_into_profile_document(profile_env, monkeypatch):
    """设置页与气泡读的是同一份数据 —— 名字必须落在 user_profile.md 里。"""
    from ethan.core.paths import user_profile_path

    client = _client(monkeypatch)
    client.patch("/api/user/name", json={"display_name": "小明"})

    content = user_profile_path().read_text(encoding="utf-8")
    assert "- 显示名：小明" in content


def test_profile_get_includes_identity_fields(profile_env, monkeypatch):
    """老前端只读 content；新前端要 display_name/avatar_url —— 三个字段都得在。"""
    client = _client(monkeypatch)
    client.put("/api/user/avatar", files={"file": ("a.png", _png_bytes(), "image/png")})
    client.patch("/api/user/name", json={"display_name": "小明"})

    body = client.get("/api/settings/profile").json()

    assert body["avatar_url"] == "images/img_avatar.png"
    assert body["display_name"] == "小明"
    assert "## 基础特征" in body["content"]


def test_named_profile_falls_back_to_config_name(profile_env, monkeypatch):
    """命名 profile 在画像里没写名字时，回落 config.yaml 的 name，而不是空。"""
    import ethan.core.users as users_mod

    class _Store:
        def get_user(self, uid):
            assert uid == "u2"  # 只有命名 profile 才查 config

            class _U:
                name = "阿强"

            return _U()

    # 路由内部是 `from ethan.core.users import get_user_store`（函数内延迟 import），
    # 所以必须 patch 源模块的属性，patch 路由模块上的名字不会生效。
    monkeypatch.setattr(users_mod, "get_user_store", lambda: _Store())

    body = _client(monkeypatch, user_id="u2").get("/api/user/identity").json()

    assert body["display_name"] == "阿强"


def test_default_profile_does_not_query_user_store(profile_env, monkeypatch):
    """default profile（user_id=""）在 config.yaml 里没有条目，不该去查它。"""
    import ethan.core.users as users_mod

    class _Store:
        def get_user(self, uid):
            raise AssertionError("default profile must not look up the user store")

    monkeypatch.setattr(users_mod, "get_user_store", lambda: _Store())

    body = _client(monkeypatch).get("/api/user/identity").json()

    assert body["display_name"] == ""


# ── 并发安全 ──────────────────────────────────────────────────────


def test_concurrent_avatar_uploads_leave_exactly_one_file(profile_env):
    """并发上传不能留下两个头像文件（否则 _find_avatar 取哪个看 mtime，行为不定）。"""
    from ethan.core.assets import AVATAR_PREFIX, IMAGES_DIR, save_avatar

    def _do(i: int) -> None:
        save_avatar(_png_bytes(color=(i % 255, 0, 0, 255)), "image/png")

    async def _main() -> None:
        await asyncio.gather(*(asyncio.to_thread(_do, i) for i in range(4)))

    asyncio.run(_main())

    leftovers = [p.name for p in IMAGES_DIR.glob(f"{AVATAR_PREFIX}.*")]
    assert leftovers == ["img_avatar.png"], leftovers
