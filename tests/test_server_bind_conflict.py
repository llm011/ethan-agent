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


# ── DB 同一性守卫（端口不同也会互锁）─────────────────────────────────
#
# 真实故障：watchdog 被一个旧的 8900 实例拉起后，那个实例退出了，watchdog 却继续
# 复活 8900 上的 server；同时 launchd 托管的 8989 实例在跑。两个进程各自跑完
# lifespan（scheduler/heartbeat/reindex 全起），双写同一个 DELETE 模式
# sessions.db（写锁全库排他）——表现是 journal 卡住不释放、连纯 SELECT 都
# `database is locked`、前端「打开会话一直加载」。
#
# 端口判据（_port_is_served）挡不住这种情况：两个实例端口完全不同。


def test_run_server_exits_when_db_conflict_on_other_port(monkeypatch):
    """核心回归：另一个实例（不同端口）开着同一个 sessions.db → 必须秒退。

    修复前只查端口，于是 watchdog 拉起的实例能穿透这里跑完整个 lifespan。
    """
    monkeypatch.delenv("ETHAN_NO_WATCHDOG", raising=False)
    # 端口上没人（模拟「用另一个端口起」的场景）
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: False)
    monkeypatch.setattr(
        api, "_find_db_conflicts", lambda: [(12345, "/x/sessions.db")]
    )

    lifespan_entered = {"yes": False}

    def _fake_lifespan(_app):
        lifespan_entered["yes"] = True
        raise AssertionError("不应进入 lifespan")

    monkeypatch.setattr(api, "lifespan", _fake_lifespan)

    with pytest.raises(SystemExit) as exc:
        api.run_server(host="0.0.0.0", port=8900)

    assert exc.value.code == 1
    assert lifespan_entered["yes"] is False


def test_run_server_proceeds_when_no_db_conflict(monkeypatch):
    """无冲突时必须正常走下去（不能因为加了守卫就起不来）。"""
    monkeypatch.delenv("ETHAN_NO_WATCHDOG", raising=False)
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: False)
    monkeypatch.setattr(api, "_find_db_conflicts", lambda: [])

    ran = {"uvicorn": False}

    def _fake_uvicorn_run(*_a, **_k):
        ran["uvicorn"] = True

    monkeypatch.setitem(
        __import__("sys").modules,
        "uvicorn",
        type("M", (), {"run": staticmethod(_fake_uvicorn_run)}),
    )

    api.run_server(host="0.0.0.0", port=8900)
    assert ran["uvicorn"] is True


def test_db_guard_skipped_with_no_watchdog_env(monkeypatch):
    """ETHAN_NO_WATCHDOG=1 是开发/测试开关，必须放行。

    worktree 里跑测试时 sessions.db 和常驻服务是同一个文件，不放行会把日常开发
    流程整个堵死（CLAUDE.md 的多 worktree 规范）。
    """
    monkeypatch.setenv("ETHAN_NO_WATCHDOG", "1")
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: False)
    monkeypatch.setattr(
        api, "_find_db_conflicts", lambda: [(12345, "/x/sessions.db")]
    )

    ran = {"uvicorn": False}

    def _fake_uvicorn_run(*_a, **_k):
        ran["uvicorn"] = True

    monkeypatch.setitem(
        __import__("sys").modules,
        "uvicorn",
        type("M", (), {"run": staticmethod(_fake_uvicorn_run)}),
    )

    api.run_server(host="0.0.0.0", port=8900)
    assert ran["uvicorn"] is True


def test_find_db_conflicts_degrades_to_empty(monkeypatch):
    """检测本身失败时降级为「无冲突」，不能让服务起不来。"""

    def _boom(*_a, **_k):
        raise RuntimeError("lsof 不存在")

    monkeypatch.setattr("ethan.interface.cli._find_conflicting_servers", _boom)
    assert api._find_db_conflicts() == []


def test_run_server_exits_when_port_already_served_unchanged(monkeypatch):
    """端口守卫生效时仍应先于 DB 守卫退出（顺序不能反）。"""
    monkeypatch.delenv("ETHAN_NO_WATCHDOG", raising=False)
    monkeypatch.setattr(api, "_port_is_served", lambda *_a, **_k: True)

    db_checked = {"yes": False}

    def _fake_db_conflicts():
        db_checked["yes"] = True
        return []

    monkeypatch.setattr(api, "_find_db_conflicts", _fake_db_conflicts)

    with pytest.raises(SystemExit):
        api.run_server(host="0.0.0.0", port=8900)

    # 端口已占用时不必再查 DB（早退）
    assert db_checked["yes"] is False


# ── watchdog 退役（不再无限复活没人要的端口）─────────────────────────


