"""重复实例 / watchdog 重启逻辑的回归测试。

背景（真实故障）：用户装了 `ethan server install`（launchd，KeepAlive=true），
而 `ethan serve` 自己还会拉起内置 watchdog——两个守护者盯同一个端口。谁先抢到
8989，另一个就永远绑不上并反复重启，实测刷出 2204 次 `Errno 48: address already
in use`。每次重启都会踢断桌面端 WebSocket，表现为「桌面端老失联」。

更糟的是绑端口失败的 uvicorn 进程**不会退出**：它会挂成一个不监听任何端口却持续
占 CPU 的僵尸，期间还跑完了 memory reindex（1297 条，数十秒）并污染 server.pid。

本文件的测试锁住修复后的三条不变量：
1. 端口上已有健康 ethan 实例时，run_server 立即退出（SystemExit(1)），不跑 lifespan。
2. watchdog._start_server 幂等：已有健康实例就不重复拉起。
3. watchdog 只在端口确实没监听者（真死）时才重启；只是 health 超时（忙）不重启。
"""
from __future__ import annotations

import pytest

from ethan.interface import api
from ethan.watchdog import DEFAULT_PORT, _check_server_health


class _FakeResp:
    """最小可用的 urlopen 返回值替身。"""

    def __init__(self, status: int = 200):
        self.status = status

    def read(self, _n: int = -1) -> bytes:
        return b'{"status":"ok","agent_name":"Ethan"}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ── api._port_is_served ──────────────────────────────────────────────


def test_port_is_served_true_for_healthy_ethan(monkeypatch):
    """health 200 且响应含 ethan 标识 → 判定「已有实例」。"""
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_a, **_k: _FakeResp(200)
    )
    assert api._port_is_served("0.0.0.0", 8989) is True


def test_port_is_served_false_for_foreign_service(monkeypatch):
    """端口被占但响应不像 ethan（如别的服务恰好占了同端口）→ 不算已有实例。

    否则会拒绝启动一个本该能跑的 server。
    """
    class _Other(_FakeResp):
        def read(self, _n: int = -1) -> bytes:
            return b'{"hello":"world"}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: _Other(200))
    assert api._port_is_served("0.0.0.0", 8989) is False


def test_port_is_served_false_when_nothing_listening(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert api._port_is_served("0.0.0.0", 9999) is False


def test_run_server_exits_when_port_already_served(monkeypatch):
    """核心回归：端口已有健康实例 → 秒退，且绝不进入 lifespan / uvicorn。

    修复前这里会一路跑完 lifespan（含 reindex）才在 bind 时报错，然后挂成僵尸。
    """
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: True)

    lifespan_entered = {"yes": False}

    def _fake_lifespan(_app):
        lifespan_entered["yes"] = True
        raise AssertionError("不应进入 lifespan")

    monkeypatch.setattr(api, "lifespan", _fake_lifespan)

    with pytest.raises(SystemExit) as exc:
        api.run_server(host="0.0.0.0", port=8989)

    assert exc.value.code == 1
    assert lifespan_entered["yes"] is False


def test_run_server_does_not_call_uvicorn_when_refused(monkeypatch):
    """拒绝路径下连 uvicorn.run 都不该触发。"""
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: True)

    called = {"n": 0}

    def _fake_uvicorn_run(*_a, **_k):
        called["n"] += 1

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", type(
        "M", (), {"run": staticmethod(_fake_uvicorn_run)}
    ))

    with pytest.raises(SystemExit):
        api.run_server(host="0.0.0.0", port=8989)

    assert called["n"] == 0


# ── watchdog._start_server 幂等 ──────────────────────────────────────


def test_start_server_skips_when_already_healthy(monkeypatch):
    """已有健康 server 时不该再拉一个（否则必然 Errno 48 → 僵尸）。"""
    import ethan.watchdog as w

    monkeypatch.setattr(w, "_check_server_health", lambda _p: True)

    def _no_popen(*_a, **_k):
        raise AssertionError("不应 Popen 新 server")

    monkeypatch.setattr(w.subprocess, "Popen", _no_popen)

    w._start_server(8989)  # 不抛错即为通过


