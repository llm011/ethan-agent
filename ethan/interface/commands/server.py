"""ethan server — macOS launchd service management."""
import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="管理 Ethan 后台服务（macOS launchd）", no_args_is_help=True)

PLIST_NAME = "com.ethan.agent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_NAME}.plist"

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ethan.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{ethan_exe}</string>
        <string>serve</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <!-- launchd 默认重启节流是 10s。端口被占时进程会立刻退出（见 api.run_server
         的重复实例检测），KeepAlive 便会以这个间隔无限重试。拉到 60s 让重试不至于
         变成刷屏，也给用户留出 `ethan server stop` 的时间。 -->
    <key>ThrottleInterval</key>
    <integer>60</integer>
    <!-- launchd 的 maxfiles 默认只有 256，对 ethan 偏低：Lark 事件监听、微信轮询、
         浏览器插件 WebSocket、多个 SQLite 连接加起来很容易接近上限。fd 耗尽的报错
         是 `OSError: [Errno 24] Too many open files`，而它**可能落在 SQLite 提交
         路径上**——写事务提交失败后 journal 不释放，会把全库写锁卡住，表现为
         「打开会话一直加载」+ 日志刷 `database is locked`。这里显式放行到 65536。 -->
    <key>SoftResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>
    <key>HardResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{ethan_home}/logs/api.out.log</string>
    <key>StandardErrorPath</key>
    <string>{ethan_home}/logs/api.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{bin_dir}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <!-- launchd 自己就是守护进程（KeepAlive=true）。必须关掉 serve 内置的
             watchdog，否则两个保姆同时管一个端口：谁先抢到 8989，另一个就一直
             绑定失败并重启，实测能刷出上千次 Errno 48，每次都把桌面端连接踢断
             （表现为「桌面端老失联」）。此处让 launchd 独占守护职责。 -->
        <key>ETHAN_NO_WATCHDOG</key>
        <string>1</string>
    </dict>
