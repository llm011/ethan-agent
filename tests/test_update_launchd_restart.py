# -*- coding: utf-8 -*-
"""`ethan update` 重启 serve 时必须感知 launchd。

线上事故（11/23）：`ethan update` 的 ``_restart_serve`` 用
``SIGTERM + Popen(start_new_session=True)`` 重启服务，完全不知道 launchd 的存在：

1. launchd 的 KeepAlive 把刚被 SIGTERM 的进程又拉起来，同时 update 也 Popen
   了一个 → 两个抢同一端口，抢输的在 ``api.run_server`` 里拒绝启动。日志里
   累计上千次「拒绝重复启动」。
2. update Popen 出来的进程**不带** ``ETHAN_NO_WATCHDOG=1``，于是它会写
   server.pid 并再拉起一个 watchdog → 与 launchd 形成双保姆。留下的孤儿
   watchdog 会在 launchd 实例 health 抖动时把它 kill 掉，自己再拉一个。

这组测试锁住两点：plist 已安装时**绝不 Popen**，且必须走 launchd 那条路。
"""
from __future__ import annotations

import io

import pytest
from rich.console import Console

from ethan.interface.commands import server as server_mod
from ethan.interface.commands import update as update_mod


@pytest.fixture(autouse=True)
def _no_real_console(monkeypatch):
    """把两个模块的 console 都换成不落盘的，避免测试输出污染。"""
    monkeypatch.setattr(update_mod, "console", Console(file=io.StringIO()))


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """把 time.sleep 变空转。

    `_restart_serve` 的端口轮询是「20 次 × 0.2s 等释放 + 30 次 × 0.5s 等就绪」，
    不短路的话每个用例白等 15s。函数内部是 `import time`，拿的是 sys.modules
    里的模块对象，所以 patch 全局 sleep 即可生效。
    """
    import time

    monkeypatch.setattr(time, "sleep", lambda *_a, **_kw: None)


def _forbid_popen(monkeypatch):
    """任何 subprocess.Popen 都算失败：launchd 托管时不允许自己拉进程。"""
    calls: list = []

    def fake_popen(*a, **kw):
        calls.append((a, kw))
        raise AssertionError(f"launchd 托管时不应 Popen：{a} {kw}")

    monkeypatch.setattr(update_mod.subprocess, "Popen", fake_popen)
    return calls


def _forbid_kill(monkeypatch):
    """不允许直接 SIGTERM 进程：那会和 launchd 的 KeepAlive 抢。"""
    import os as _os

    def fake_kill(pid, sig):
        raise AssertionError(f"launchd 托管时不应直接 kill(pid={pid}, sig={sig})")

    monkeypatch.setattr(_os, "kill", fake_kill)


# ── 主路径：plist 已安装 → 走 launchd ────────────────────────────


def test_restart_uses_launchd_when_plist_installed(monkeypatch):
    """plist 存在时必须调用 server.restart_service，而不是 Popen 新进程。"""
    _forbid_popen(monkeypatch)
    _forbid_kill(monkeypatch)

    called = {}

    def fake_restart_service(console):
        called["hit"] = True
        return True

    monkeypatch.setattr(server_mod, "restart_service", fake_restart_service)
    monkeypatch.setattr(server_mod, "_is_installed", lambda: True)

    update_mod._restart_serve(None)
    assert called.get("hit") is True


def test_restart_launchd_failure_does_not_popen(monkeypatch):
    """launchd 重启失败也只提示，不能退回裸 Popen（那正是事故成因）。"""
    _forbid_popen(monkeypatch)

    monkeypatch.setattr(server_mod, "restart_service", lambda console: False)
    monkeypatch.setattr(server_mod, "_is_installed", lambda: True)

    update_mod._restart_serve(None)  # 不抛异常，只打印提示


def test_restart_launchd_exception_is_swallowed(monkeypatch):
    """restart_service 抛异常时不能让 update 整个崩掉。"""
    _forbid_popen(monkeypatch)

    def boom(console):
        raise RuntimeError("launchctl exploded")

    monkeypatch.setattr(server_mod, "restart_service", boom)
    monkeypatch.setattr(server_mod, "_is_installed", lambda: True)

    update_mod._restart_serve(None)  # 不应向外抛


# ── 判据：看 plist 文件存在，不看 launchd 当前有无 PID ──────────


def test_launchd_installed_checks_plist_file_not_pid(monkeypatch):
    """服务崩溃重试时 launchctl 的 PID 列是 `-`，此时仍算 launchd 托管。

    若按「有 PID」判断，就会在 launchd 也在拉的瞬间退回裸 Popen，重新造出
    抢端口的双实例——正是要防的场景。
    """
    monkeypatch.setattr(server_mod, "_is_installed", lambda: True)
    assert update_mod._launchd_installed() is True

    monkeypatch.setattr(server_mod, "_is_installed", lambda: False)
    assert update_mod._launchd_installed() is False


