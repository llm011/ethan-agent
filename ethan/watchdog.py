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
# watchdog 自己的日志。不能用 DEVNULL：watchdog 是「发现 server 不健康 → kill →
# 重启」这条链上唯一的决策者，它的日志一旦丢弃，事后就只能看到 server 被反复重启
# （表现为「桌面端老失联」），却查不到是谁、因为什么触发的重启。
WATCHDOG_LOG_FILE = _PID_DIR / "watchdog.log"
# watchdog 正在监控的端口。单独存一个文件而不是塞进 watchdog.pid：PID 文件
# 被别处按「一行整数」读取，混入端口会解析失败。少了这个文件就没法判断
# 复用到的 watchdog 盯的是不是我们这次的端口。
WATCHDOG_PORT_FILE = _PID_DIR / "watchdog.port"

DEFAULT_PORT = 8900
HEALTH_CHECK_INTERVAL = 15  # 每15秒检查一次
HEALTH_CHECK_TIMEOUT = 5    # HTTP 超时
MAX_FAILURES = 3            # 连续N次失败才判定死亡
# 连续复活失败多少次后判定「主人已不存在」并退役。见 watchdog_main 的说明：
# 拉起 watchdog 的 serve 退出后，watchdog 会无限复活一个没人要的端口实例，
# 与主实例双写 sessions.db。给几次机会（应对 server 真的连续崩溃后自愈），
# 仍起不来就退出。默认 5 次 ≈ 5 个健康检查周期（每周期 15s）。
MAX_RESURRECT_ATTEMPTS = 5


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

    # 日志落盘而非 DEVNULL，见 WATCHDOG_LOG_FILE 的说明
    try:
        WATCHDOG_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(WATCHDOG_LOG_FILE, "a", buffering=1)
    except OSError:
        log_f = subprocess.DEVNULL

    proc = subprocess.Popen(
        [python, "-m", "ethan.watchdog", "--daemon", "--port", str(port)],
        cwd=str(project_root),
        stdout=log_f,
        stderr=subprocess.STDOUT,
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
    """HTTP ping server health endpoint。

    注意：这里「返回 False」只表示「这次探测没拿到 200」，不等于 server 已死。
    单纯的超时常发生在 server 事件循环被长任务占住时（LLM 流式、memory reindex、
    SQLite 忙等），此时进程健康、端口也在监听。调用方需结合 _port_in_use 判断，
    否则会把健康的 server 误杀重启——每次重启都会踢断桌面端连接。
    """
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


def _server_is_dead(port: int) -> bool:
    """判定 server 是否「真的死了」——端口上已没有任何监听进程。

    只有这种情况才值得 kill + 重启：进程没了/没绑上端口。进程还在监听但 health
    超时，属于「忙」，应当继续观察而不是重启。
    """
    return not _port_in_use(port)


def _port_in_use(port: int) -> bool:
    """端口上是否还有进程在监听。"""
    try:
        import subprocess as sp
        result = sp.run(
            ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=3,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _wait_port_released(port: int, timeout: float = 10.0) -> bool:
    """等端口真正释放（上限 timeout 秒）。

    固定 sleep(2) 不够稳：SIGKILL 之后 socket 可能仍处于 TIME_WAIT / 未回收，
    2 秒后拉起新进程照样 Errno 48，于是进入「起不来就再杀再起」的循环——每次
    循环都会把桌面端连接踢断一次。这里轮询到真释放为止。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_in_use(port):
            return True
        time.sleep(0.25)
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
    if not _wait_port_released(port):
        logger.error(
            "[Watchdog] Port %d still in use after kill — new server will fail to bind",
            port,
        )


def _start_server(port: int = DEFAULT_PORT) -> None:
    """拉起 server 进程（监听 port）。"""
    # 幂等：已经有健康的 server 在监听就不要再拉一个。
    # 重复拉起必然绑不上端口，而绑失败的进程曾经会挂成僵尸（见 api.run_server 的
    # 说明），白白污染 server.pid / heartbeat / 调度器，还会踢断桌面端连接。
    if _check_server_health(port):
        logger.info("[Watchdog] Server already healthy on port %d — skipping start", port)
        return

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

    # 重定向到日志文件（非 DEVNULL），方便排查 server 启动/运行期错误。
    # _PID_DIR 可能还不存在（全新机器 / /tmp 被清理过），不建目录这里会直接
    # FileNotFoundError——watchdog 在「要重启 server」这条最需要它的路径上崩掉。
    log_path = _PID_DIR / "server_subprocess.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log_path, "a", buffering=1)  # 行缓冲，实时写
    except OSError:
        log_f = subprocess.DEVNULL
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

    # 因为「被 launchd 拉起（ETHAN_NO_WATCHDOG=1）」以外的任何一次 serve 启动都会
    # 留下一个脱离会话的 watchdog，而它只认端口、不认「主人还在不在」，于是会出现：
    # 拉起它的那个 serve 早退出了，watchdog 却继续 ping 那个端口、发现没人监听、
    # 判定「server 死亡」并无限复活一个幽灵实例。
    # 实测代价：幽灵实例跑完整个 lifespan（scheduler/heartbeat 全起）与主实例双写
    # 同一个 DELETE 模式 sessions.db，把库锁死到连 SELECT 都 `database is locked`。
    #
    # 判据：连续 N 轮尝试重启、但每次重启出来的实例都活不过一个健康检查周期，
    # 且端口上原本就没有任何「主实例」在监听（_port_in_use 为假）——说明没人需要
    # 这个端口了，watchdog 应当退役，而不是继续制造实例。真正的 server 崩溃由
    # 上一层的 supervisor（launchd KeepAlive / 用户手动 serve）负责重启。
    _resurrect_failures = 0

    while True:
        try:
            healthy = _check_server_health(port)

            if healthy:
                if consecutive_failures > 0:
                    logger.info("[Watchdog] Server recovered after %d failures", consecutive_failures)
                consecutive_failures = 0
            else:
                # 区分「忙」和「死」：端口上还有监听进程 → 大概率只是事件循环被占住
                # （LLM 流式 / reindex / SQLite 忙等），重启反而会打断正在跑的任务、
                # 踢断桌面端连接。只有端口上彻底没人监听了才判定死亡并重启。
                if not _server_is_dead(port):
                    logger.warning(
                        "[Watchdog] Health check timed out but port %d still has a "
                        "listener — treating as busy, not restarting",
                        port,
                    )
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(
                        "[Watchdog] Server health check failed (%d/%d)",
                        consecutive_failures, MAX_FAILURES,
                    )

                    if consecutive_failures >= MAX_FAILURES:
                        # 先记录这次重启前端口上究竟有没有「活着的 server」：
                        # _server_is_dead 为真意味着端口上没人监听，即这次重启是
                        # 「从零复活」而不是「接住一个崩掉的进程」。
                        resurrecting = _server_is_dead(port)
                        logger.error("[Watchdog] Server unresponsive, restarting...")
                        _kill_server(port)
                        _start_server(port)
                        consecutive_failures = 0

                        # 复活次数守卫：反复复活又反复失败 = 没人需要这个端口了
                        # （典型场景：拉起本 watchdog 的那个 serve 已退出/被换成
                        # launchd 托管的另一个端口实例）。继续复活只会不断制造
                        # 争抢同一个 sessions.db 的幽灵实例，必须退役。
                        if resurrecting:
                            _resurrect_failures += 1
                            if _resurrect_failures >= MAX_RESURRECT_ATTEMPTS:
                                logger.error(
                                    "[Watchdog] 已连续 %d 次复活端口 %d 上的 server "
                                    "但均未存活 —— 判定本 watchdog 的主人已不存在"
                                    "（可能是被替代的旧实例遗留），停止复活并退出，"
                                    "避免继续制造争抢同一 sessions.db 的重复实例。",
                                    _resurrect_failures,
                                    port,
                                )
                                _remove_pid(WATCHDOG_PID_FILE)
                                _remove_watchdog_port()
                                sys.exit(0)
                        else:
                            # 端口原本有监听 = 正常接住崩溃的进程，重置计数
                            _resurrect_failures = 0

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
