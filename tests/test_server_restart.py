# -*- coding: utf-8 -*-
"""`ethan server restart` 的可靠性保障。

两个回归点：

1. `launchctl load` 返回 0 只代表任务被登记，不代表 serve 起来了。旧实现直接
   打印「✓ 服务已重启」，用户看到成功提示但端口上是空的——线上表现就是
   「restart 提示成功，但访问失败」。现在必须等 /api/health 通过才算成功。
2. 老用户的 plist 是旧模板（缺 ETHAN_NO_WATCHDOG / ThrottleInterval /
   NumberOfFiles），`restart` 只看文件存不存在就原样 load 回去，新模板的修复
   永远落不到他们机器上。现在比对内容并重写。

此外 `restart` 重写 plist 时必须沿用**已安装**的可执行路径，不能在 worktree 里
把常驻服务绑到临时目录。
"""
from __future__ import annotations

import io

import pytest
from rich.console import Console

from ethan.interface.commands import server as server_mod


@pytest.fixture()
def plist(tmp_path, monkeypatch):
    """把 PLIST_PATH 指到临时文件，避免碰真实 ~/Library/LaunchAgents。"""
    path = tmp_path / "com.ethan.agent.plist"
    monkeypatch.setattr(server_mod, "PLIST_PATH", path)
    return path


def _quiet() -> Console:
    return Console(file=io.StringIO())


def _fake_exe(tmp_path, name="ethan"):
    exe = tmp_path / name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


# ── plist 渲染 / 过期检测 ──────────────────────────────────────────


def test_render_plist_contains_service_hardening():
    """模板必须带上这轮修复的守护进程配置。"""
    body = server_mod._render_plist()
    assert "<key>ETHAN_NO_WATCHDOG</key>" in body
    assert "<key>ThrottleInterval</key>" in body
    assert "<key>NumberOfFiles</key>" in body


def test_refresh_plist_noop_when_up_to_date(plist, tmp_path):
    """已是最新模板时不重写（避免每次 restart 都改文件）。"""
    exe = _fake_exe(tmp_path)
    plist.write_text(server_mod._render_plist(exe))

    assert server_mod._refresh_plist_if_stale(_quiet()) is False
    assert plist.read_text() == server_mod._render_plist(exe)


def test_refresh_plist_rewrites_stale_config(plist, tmp_path):
    """旧模板会被按新模板重写，且**保留**原来的可执行路径。"""
    exe = _fake_exe(tmp_path)
    stale = server_mod._render_plist(exe).replace(
        "<key>ETHAN_NO_WATCHDOG</key>", "<key>OLD_FLAG</key>"
    )
    plist.write_text(stale)

    assert server_mod._refresh_plist_if_stale(_quiet()) is True

    body = plist.read_text()
    assert "OLD_FLAG" not in body
    assert "ETHAN_NO_WATCHDOG" in body
    assert server_mod._installed_exe() == exe


def test_refresh_keeps_installed_exe_not_current_process(plist, tmp_path, monkeypatch):
    """在 worktree 里跑 restart 不能把常驻服务绑到 worktree 的 ethan。

    `_ethan_exe()` 返回的是**当前进程**的 ethan；模拟 worktree 场景，让
    它以另一个路径存在时，重写 plist 仍要沿用已安装 plist 里的路径。
    """
    installed = _fake_exe(tmp_path, "installed-ethan")
    worktree = _fake_exe(tmp_path, "worktree-ethan")
    plist.write_text(server_mod._render_plist(installed))
    monkeypatch.setattr(server_mod, "_ethan_exe", lambda: worktree)

    plist.write_text(plist.read_text().replace("ETHAN_NO_WATCHDOG", "X"))

    assert server_mod._refresh_plist_if_stale(_quiet()) is True
    assert server_mod._installed_exe() == installed
    assert "worktree-ethan" not in plist.read_text()


def test_refresh_noop_when_not_installed(plist):
    """没安装时不做任何事。"""
    assert not plist.exists()
    assert server_mod._refresh_plist_if_stale(_quiet()) is False


def test_installed_exe_none_when_path_missing(plist, tmp_path):
    """plist 里记录的可执行文件已被删除时返回 None，由调用方回退。"""
    gone = tmp_path / "gone-ethan"
    plist.write_text(server_mod._render_plist(gone))
    assert server_mod._installed_exe() is None


# ── 健康检查轮询 ────────────────────────────────────────────────────


def test_wait_for_health_returns_false_on_timeout():
    """没人监听的端口必须在超时后返回 False，而不是直接报成功。"""

    assert server_mod._wait_for_health("127.0.0.1", 1, timeout=0.5) is False


def test_wait_for_health_returns_true_when_up(monkeypatch):
    """健康检查 200 时立即返回 True。"""

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=None):
        assert url.endswith("/api/health")
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert server_mod._wait_for_health("127.0.0.1", 8900, timeout=5) is True


@pytest.mark.parametrize(
    "host,expected",
    [
        ("0.0.0.0", "127.0.0.1"),
        ("::", "127.0.0.1"),
        ("", "127.0.0.1"),
        ("127.0.0.1", "127.0.0.1"),
        # 绑到具体 LAN 地址时，探活也要跟着换，否则永远连不上
        ("192.168.1.10", "192.168.1.10"),
    ],
)
def test_service_endpoint_maps_wildcard_host(host, expected, monkeypatch):
    """通配地址换成回环；具体地址原样使用。"""

    class _Srv:
        pass

    srv = _Srv()
    srv.host = host
    srv.port = 8900

    class _Cfg:
        server = srv

    monkeypatch.setattr("ethan.core.config.get_config", lambda: _Cfg())
    assert server_mod._service_endpoint() == (expected, 8900)


def test_service_endpoint_falls_back_on_error(monkeypatch):
    """读配置失败时回退到本机 8900，不能直接抛。"""

    def boom():
        raise RuntimeError("config broken")

    monkeypatch.setattr("ethan.core.config.get_config", boom)
    assert server_mod._service_endpoint() == ("127.0.0.1", 8900)