def test_start_server_proceeds_when_dead(monkeypatch):
    """server 确实不在时应当拉起。"""
    import ethan.watchdog as w

    monkeypatch.setattr(w, "_check_server_health", lambda _p: False)

    spawned = {"cmd": None}

    class _FakeProc:
        pid = 12345

    def _fake_popen(cmd, **_k):
        spawned["cmd"] = cmd
        return _FakeProc()

    # 拉起来后会轮询 health 直到超时（30 次 * 1s），这里让它立刻"健康"以缩短测试
    calls = {"n": 0}

    def _health_then_ok(_p):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(w, "_check_server_health", _health_then_ok)
    monkeypatch.setattr(w.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(w.time, "sleep", lambda _s: None)

    w._start_server(8989)

    assert spawned["cmd"] is not None
    assert "8989" in " ".join(spawned["cmd"])


def test_start_server_survives_missing_pid_dir(monkeypatch, tmp_path):
    """全新机器上 /tmp/ethan 还不存在时也要能启动（否则 watchdog 直接崩）。

    CI 上曾因此失败：_start_server 无脑 open(/tmp/ethan/server_subprocess.log)，
    目录不存在就 FileNotFoundError——偏偏发生在「最需要重启 server」的时刻。
    """
    import ethan.watchdog as w

    missing_dir = tmp_path / "no" / "such" / "dir"
    monkeypatch.setattr(w, "_PID_DIR", missing_dir)
    monkeypatch.setattr(w, "_check_server_health", lambda _p: False)

    spawned = {"cmd": None}

    class _FakeProc:
        pid = 999

    def _fake_popen(cmd, **kwargs):
        spawned["cmd"] = cmd
        # stdout 必须是可用的文件对象或 DEVNULL，不能是 None
        assert kwargs.get("stdout") is not None
        return _FakeProc()

    calls = {"n": 0}

    def _health_then_ok(_p):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(w, "_check_server_health", _health_then_ok)
    monkeypatch.setattr(w.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(w.time, "sleep", lambda _s: None)

    w._start_server(8989)  # 不抛错即为通过

    assert spawned["cmd"] is not None


# ── 忙 vs 死 ─────────────────────────────────────────────────────────


def test_server_not_dead_when_port_still_listening(monkeypatch):
    """health 超时但端口还有监听者 → 只是忙，不算死（不该重启）。"""
    import ethan.watchdog as w

    monkeypatch.setattr(w, "_port_in_use", lambda _p: True)
    assert w._server_is_dead(8989) is False


def test_server_dead_when_no_listener(monkeypatch):
    """端口上没人监听 → 真死，可以重启。"""
    import ethan.watchdog as w

    monkeypatch.setattr(w, "_port_in_use", lambda _p: False)
    assert w._server_is_dead(8989) is True


def test_check_server_health_false_on_error(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert _check_server_health(DEFAULT_PORT) is False


def test_watchdog_default_port_is_8900():
    """默认端口常量不该被顺手改掉（多处依赖）。"""
    assert DEFAULT_PORT == 8900


# ── launchd plist 不再双重守护 ───────────────────────────────────────


def test_plist_disables_builtin_watchdog():
    """launchd 自己就是守护进程，plist 必须关掉 serve 内置 watchdog。

    否则两个守护者互抢端口，就是「桌面端老失联」的根因。
    """
    import plistlib

    from ethan.interface.commands.server import _PLIST_TEMPLATE

    content = _PLIST_TEMPLATE.format(
        ethan_exe="/tmp/x/ethan", bin_dir="/tmp/x", ethan_home="/tmp/x"
    )
    data = plistlib.loads(content.encode())
    assert data["EnvironmentVariables"]["ETHAN_NO_WATCHDOG"] == "1"
    assert data["KeepAlive"] is True


def test_plist_has_throttle_interval():
    """端口被占时进程会快速退出，需要节流避免刷屏式重启。"""
    import plistlib

    from ethan.interface.commands.server import _PLIST_TEMPLATE

    content = _PLIST_TEMPLATE.format(
        ethan_exe="/tmp/x/ethan", bin_dir="/tmp/x", ethan_home="/tmp/x"
    )
    data = plistlib.loads(content.encode())
    assert data["ThrottleInterval"] >= 10
