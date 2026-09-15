# -*- coding: utf-8 -*-
"""watchdog 复用判定必须带端口（PR #341 review 回归）。

背景：`ensure_watchdog_running()` 原本只看 PID 文件在不在，存在就直接复用。
端口写死 8900 的年代这没问题（复用到的一定盯 8900）；端口可配之后，
「已有 watchdog」不等于「盯的是我要的端口」——把端口改到 8981 时，之前为
8900 拉起的 watchdog 还活着，直接复用会让它继续 ping 8900：健康的服务被判
「死亡」反复 kill/restart，而恰好占用 8900 的别的实例会被 `_kill_server` 误杀。

修法：watchdog 启动时把端口写进 `watchdog.port`，复用前比对；不一致就换掉。
这些用例锁住「比对」这段逻辑，以及 PID 文件格式没被污染。
"""
from __future__ import annotations

import pytest

from ethan import watchdog as w


@pytest.fixture()
def pid_dir(tmp_path, monkeypatch):
    """把 watchdog 的 PID/端口文件指到临时目录，避免动到真实 /tmp/ethan。"""
    monkeypatch.setattr(w, "_PID_DIR", tmp_path)
    monkeypatch.setattr(w, "SERVER_PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(w, "WATCHDOG_PID_FILE", tmp_path / "watchdog.pid")
    monkeypatch.setattr(w, "WATCHDOG_PORT_FILE", tmp_path / "watchdog.port")
    return tmp_path


def test_read_port_none_when_file_missing(pid_dir):
    """没有端口文件（老版本遗留 / 首次）→ None，不抛异常。"""
    assert w._read_watchdog_port() is None


def test_read_port_none_when_file_garbage(pid_dir):
    """端口文件内容损坏 → None，不能让 watchdog 检查把服务搞挂。"""
    (pid_dir / "watchdog.port").write_text("not-a-port")
    assert w._read_watchdog_port() is None


def test_write_read_roundtrip(pid_dir):
    w._write_watchdog_port(8981)
    assert w._read_watchdog_port() == 8981


def test_pid_file_stays_bare_int(pid_dir, monkeypatch):
    """watchdog.pid 必须仍是「一行整数」——别处按 int() 读，混入端口会解析炸。"""
    import os

    w._write_pid(w.WATCHDOG_PID_FILE)
    raw = w.WATCHDOG_PID_FILE.read_text().strip()
    assert raw == str(os.getpid())
    assert int(raw) == os.getpid()


def test_ensure_same_port_reuses_without_killing(pid_dir, monkeypatch):
    """端口一致 → 直接复用，不该去 kill 它。"""
    # 用当前进程假装是那个 watchdog（_pid_alive 对活着的 pid 返回 True）
    w._write_pid(w.WATCHDOG_PID_FILE)
    w._write_watchdog_port(8981)

    killed = []
    monkeypatch.setattr(w, "_stop_watchdog", lambda pid: killed.append(pid))

    w.ensure_watchdog_running(port=8981)
    assert killed == []
    assert w.WATCHDOG_PID_FILE.exists()


def test_ensure_different_port_replaces_watchdog(pid_dir, monkeypatch):
    """端口不一致 → 换掉旧 watchdog（这是本次修复的核心回归点）。"""
    w._write_pid(w.WATCHDOG_PID_FILE)
    w._write_watchdog_port(8900)  # 旧的盯 8900

    killed = []
    monkeypatch.setattr(w, "_stop_watchdog", lambda pid: killed.append(pid))
    spawned = []
    monkeypatch.setattr(w.subprocess, "Popen", lambda *a, **kw: spawned.append(a) or type(
        "P", (), {"pid": 4242}
    )())

    w.ensure_watchdog_running(port=8981)
    assert len(killed) == 1, "盯错端口的 watchdog 必须被换掉"
    assert len(spawned) == 1, "换掉后要拉起盯新端口的 watchdog"


def test_ensure_unknown_port_replaces_watchdog(pid_dir, monkeypatch):
    """端口文件缺失（老 watchgod 遗留）→ 也换掉：无法确认它盯的端口。

    放行的话它可能正在 ping 一个早已不存在的端口，把（错的）服务反复重启。
    """
    w._write_pid(w.WATCHDOG_PID_FILE)
    assert w._read_watchdog_port() is None

    killed = []
    monkeypatch.setattr(w, "_stop_watchdog", lambda pid: killed.append(pid))
    monkeypatch.setattr(w.subprocess, "Popen", lambda *a, **kw: type(
        "P", (), {"pid": 4242}
    )())

    w.ensure_watchdog_running(port=8981)
    assert len(killed) == 1


def test_stop_watchdog_safe_for_dead_pid(pid_dir):
    """pid 已不存在：不抛异常，并把残留的 pid/port 文件清掉。"""
    w._write_pid(w.WATCHDOG_PID_FILE)
    w._write_watchdog_port(8981)
    w._stop_watchdog(999999)
    assert not w.WATCHDOG_PID_FILE.exists()
    assert not w.WATCHDOG_PORT_FILE.exists()
