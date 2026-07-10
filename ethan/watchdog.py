"""进程互相监控：server ↔ watchdog 相互检查、相互拉起。

架构：
- Server（web + lark listener）：单进程，启动时自动拉起 watchdog
- Watchdog：独立进程，定期 ping server /api/health，死了就重启

互相感知通过 PID 文件：
- ~/.ethan/server.pid  — server 写入自己的 PID
- ~/.ethan/watchdog.pid — watchdog 写入自己的 PID

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


# ── Server 侧：启动/检查 watchdog ─────────────────────────────────────


def write_server_pid() -> None:
    """Server 启动时调用：写 PID 文件。"""
    _write_pid(SERVER_PID_FILE)
    logger.info("[Watchdog] Server PID %d written to %s", os.getpid(), SERVER_PID_FILE)


def ensure_watchdog_running() -> None:
    """Server 侧确保 watchdog 进程在运行。不在就拉起。"""
    existing_pid = _read_pid(WATCHDOG_PID_FILE)
    if existing_pid:
        logger.info("[Watchdog] Watchdog already running (pid=%d)", existing_pid)
        return

    # 拉起 watchdog 作为独立后台进程
    project_root = Path(__file__).parent.parent
    venv_python = project_root / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else sys.executable

    proc = subprocess.Popen(
        [python, "-m", "ethan.watchdog", "--daemon"],
        cwd=str(project_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # 脱离父进程会话，父死不影响子
    )
    logger.info("[Watchdog] Started watchdog (pid=%d)", proc.pid)


def check_watchdog_health() -> None:
    """Server 的 heartbeat 里调用：检查 watchdog 是否存活，不在就重新拉起。"""
    existing_pid = _read_pid(WATCHDOG_PID_FILE)
    if existing_pid:
        return
    logger.warning("[Watchdog] Watchdog process not found, restarting...")
    ensure_watchdog_running()


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


def _kill_server() -> None:
    """强杀 server 进程（通过 PID 文件或端口扫描）。"""
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
            ["lsof", "-ti", f":{DEFAULT_PORT}"],
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


def _start_server() -> None:
    """拉起 server 进程。"""
    project_root = Path(__file__).parent.parent
    venv_python = project_root / ".venv" / "bin" / "python3"

    if venv_python.exists():
        # 直接用 venv python 启动，不依赖 uv（避免 PATH 问题）
        cmd = [
            str(venv_python), "-c",
            f"from ethan.interface.api import run_server; run_server(port={DEFAULT_PORT})",
        ]
    else:
        cmd = [
            "uv", "run", "python", "-c",
            f"from ethan.interface.api import run_server; run_server(port={DEFAULT_PORT})",
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

    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    logger.info("[Watchdog] Started server (pid=%d)", proc.pid)

    # 等待 server 启动成功（最多 30 秒）
    for _ in range(30):
        time.sleep(1)
        if _check_server_health(DEFAULT_PORT):
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
    logger.info("[Watchdog] Watchdog started (pid=%d), monitoring server on port %d", os.getpid(), port)

    consecutive_failures = 0

    def _cleanup(signum, frame):
        _remove_pid(WATCHDOG_PID_FILE)
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
                    _kill_server()
                    _start_server()
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
