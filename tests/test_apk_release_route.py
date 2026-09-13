"""`/api/releases/android/{tag}/{file}` 路由测试。

这块最需要回归保护的是**路径校验**：tag 会被拼进文件路径，一个宽松的正则就等于
任意文件读取。所以下面的用例一半都在打它。

路由本身是「302 到 CDN」或「本地缓存直发」两种形态，都测。
"""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch, cache_dir: str = ""):
    """按指定缓存目录重新加载路由模块并挂到干净的 app 上。

    模块级读环境变量（和 `docs.py` 的 `_DOCS_DIR` 一样的做法），所以要 reload。
    """
    monkeypatch.setenv("ETHAN_APK_CACHE_DIR", cache_dir)
    from ethan.interface.routers import releases

    importlib.reload(releases)
    app = FastAPI()
    app.include_router(releases.router, prefix="/api")
    return TestClient(app, follow_redirects=False), releases


APK = "/api/releases/android/v0.5.259/app-release.apk"
SHA = "/api/releases/android/v0.5.259/app-release.apk.sha256"


# ── 无本地缓存 → 302 到 CDN ──────────────────────────────────────────

def test_no_cache_redirects_to_cdn(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get(APK)
    assert r.status_code == 302
    assert r.headers["location"] == (
        "https://cdn.lyb.pub/ethan/releases/android/v0.5.259/app-release.apk"
    )


def test_sha256_redirects_to_cdn(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get(SHA)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/v0.5.259/app-release.apk.sha256")


def test_public_no_auth_required(monkeypatch):
    """匿名可下载 —— 更新检查本就是匿名的，下载要登录会出现
    「检测到新版本但装不了」这种最糟糕的组合。"""
    client, _ = _client(monkeypatch)
    assert client.get(APK).status_code == 302   # 没有任何 Authorization header


def test_302_does_not_override_cache_control(monkeypatch):
    """302 响应不要自带 Cache-Control —— 缓存策略交给 Cloudflare，
    我们本地加的头和 CDN 的策略打架很难查。"""
    client, _ = _client(monkeypatch)
    assert "cache-control" not in {k.lower() for k in client.get(APK).headers}


def test_cdn_base_url_configurable(monkeypatch):
    monkeypatch.setenv("CDN_PUBLIC_URL", "https://mirror.example.com/")
    monkeypatch.setenv("ETHAN_APK_CACHE_DIR", "")
    from ethan.interface.routers import releases
    importlib.reload(releases)
    app = FastAPI()
    app.include_router(releases.router, prefix="/api")
    r = TestClient(app, follow_redirects=False).get(APK)
    # 末尾斜杠不能拼出双斜杠
    assert r.headers["location"] == (
        "https://mirror.example.com/ethan/releases/android/v0.5.259/app-release.apk"
    )


# ── 有本地缓存 → 直接下发 ────────────────────────────────────────────

def test_local_cache_served_with_correct_content_type(monkeypatch, tmp_path):
    d = tmp_path / "v0.5.259"
    d.mkdir()
    (d / "app-release.apk").write_bytes(b"PK\x03\x04fake apk")
    (d / "app-release.apk.sha256").write_text("a" * 64 + "  app-release.apk\n")

    client, _ = _client(monkeypatch, str(tmp_path))
    r = client.get(APK)
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04fake apk"
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    # 版本固化路径，内容永不改变 → 可长缓存
    assert "immutable" in r.headers["cache-control"]

    r = client.get(SHA)
    assert r.status_code == 200
    assert r.text.startswith("a" * 64)


def test_local_cache_falls_back_to_cdn_when_version_missing(monkeypatch, tmp_path):
    """缓存目录里没有这个版本 → 回到 302，而不是 404。

    否则「镜像还没同步完」会直接让用户更新不了，而 CDN 上其实是有的。
    """
    client, _ = _client(monkeypatch, str(tmp_path))
    assert client.get(APK).status_code == 302


# ── 路径校验（重点） ────────────────────────────────────────────────

@pytest.mark.parametrize("tag", [
    "..",
    "../..",
    "v1.0.0/../../etc/passwd",
    "v1.0.0%2f..%2f..%2fetc",
    "etc",
    "1.0.0",            # 缺 v 前缀
    "v1.0",             # 段数不够
    "v1.0.0.0",
    "latest",           # 可变 key 有意不支持（缓存污染风险）
    "",
])
def test_rejects_illegal_tag(monkeypatch, tmp_path, tag):
    (tmp_path / "secret.txt").write_text("SECRET")
    client, _ = _client(monkeypatch, str(tmp_path))
    r = client.get(f"/api/releases/android/{tag}/app-release.apk")
    assert r.status_code in (400, 404), f"tag={tag!r} 应该被拒，实际 {r.status_code}"
    assert b"SECRET" not in r.content


@pytest.mark.parametrize("filename", [
    "build.gradle",
    "app-release.apk.bak",
    "..",
    "../../../../etc/passwd",
])
def test_rejects_other_filenames(monkeypatch, tmp_path, filename):
    (tmp_path / "v0.5.259").mkdir()
    (tmp_path / "v0.5.259" / "app-release.apk").write_bytes(b"ok")
    (tmp_path / "secret.txt").write_text("SECRET")
    client, _ = _client(monkeypatch, str(tmp_path))
    r = client.get(f"/api/releases/android/v0.5.259/{filename}")
    assert r.status_code in (400, 404)
    assert b"SECRET" not in r.content


@pytest.mark.parametrize("tag", [
    "v0.5.259",
    "v1.2.3-rc1",
    "v1.2.3-beta.2",
    "v10.0.0+meta",
])
def test_accepts_wellformed_tags(monkeypatch, tag):
    client, _ = _client(monkeypatch)
    r = client.get(f"/api/releases/android/{tag}/app-release.apk")
    assert r.status_code == 302
    assert f"/{tag}/app-release.apk" in r.headers["location"]


def test_symlink_escape_is_blocked(monkeypatch, tmp_path):
    """缓存目录里有人放了个指向外部的软链 → `.resolve()` 之后就不在 base 下了。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.txt").write_text("SECRET")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "v0.5.259").symlink_to(outside)
    (outside / "app-release.apk").write_text("SECRET")

    client, _ = _client(monkeypatch, str(cache))
    r = client.get(APK)
    assert b"SECRET" not in r.content