</dict>
</plist>"""


def _ethan_exe() -> Path:
    bin_dir = Path(sys.executable).parent
    exe = bin_dir / "ethan"
    if exe.exists():
        return exe
    import shutil
    found = shutil.which("ethan")
    if found:
        return Path(found)
    raise typer.BadParameter("找不到 ethan 可执行文件，请确认已正确安装。")


def _is_installed() -> bool:
    return PLIST_PATH.exists()


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


@app.command("install")
def install() -> None:
    """安装 Ethan 为 macOS 开机自启服务（launchd）。"""
    console = Console()

    if sys.platform != "darwin":
        console.print("[red]此命令仅支持 macOS。[/red]")
        raise typer.Exit(1)

    exe = _ethan_exe()
    ethan_home = Path.home() / ".ethan"
    log_dir = ethan_home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    plist_content = _PLIST_TEMPLATE.format(
        ethan_exe=str(exe),
        bin_dir=str(exe.parent),
        ethan_home=str(ethan_home),
    )

    _launchctl("unload", str(PLIST_PATH))  # 忽略未加载时的错误
    PLIST_PATH.write_text(plist_content)

    result = _launchctl("load", str(PLIST_PATH))
    if result.returncode != 0:
        console.print(f"[red]launchctl load 失败：{result.stderr.strip()}[/red]")
        raise typer.Exit(1)

    console.print("[green]✓ 服务已安装并启动，下次开机将自动运行。[/green]")
    console.print(f"  可执行文件：{exe}")
    console.print(f"  日志目录：  {log_dir}/")
    # 端口不写进 plist——serve 启动时读 config server.port，改端口只需 restart
    try:
        from ethan.core.config import get_config

        srv = get_config().server
        console.print(f"  监听地址：  {srv.host}:{srv.port}  [dim](config.yaml 的 server 段，改后 ethan server restart 生效)[/dim]")
    except Exception:
        pass
    console.print()
    console.print("  [dim]ethan server status[/dim]   — 查看运行状态")
    console.print("  [dim]ethan server restart[/dim]  — 重启服务")
    console.print("  [dim]ethan server stop[/dim]     — 停止服务")
    console.print("  [dim]ethan server uninstall[/dim]— 卸载服务")

    # 顺带安装 cua-driver（桌面控制后台服务）
    _install_cua_driver(console)


def _install_cua_driver(console: Console) -> None:
    """安装 cua-driver 桌面控制后台服务（可选依赖，失败不影响主流程）。"""
    import shutil

    console.print()
    console.print("[dim]检查 cua-driver（桌面控制插件）...[/dim]")

    # 已安装则直接跳过
    if shutil.which("cua-driver"):
        result = subprocess.run(["cua-driver", "status"], capture_output=True, text=True)
        if result.returncode == 0:
            console.print("[dim]  cua-driver 已安装且在运行，跳过。[/dim]")
            return
        # 已装但未注册服务，补注册
        reg = subprocess.run(["cua-driver", "install"], capture_output=True, text=True)
        if reg.returncode == 0:
            console.print("[green]  ✓ cua-driver 已注册为开机自启服务。[/green]")
        return

    # 未安装，下载安装脚本
    console.print("[dim]  正在安装 cua-driver...[/dim]")
    try:
        install_result = subprocess.run(
            ["bash", "-c",
             "curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash"],
            capture_output=True, text=True, timeout=120,
        )
        if install_result.returncode != 0:
            console.print(f"[yellow]  cua-driver 安装失败（可手动安装后再运行 cua-driver install）：{install_result.stderr.strip()[:200]}[/yellow]")
            return
    except subprocess.TimeoutExpired:
        console.print("[yellow]  cua-driver 安装超时，可稍后手动执行：curl -fsSL .../install.sh | bash[/yellow]")
        return
    except Exception as e:
        console.print(f"[yellow]  cua-driver 安装异常：{e}[/yellow]")
        return

    # 注册为 launchd 服务
    if shutil.which("cua-driver"):
        reg = subprocess.run(["cua-driver", "install"], capture_output=True, text=True)
        if reg.returncode == 0:
            console.print("[green]  ✓ cua-driver 已安装并注册为开机自启服务。[/green]")
        else:
            console.print("[green]  ✓ cua-driver 已安装（launchd 注册失败，可手动运行 cua-driver install）。[/green]")
    else:
        console.print("[yellow]  cua-driver 安装完成，但未找到可执行文件，请检查 PATH。[/yellow]")



@app.command("uninstall")
def uninstall() -> None:
    """卸载 Ethan 开机自启服务。"""
    console = Console()
    if not _is_installed():
        console.print("[yellow]服务未安装。[/yellow]")
        return
    _launchctl("unload", str(PLIST_PATH))
    PLIST_PATH.unlink(missing_ok=True)
    console.print("[green]✓ 服务已卸载。[/green]")


def _stop_leftover_instances(console: Console) -> None:
    """停掉 launchd 之外的残留 ethan 实例（如 watchdog 拉起的那个）。

    `restart` 走 launchd unload/load，只能管到自己拉起的进程。如果端口还被另一个
    实例（watchdog 的、或历史遗留的）占着，launchd 重启出来的新进程照样绑不上——
    重启看起来"成功"了，实际端口上还是旧进程，用户会以为重启无效。这里一并清掉。
    """
    import signal

    try:
        from ethan.interface.cli import _find_conflicting_servers

        conflicts = _find_conflicting_servers()
    except Exception:
        conflicts = []
    if not conflicts:
        return

    console.print(f"[dim]发现 {len(conflicts)} 个残留实例，正在停止...[/dim]")
    for pid, _db in conflicts:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            continue
    # 给它们一点时间优雅退出，仍在的再强杀
    import time

    time.sleep(2)
    for pid, _db in conflicts:
        try:
            os.kill(pid, 0)  # 存活探测
        except (ProcessLookupError, PermissionError):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


@app.command("restart")
def restart() -> None:
    """重启 Ethan 后台服务。"""
    console = Console()
    if _is_installed():
        _launchctl("unload", str(PLIST_PATH))
        # launchd 的进程停了，但可能还有别的实例占着端口，先清干净再拉起，
        # 否则新进程绑不上，重启看起来无效。
        _stop_leftover_instances(console)
        result = _launchctl("load", str(PLIST_PATH))
        if result.returncode != 0:
            console.print(f"[red]重启失败：{result.stderr.strip()}[/red]")
            raise typer.Exit(1)
        console.print("[green]✓ 服务已重启。[/green]")
    else:
        from ethan.interface.commands.update import _restart_serve
        _restart_serve(None)


@app.command("stop")
def stop() -> None:
    """停止 Ethan 后台服务。"""
    console = Console()
    if _is_installed():
        _launchctl("unload", str(PLIST_PATH))
        console.print("[green]✓ 服务已停止。[/green]")
    else:
        import signal

        from ethan.interface.commands.update import _find_serve_pid, _wait_pid_gone
        pid = _find_serve_pid()
        if not pid:
            console.print("[yellow]未发现后台运行的 ethan serve 进程。[/yellow]")
            return
        console.print(f"[dim]发送 SIGTERM 到 ethan serve (pid={pid})...[/dim]")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if not _wait_pid_gone(pid, timeout=8):
            console.print(f"[yellow]SIGTERM 超时，改发 SIGKILL (pid={pid})...[/yellow]")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _wait_pid_gone(pid, timeout=2)
        console.print("[green]✓ ethan serve 已停止。[/green]")


def _parse_launchctl_output(text: str) -> dict:
    """Extract key fields from launchctl list output."""
    import re
    fields = {}
    for key, pattern in [
        ("pid", r'"PID"\s*=\s*(\d+)'),
        ("exit", r'"LastExitStatus"\s*=\s*(\d+)'),
        ("exe", r'"Program"\s*=\s*"([^"]+)"'),
    ]:
        m = re.search(pattern, text)
        if m:
            fields[key] = m.group(1)
    return fields


@app.command("status")
def status() -> None:
    """查看 Ethan 服务运行状态。"""
    console = Console()
    if not _is_installed():
        console.print("[yellow]服务未安装。运行 [bold]ethan server install[/bold] 可安装开机自启服务。[/yellow]")
        return
    result = _launchctl("list", PLIST_NAME)
    launchd_pid: int | None = None
    if result.returncode != 0 or not result.stdout.strip() or result.stdout.strip() == "-":
        console.print("[yellow]● 服务已安装但当前未在运行[/yellow]")
        console.print(f"  plist:  {PLIST_PATH}")
    else:
        fields = _parse_launchctl_output(result.stdout)
        console.print("[green]● 服务运行中[/green]")
        if "pid" in fields:
            console.print(f"  PID:    {fields['pid']}")
            try:
                launchd_pid = int(fields["pid"])
            except ValueError:
                launchd_pid = None
        if "exe" in fields:
            console.print(f"  程序:   {fields['exe']}")
        console.print(f"  日志:   {Path.home() / '.ethan' / 'logs' / 'api.out.log'}")
        console.print(f"  plist:  {PLIST_PATH}")

    # 多实例告警：多个 serve 抢同一份 sessions.db / 同一端口时，桌面端会表现为
    # 「反复失联」（连接被踢断）。这种情况在 status 里必须显式提示，否则用户只会
    # 看到「服务运行中」而不知道后台还在互相打架。
    #
    # 但 status 自身是独立的短命 CLI 进程：正常运行的那个常驻 server 并不是当前
    # 进程，若不排除就会被 _find_conflicting_servers 误报成「冲突」——只要有 1 个
    # 健康 server 在跑，status 就永远多报 1 个（它数的那个 pid 恰恰是唯一的正主）。
    #
    # 合法正主有两条来源，必须都给上：
    # 1. /tmp/ethan/server.pid —— serve 自己写的；
    # 2. **launchd 的 PID** —— launchd 托管的实例带 ETHAN_NO_WATCHDOG=1，**不写**
    #    server.pid。只用第 1 条的话，launchd 场景下 legit_pid 恒为 None，唯一的
    #    正主会被报成冲突（实测如此），用户每次 status 都看到假的「多实例」告警。
    exclude: set[int] = set()
    try:
        from ethan.watchdog import SERVER_PID_FILE, _read_pid

        pid_file_pid = _read_pid(SERVER_PID_FILE)
        if pid_file_pid:
            exclude.add(pid_file_pid)
    except Exception:
        pass
    if launchd_pid:
        exclude.add(launchd_pid)

    try:
        from ethan.interface.cli import _find_conflicting_servers

        conflicts = _find_conflicting_servers(
            extra_exclude_pids=exclude or None
        )
    except Exception:
        conflicts = []
    if conflicts:
        console.print()
        console.print("[yellow]⚠ 检测到多个 ethan 实例在运行，会互相抢端口/数据库：[/yellow]")
        for pid, db in conflicts:
            console.print(f"    pid={pid}  →  {db}")
        console.print("  [dim]建议只保留一个：ethan server stop 后重启，或卸载 launchd 服务。[/dim]")
