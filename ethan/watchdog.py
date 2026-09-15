"""进程互相监控：server ↔ watchdog 相互检查、相互拉起。

架构：
- Server（web + lark listener）：单进程，启动时自动拉起 watchdog
- Watchdog：独立进程，定期 ping server /api/health，死了就重启

互相感知通过 PID 文件（位于 _PID_DIR = /tmp/ethan）：
- /tmp/ethan/server.pid  — server 写入自己的 PID
- /tmp/ethan/watchdog.pid — watchdog 写入自己的 PID

Server 的 heartbeat 里检查 watchdog 是否存活，如不在则重新拉起。
Watchdog 循环检查 server health，如不通则 kill + 重启。
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_PID_DIR = Path("/tmp/ethan")
SERVER_PID_FILE = _PID_DIR / "server.pid"
WATCHDOG_PID_FILE = _PID_DIR / "watchdog.pid"
# watchdog 正在监控的端口。单独存一个文件而不是塞进 watchdog.pid：PID 文件
# 被别处按「一行整数」读取，混入端口会解析失败。少了这个文件就没法判断
# 复用到的 watchdog 盯的是不是我们这次的端口。
WATCHDOG_PORT_FILE = _PID_DIR / "watchdog.port"

DEFAULT_PORT = 8900
HEALTH_CHECK_INTERVAL = 15  # 每15秒检查一次
HEALTH_CHECK_TIMEOUT = 5    # HTTP 超时
MAX_FAILURES = 3            # 连续N次失败才判定死亡


def _pid_alive(pid: int) -> bool:
    """检查 PID 对应进程是否存活。"""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_pid(pid_file: Path) -> int | None:
    """读取 PID 文件，返回 PID 或 None。"""
    try:
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            if _pid_alive(pid):
                return pid
    except (ValueError, OSError):
        pass
    return None


def _write_pid(pid_file: Path) -> None:
    """写入当前进程 PID。"""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))


def _remove_pid(pid_file: Path) -> None:
    """清理 PID 文件。"""
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def _read_watchdog_port() -> int | None:
    """读 watchdog 正在监控的端口，读不到（老版本/文件被删）返回 None。"""
    try:
        return int(WATCHDOG_PORT_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _write_watchdog_port(port: int) -> None:
    try:
        WATCHDOG_PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        WATCHDOG_PORT_FILE.write_text(str(port))
    except OSError:
        pass


def _remove_watchdog_port() -> None:
    try:
        WATCHDOG_PORT_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ── Server 侧：启动/检查 watchdog ─────────────────────────────────────


def write_server_pid() -> None:
    """Server 启动时调用：写 PID 文件。"""
    _write_pid(SERVER_PID_FILE)
    logger.info("[Watchdog] Server PID %d written to %s", os.getpid(), SERVER_PID_FILE)


def _stop_watchdog(pid: int) -> None:
    """停掉一个 watchdog 进程并等它退出（SIGTERM 优先，超时再 KILL）。

    只在「复用到盯错端口的 watchdog」时调用。先 SIGTERM 让它走自己的 _cleanup
    清掉 PID 文件，比直接 KILL 干净。
    """
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        _remove_pid(WATCHDOG_PID_FILE)
        _remove_watchdog_port()
        return

    for _ in range(20):  # 最多等 2 秒
        time.sleep(0.1)
        if not _pid_alive(pid):
            break
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    _remove_pid(WATCHDOG_PID_FILE)
    _remove_watchdog_port()


def ensure_watchdog_running(port: int = DEFAULT_PORT) -> None:
    """Server 侧确保 watchdog 进程在运行，且盯的正是 port。不在/盯错了就拉起。

    port 必须传 server 的实际监听端口：watchdog 靠 HTTP ping 该端口判活，
    盯错端口会把健康的 server 误判为死亡并反复重启（且 `_kill_server` 的端口
    扫描会误杀恰好占用该端口的其它实例）。

    端口可配之后，「已有 watchdog」不再等于「盯的是对的端口」——把端口改到
    8981 时，之前为 8900 拉起的 watchdog 还活着，直接复用会让它继续 ping 8900。
    因此复用前要比对端口，不一致就把旧的换掉。
    """
    existing_pid = _read_pid(WATCHDOG_PID_FILE)
    if existing_pid:
        watched_port = _read_watchdog_port()
        if watched_port == port:
            logger.info(
                "[Watchdog] Watchdog already running (pid=%d, port=%d)",
                existing_pid,
                port,
            )
            return
        if watched_port is None:
            # 老版本留下的进程/端口文件缺失：无法确认它盯的是哪个端口，
            # 但它在 ping 错端口时会自己把（错的）server 重启，风险大于收益，
            # 故一并换掉。只警告不静默。
            logger.warning(
                "[Watchdog] Existing watchdog (pid=%d) has unknown port, replacing...",
                existing_pid,
            )
        else:
            logger.warning(
                "[Watchdog] Existing watchdog (pid=%d) monitors port %d, "
                "but we need %d — replacing it",
                existing_pid,
                watched_port,
                port,
            )
        _stop_watchdog(existing_pid)

    # 拉起 watchdog 作为独立后台进程
    project_root = Path(__file__).parent.parent
    venv_python = project_root / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else sys.executable

    proc = subprocess.Popen(
        [python, "-m", "ethan.watchdog", "--daemon", "--port", str(port)],
        cwd=str(project_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # 脱离父进程会话，父死不影响子
    )
    logger.info("[Watchdog] Started watchdog (pid=%d), monitoring port %d", proc.pid, port)


def check_watchdog_health(port: int = DEFAULT_PORT) -> None:
    """Server 的 heartbeat 里调用：检查 watchdog 是否存活，不在就重新拉起。"""
    existing_pid = _read_pid(WATCHDOG_PID_FILE)
    if existing_pid:
        return
    logger.warning("[Watchdog] Watchdog process not found, restarting...")
    ensure_watchdog_running(port=port)


# ── Watchdog 侧：主循环 ──────────────────────────────────────────────


def _check_server_health(port: int) -> bool:
    """HTTP ping server health endpoint。"""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=HEALTH_CHECK_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


def _kill_server(port: int = DEFAULT_PORT) -> None:
    """强杀 server 进程（通过 PID 文件或端口扫描）。

    端口扫描必须用实际监控端口：写死 8900 会在服务跑在非默认端口时，
    误杀恰好占用 8900 的其它实例。
    """
    pid = _read_pid(SERVER_PID_FILE)
    if pid:
        logger.warning("[Watchdog] Killing server (pid=%d)", pid)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        time.sleep(1)

    # 同时检查端口占用（应对 PID 文件过期的情况）
    try:
        import subprocess as sp
        result = sp.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    os.kill(int(line.strip()), signal.SIGKILL)
                except (ValueError, ProcessLookupError):
                    pass
    except Exception:
        pass

    _remove_pid(SERVER_PID_FILE)
    time.sleep(2)  # 等端口释放


def _start_server(port: int = DEFAULT_PORT) -> None:
    """拉起 server 进程（监听 port）。"""
    project_root = Path(__file__).parent.parent
    venv_python = project_root / ".venv" / "bin" / "python3"

    if venv_python.exists():
        # 直接用 venv python 启动，不依赖 uv（避免 PATH 问题）
        cmd = [
            str(venv_python), "-c",
            f"from ethan.interface.api import run_server; run_server(port={port})",
        ]
    else:
        cmd = [
            "uv", "run", "python", "-c",
            f"from ethan.interface.api import run_server; run_server(port={port})",
        ]

    env = os.environ.copy()
    # 确保子进程能找到系统命令
    extra_paths = [
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".cargo" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")

    # 重定向到日志文件（非 DEVNULL），方便排查 server 启动/运行期错误
    log_path = _PID_DIR / "server_subprocess.log"
    log_f = open(log_path, "a", buffering=1)  # 行缓冲，实时写
    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    logger.info("[Watchdog] Started server (pid=%d)", proc.pid)

    # 等待 server 启动成功（最多 30 秒）
    for _ in range(30):
        time.sleep(1)
        if _check_server_health(port):
            logger.info("[Watchdog] Server is up and healthy")
            return
    logger.error("[Watchdog] Server failed to start within 30s")


def _check_lark_event_bus() -> bool:
    """检查 lark event bus 进程是否存活。"""
    try:
        import subprocess as sp
        result = sp.run(
            ["pgrep", "-f", "lark-cli event _bus"],
            capture_output=True, text=True, timeout=3,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def watchdog_main(port: int = DEFAULT_PORT) -> None:
    """Watchdog 主循环：守护 server 进程。"""
    _write_pid(WATCHDOG_PID_FILE)
    # 记下监控端口，供 ensure_watchdog_running 复用前比对（见那里的说明）
    _write_watchdog_port(port)
    logger.info("[Watchdog] Watchdog started (pid=%d), monitoring server on port %d", os.getpid(), port)

    consecutive_failures = 0

    def _cleanup(signum, frame):
        _remove_pid(WATCHDOG_PID_FILE)
        _remove_watchdog_port()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    # 启动后先等待一个周期，给 server 时间完成启动（绑端口）
    time.sleep(HEALTH_CHECK_INTERVAL)

    while True:
        try:
            healthy = _check_server_health(port)

            if healthy:
                if consecutive_failures > 0:
                    logger.info("[Watchdog] Server recovered after %d failures", consecutive_failures)
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.warning(
                    "[Watchdog] Server health check failed (%d/%d)",
                    consecutive_failures, MAX_FAILURES,
                )

                if consecutive_failures >= MAX_FAILURES:
                    logger.error("[Watchdog] Server unresponsive, restarting...")
                    _kill_server(port)
                    _start_server(port)
                    consecutive_failures = 0
                    # 重启后等一个周期再检查
                    time.sleep(HEALTH_CHECK_INTERVAL)
                    continue

            # 顺便检查 lark event bus（如果 server 在，bus 不在说明可能静默断连）
            if healthy and not _check_lark_event_bus():
                logger.warning("[Watchdog] Lark event bus not found — server may need restart for reconnection")
                # 不立刻重启 server，因为 server 内部有重连逻辑
                # 但如果持续没有 bus，说明 server 的重连也失败了

        except Exception:
            logger.exception("[Watchdog] Check loop error")

        time.sleep(HEALTH_CHECK_INTERVAL)


# ── 入口 ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Ethan server watchdog")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port to monitor")
    args = parser.parse_args()
    watchdog_main(port=args.port)