def test_watchdog_retires_after_repeated_failed_resurrections(monkeypatch):
    """连续复活都起不来 → 判定主人已不存在，主动退出。

    修复前 watchdog 会无限复活一个已无人管理的端口实例，持续制造与主实例
    争抢同一 sessions.db 的幽灵进程。
    """
    import ethan.watchdog as w

    monkeypatch.setattr(w, "HEALTH_CHECK_INTERVAL", 0)
    monkeypatch.setattr(w, "MAX_FAILURES", 2)
    monkeypatch.setattr(w, "MAX_RESURRECT_ATTEMPTS", 2)

    # 端口永远没人监听（真死）→ resurrecting 恒为 True
    monkeypatch.setattr(w, "_check_server_health", lambda _p: False)
    monkeypatch.setattr(w, "_server_is_dead", lambda _p: True)
    monkeypatch.setattr(w, "_port_in_use", lambda _p: False)
    monkeypatch.setattr(w, "_kill_server", lambda _p: None)
    monkeypatch.setattr(w, "_check_lark_event_bus", lambda: True)
    monkeypatch.setattr(w.time, "sleep", lambda _s: None)

    starts = {"n": 0}

    def _fake_start(_port=w.DEFAULT_PORT):
        starts["n"] += 1

    monkeypatch.setattr(w, "_start_server", _fake_start)
    # 别碰真实的 pid/port 文件
    monkeypatch.setattr(w, "_write_pid", lambda *_a, **_k: None)
    monkeypatch.setattr(w, "_write_watchdog_port", lambda *_a, **_k: None)

    with pytest.raises(SystemExit):
        w.watchdog_main(port=8900)

    assert starts["n"] == 2


def test_watchdog_does_not_retire_when_resurrection_succeeds(monkeypatch):
    """复活后端口有监听者 → 是正常接住崩溃进程，不该退役。"""
    import ethan.watchdog as w

    monkeypatch.setattr(w, "HEALTH_CHECK_INTERVAL", 0)
    monkeypatch.setattr(w, "MAX_FAILURES", 2)
    monkeypatch.setattr(w, "MAX_RESURRECT_ATTEMPTS", 2)
    monkeypatch.setattr(w, "_check_server_health", lambda _p: False)
    monkeypatch.setattr(w, "_server_is_dead", lambda _p: True)
    monkeypatch.setattr(w, "_port_in_use", lambda _p: False)
    monkeypatch.setattr(w, "_kill_server", lambda _p: None)
    monkeypatch.setattr(w, "_check_lark_event_bus", lambda: True)

    calls = {"n": 0}

    def _sleep(_s):
        calls["n"] += 1
        if calls["n"] > 12:  # 防死循环
            raise SystemExit(0)

    monkeypatch.setattr(w.time, "sleep", _sleep)

    # 关键：复活之后端口变成有人监听 → 下一次循环判定 _server_is_dead=False
    state = {"started": False}

    def _fake_start(_port=w.DEFAULT_PORT):
        state["started"] = True

    monkeypatch.setattr(w, "_start_server", _fake_start)
    monkeypatch.setattr(
        w, "_server_is_dead", lambda _p: not state["started"]
    )
    monkeypatch.setattr(w, "_port_in_use", lambda _p: state["started"])
    monkeypatch.setattr(w, "_write_pid", lambda *_a, **_k: None)
    monkeypatch.setattr(w, "_write_watchdog_port", lambda *_a, **_k: None)

    # 不抛 SystemExit（退役）即为通过；只由 _sleep 到次数上限退出
    with pytest.raises(SystemExit) as exc:
        w.watchdog_main(port=8900)

    assert exc.value.code == 0  # 来自 _sleep 的防死循环退出，不是退役
    assert state["started"] is True


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


def test_plist_raises_fd_limit():
    """launchd 默认 maxfiles=256 对 ethan 偏低，必须显式放行。

    fd 耗尽的 `Errno 24` 可能落在 SQLite 提交路径上，导致写事务 journal 不释放、
    全库写锁卡死（表现为「打开会话一直加载」）。
    """
    import plistlib

    from ethan.interface.commands.server import _PLIST_TEMPLATE

    content = _PLIST_TEMPLATE.format(
        ethan_exe="/tmp/x/ethan", bin_dir="/tmp/x", ethan_home="/tmp/x"
    )
    data = plistlib.loads(content.encode())
    assert data["SoftResourceLimits"]["NumberOfFiles"] >= 8192
    assert data["HardResourceLimits"]["NumberOfFiles"] >= 8192


# ── status 不误报唯一的 launchd 正主 ─────────────────────────────────


def test_status_excludes_launchd_pid(monkeypatch, capsys):
    """launchd 托管的实例带 ETHAN_NO_WATCHDOG=1 → **不写** server.pid。

    status 原先只靠 server.pid 排除正主，于是 legit_pid 恒为 None，唯一的健康
    实例被报成「多实例冲突」（实测如此）。必须同时把 launchd 的 PID 排除掉。
    """
    from ethan.interface.commands import server as srv

    fake_list = (
        '{\n'
        '\t"PID" = 4242;\n'
        '\t"Program" = "/x/ethan";\n'
        '}'
    )
    monkeypatch.setattr(srv, "_is_installed", lambda: True)
    monkeypatch.setattr(
        srv, "_launchctl", lambda *_a, **_k: type(
            "R", (), {"returncode": 0, "stdout": fake_list}
        )()
    )
    # server.pid 不存在（launchd 场景就是如此）
    monkeypatch.setattr("ethan.watchdog._read_pid", lambda _p: None)

    seen: dict = {}

    def _fake_conflicts(extra_exclude_pids=None):
        seen["exclude"] = extra_exclude_pids
        return []

    monkeypatch.setattr(
        "ethan.interface.cli._find_conflicting_servers", _fake_conflicts
    )

    srv.status()
    out = capsys.readouterr().out
    # launchd 的 PID 必须在排除集里，否则会误报
    assert seen.get("exclude") and 4242 in seen["exclude"]
    assert "多个 ethan 实例" not in out
