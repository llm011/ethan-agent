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
    <key>StandardOutPath</key>
    <string>{ethan_home}/logs/api.out.log</string>
    <key>StandardErrorPath</key>
    <string>{ethan_home}/logs/api.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{bin_dir}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
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



def uninstall() -> None:
    """卸载 Ethan 开机自启服务。"""
    console = Console()
    if not _is_installed():
        console.print("[yellow]服务未安装。[/yellow]")
        return
    _launchctl("unload", str(PLIST_PATH))
    PLIST_PATH.unlink(missing_ok=True)
    console.print("[green]✓ 服务已卸载。[/green]")


@app.command("restart")
def restart() -> None:
    """重启 Ethan 后台服务。"""
    console = Console()
    if _is_installed():
        _launchctl("unload", str(PLIST_PATH))
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
    if result.returncode != 0 or not result.stdout.strip() or result.stdout.strip() == "-":
        console.print("[yellow]● 服务已安装但当前未在运行[/yellow]")
        console.print(f"  plist:  {PLIST_PATH}")
    else:
        fields = _parse_launchctl_output(result.stdout)
        console.print("[green]● 服务运行中[/green]")
        if "pid" in fields:
            console.print(f"  PID:    {fields['pid']}")
        if "exe" in fields:
            console.print(f"  程序:   {fields['exe']}")
        console.print(f"  日志:   {Path.home() / '.ethan' / 'logs' / 'api.out.log'}")
        console.print(f"  plist:  {PLIST_PATH}")