def test_launchd_installed_false_when_probe_raises(monkeypatch):
    """探测本身出问题时保守返回 False，不阻断非 launchd 用户的重启。

    （不模拟 ImportError：``from pkg import mod`` 走的是包属性而非 sys.modules，
    摘缓存拦不住，模拟出来的是假场景。真正要保的是「任何异常都别往外抛」。）
    """

    def boom():
        raise OSError("plist unreadable")

    monkeypatch.setattr(server_mod, "_is_installed", boom)
    assert update_mod._launchd_installed() is False


# ── 端口解析：launchd 不继承 shell 环境 ──────────────────────────


def test_launchd_port_ignores_shell_env(monkeypatch, tmp_path):
    """终端里设了 ETHAN_SERVER_PORT 不能影响对 launchd 实例的端口判断。

    实测场景：用户 shell 里 export ETHAN_SERVER_PORT=8981，但 plist 没设这个键，
    launchd 的 serve 读 config.yaml 跑在 8989。若重启时按 shell 环境探 8981，
    一次成功的重启会被误报成「服务未能就绪」。

    这里**必须绕开 get_config()**：``load_config`` 自己也会读 shell 的
    ETHAN_SERVER_PORT（env 赢过 config.yaml），用它等于没修。
    """
    plist = tmp_path / "com.ethan.agent.plist"
    plist.write_text(server_mod._render_plist(tmp_path / "ethan"))
    monkeypatch.setattr(server_mod, "PLIST_PATH", plist)
    monkeypatch.setenv("ETHAN_SERVER_PORT", "8981")

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("server:\n  port: 8989\n")
    monkeypatch.setattr("ethan.core.config.CONFIG_FILE", cfg_file)

    assert server_mod._launchd_service_port() == 8989


def test_launchd_port_defaults_when_no_config(monkeypatch, tmp_path):
    """既没 plist 键也没配置文件时回退 8900。"""
    plist = tmp_path / "com.ethan.agent.plist"
    plist.write_text(server_mod._render_plist(tmp_path / "ethan"))
    monkeypatch.setattr(server_mod, "PLIST_PATH", plist)
    monkeypatch.setenv("ETHAN_SERVER_PORT", "8981")
    monkeypatch.setattr("ethan.core.config.CONFIG_FILE", tmp_path / "missing.yaml")

    assert server_mod._launchd_service_port() == 8900


def test_launchd_port_prefers_plist_env(monkeypatch, tmp_path):
    """plist 里显式设了端口时以它为准（那才是服务真正读到的值）。"""
    plist = tmp_path / "com.ethan.agent.plist"
    body = server_mod._render_plist(tmp_path / "ethan").replace(
        "<key>ETHAN_NO_WATCHDOG</key>",
        "<key>ETHAN_SERVER_PORT</key>\n        <string>8990</string>\n"
        "        <key>ETHAN_NO_WATCHDOG</key>",
    )
    plist.write_text(body)
    monkeypatch.setattr(server_mod, "PLIST_PATH", plist)
    monkeypatch.setenv("ETHAN_SERVER_PORT", "8981")

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("server:\n  port: 8989\n")
    monkeypatch.setattr("ethan.core.config.CONFIG_FILE", cfg_file)

    assert server_mod._launchd_service_port() == 8990


# ── 非 launchd 用户：旧行为保持不变 ─────────────────────────────


def test_restart_falls_back_to_popen_without_launchd(monkeypatch):
    """未安装 launchd 时仍走原来的 SIGTERM + Popen 路径。"""
    monkeypatch.setattr(server_mod, "_is_installed", lambda: False)
    monkeypatch.setattr(update_mod, "_find_serve_pid", lambda: None)
    monkeypatch.setattr(update_mod, "_is_port_listening", lambda *a, **kw: False)

    spawned = []

    class _FakeProc:
        pid = 4242

    def fake_popen(*a, **kw):
        spawned.append((a, kw))
        return _FakeProc()

    monkeypatch.setattr(update_mod.subprocess, "Popen", fake_popen)

    update_mod._restart_serve(None)
    assert len(spawned) == 1, "非 launchd 场景应照旧拉起一个进程"


def test_restart_kills_old_process_without_launchd(monkeypatch):
    """非 launchd 场景仍要 SIGTERM 旧进程（否则会起两个）。"""
    import os as _os
    import signal as _signal

    monkeypatch.setattr(server_mod, "_is_installed", lambda: False)
    monkeypatch.setattr(update_mod, "_find_serve_pid", lambda: 1234)
    monkeypatch.setattr(update_mod, "_wait_pid_gone", lambda pid, timeout=8: True)
    monkeypatch.setattr(update_mod, "_is_port_listening", lambda *a, **kw: False)

    killed = []
    monkeypatch.setattr(_os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(
        update_mod.subprocess, "Popen", lambda *a, **kw: type("P", (), {"pid": 999})()
    )

    update_mod._restart_serve(None)
    assert killed and killed[0] == (1234, _signal.SIGTERM)
