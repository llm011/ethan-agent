"""Ethan CLI 主入口。

命令结构：
  ethan                    启动轻量 REPL（快速）
  ethan -p "你好"          直接发送一句并返回
  ethan -m MODEL           用指定模型
  ethan -r last            恢复上次会话
  ethan model ...          管理模型注册表
  ethan provider ...       管理 provider 连接配置
  ethan session ...        管理对话会话
  ethan skill ...          管理 Skills
  ethan schedule ...       管理定时任务
  ethan knowledge ...      管理个人知识库
  ethan trust ...          管理文件写入授权的信任目录白名单
"""
from typing import Optional

import typer

app = typer.Typer(
    name="ethan",
    help="Ethan — Personal AI Agent",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)


def _register_subcommands():
    from ethan.interface.commands import channel as channel_cmd
    from ethan.interface.commands import code as code_cmd
    from ethan.interface.commands import command as command_cmd
    from ethan.interface.commands import knowledge as knowledge_cmd
    from ethan.interface.commands import mcp as mcp_cmd
    from ethan.interface.commands import model as model_cmd
    from ethan.interface.commands import plugin as plugin_cmd
    from ethan.interface.commands import provider as provider_cmd
    from ethan.interface.commands import router as router_cmd
    from ethan.interface.commands import schedule as schedule_cmd
    from ethan.interface.commands import secret as secret_cmd
    from ethan.interface.commands import server as server_cmd
    from ethan.interface.commands import session as session_cmd
    from ethan.interface.commands import setup as setup_cmd
    from ethan.interface.commands import skill as skill_cmd
    from ethan.interface.commands import trust as trust_cmd
    from ethan.interface.commands import update as update_cmd

    app.add_typer(model_cmd.app, name="model")
    app.add_typer(provider_cmd.app, name="provider")
    app.add_typer(plugin_cmd.app, name="plugin")
    app.add_typer(session_cmd.app, name="session")
    app.add_typer(skill_cmd.app, name="skill")
    app.add_typer(schedule_cmd.app, name="schedule")
    app.add_typer(secret_cmd.app, name="secret")
    app.add_typer(knowledge_cmd.app, name="knowledge")
    app.add_typer(mcp_cmd.app, name="mcp")
    app.add_typer(code_cmd.app, name="code")
    app.add_typer(update_cmd.app, name="update")
    app.add_typer(channel_cmd.app, name="channel")
    app.add_typer(router_cmd.app, name="router")
    app.add_typer(command_cmd.app, name="command")
    app.add_typer(server_cmd.app, name="server")
    app.add_typer(setup_cmd.app, name="setup")
    app.add_typer(trust_cmd.app, name="trust")


serve_app = typer.Typer(help="管理 API 服务")
app.add_typer(serve_app, name="serve")


def _find_conflicting_servers() -> list[tuple[int, str]]:
    """找出正在运行、且会写入同一个 sessions.db 的 serve 进程。

    冲突的本质是抢同一个 SQLite 文件（单写者模型），不是抢端口——两个实例用不同
    端口照样互锁。所以判据取「进程实际打开的 sessions.db 路径」与当前进程目标路径
    是否一致，而不是端口是否相同。

    返回 [(pid, db_path), ...]，不含当前进程自身。
    """
    import os
    import subprocess
    from pathlib import Path

    try:
        from ethan.core.paths import user_sessions_db_path

        my_db = user_sessions_db_path().resolve()
    except Exception:
        return []

    me = os.getpid()
    try:
        r = subprocess.run(
            ["pgrep", "-f", "ethan.*serve"],
            capture_output=True,
            text=True,
        )
    except Exception:
        return []

    conflicts: list[tuple[int, str]] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        if pid == me:
            continue
        # 用 lsof 读该进程实际打开的 sessions.db，比解析环境变量更可靠
        try:
            lr = subprocess.run(
                ["lsof", "-p", str(pid)],
                capture_output=True,
                text=True,
            )
        except Exception:
            continue
        for lline in lr.stdout.splitlines():
            if "sessions.db" not in lline:
                continue
            # lsof 最后一列是路径；-journal/-wal 附属文件要归一化回主库
            path = lline.split()[-1]
            for suffix in ("-journal", "-wal", "-shm"):
                if path.endswith(suffix):
                    path = path[: -len(suffix)]
            try:
                if Path(path).resolve() == my_db:
                    conflicts.append((pid, str(my_db)))
                    break
            except Exception:
                continue
    return conflicts


def _server_bind_defaults(explicit_host: Optional[str], explicit_port: Optional[int]) -> tuple[str, int]:
    """解析 serve 实际监听地址：显式参数 > config.yaml server.* > 内置默认。

    config 读不到时（首次运行 / config 损坏）静默回退默认值——绑定地址不该
    因为配置问题导致服务起不来。
    """
    host, port = explicit_host, explicit_port
    if host is None or port is None:
        try:
            from ethan.core.config import get_config

            srv = get_config().server
            if host is None:
                host = srv.host
            if port is None:
                port = srv.port
        except Exception:
            pass
    return host or "0.0.0.0", port or 8900


@serve_app.callback(invoke_without_command=True)
def serve_main(
    ctx: typer.Context,
    host: Optional[str] = typer.Option(
        None, "--host", help="Bind host（默认取 config server.host，缺省 0.0.0.0）"
    ),
    port: Optional[int] = typer.Option(
        None, "--port", help="Bind port（默认取 config server.port，缺省 8900）"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="已有实例在运行同一数据目录时，仍强制启动（不推荐，会导致 SQLite 锁冲突）",
    ),
) -> None:
    """Start the HTTP API server. Default runs in foreground."""
    if ctx.invoked_subcommand is None:
        import os

        host, port = _server_bind_defaults(host, port)
        # ETHAN_NO_WATCHDOG=1 是开发/测试开关（CLAUDE.md 的多 worktree 规范），
        # 语义就是「我知道自己在干什么，别接管我的进程」。worktree 里跑测试时
        # sessions.db 与常驻服务是同一个文件，不放行会把日常开发流程堵死。
        if not force and not os.environ.get("ETHAN_NO_WATCHDOG"):
            conflicts = _find_conflicting_servers()
            if conflicts:
                from rich.console import Console

                console = Console()
                console.print(
                    "[red]✗ 已有 ethan 实例正在使用同一数据目录，拒绝启动。[/red]"
                )
                console.print()
                for pid, db in conflicts:
                    console.print(f"  运行中的实例: [bold]pid={pid}[/bold]")
                    console.print(f"  数据目录:     [dim]{db}[/dim]")
                console.print()
                console.print(
                    "  多个实例同时写同一个 sessions.db 会导致 [bold]database is locked[/bold]，"
                    "定时任务与写入静默失败。"
                )
                console.print()
                console.print("  可选操作：")
                console.print("    ethan serve stop          — 停掉已有实例")
                console.print(
                    "    使用不同数据目录              — 设 ETHAN_DATA_DIR 环境变量"
                )
                console.print(
                    "    开发/测试                    — 设 ETHAN_NO_WATCHDOG=1（跳过本检测，"
                    "不写 PID、不拉起 watchdog）"
                )
                console.print("    ethan serve --force        — 强制启动（不推荐，会锁冲突）")
                raise typer.Exit(1)
        from ethan.interface.api import run_server
        run_server(host=host, port=port)

@serve_app.command("stop")
def serve_stop() -> None:
    """停止后台运行的 serve 进程。"""
    import os
    import signal

    from rich.console import Console

    from ethan.interface.commands.update import _find_serve_pid, _wait_pid_gone

    console = Console()
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
    console.print("[green]✓ ethan serve 已停止[/green]")


def _launch_web(port: Optional[int] = None, url: Optional[str] = None) -> None:
    import os
    import socket
    import subprocess
    import sys
    import time
    import urllib.request
    import webbrowser
    from pathlib import Path

    from rich.console import Console
    console = Console()

    if url:
        webbrowser.open(url)
        return

    # 未显式指定端口时跟随 config server.port（与 serve 用同一套默认值解析）
    _, port = _server_bind_defaults(None, port)

    def _port_open(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", p)) == 0

    def _http_ready(p: int) -> bool:
        """确认 HTTP 服务真正就绪（/api/health 返回 200），而不只是 TCP 端口能连。"""
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/health", timeout=1) as r:
                return r.status == 200
        except Exception:
            return False

    if not _port_open(port):
        # Find the `ethan` script next to the current Python executable
        bin_dir = Path(sys.executable).parent
        ethan_exe = bin_dir / "ethan"
        if not ethan_exe.exists():
            ethan_exe = Path(sys.argv[0])  # fallback to the running script
        subprocess.Popen(
            [str(ethan_exe), "serve", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ},
        )
        # Wait up to 60s for the port to come up (cold start can take ~35s)
        for _ in range(300):
            if _port_open(port):
                break
            time.sleep(0.2)

    # 端口可连 ≠ HTTP 已就绪；再等 /api/health 返回 200 才开浏览器
    ready = False
    for _ in range(150):  # 最多再等 30s
        if _http_ready(port):
            ready = True
            break
        time.sleep(0.2)

    if not ready:
        console.print(
            f"[yellow]Web UI 未能就绪，请手动运行 [bold]ethan serve[/bold] 后访问 http://localhost:{port}[/yellow]"
        )
        return

    webbrowser.open(f"http://localhost:{port}")

    # 提示 token，方便用户登录
    from ethan.core.config import get_config
    token = get_config().network.auth_token
    console.print()
    console.print(f"[dim]🌐 Web UI 已打开：[/dim][cyan]http://localhost:{port}[/cyan]")
    if token:
        console.print(f"[dim]🔑 登录 Token：[/dim][cyan bold]{token}[/cyan bold]")
        console.print("[dim]   REPL 里输入 /token 可随时查看或轮换（/token rotate）[/dim]")
    else:
        console.print("[yellow]当前未配置 Web Token，首次访问可能需要先设置。[/yellow]")
    console.print()


web_app = typer.Typer(help="Web UI 管理")
app.add_typer(web_app, name="web")

@web_app.callback(invoke_without_command=True)
def web_main(
    ctx: typer.Context,
    port: Optional[int] = typer.Option(
        None, "--port", help="Web UI port（默认取 config server.port，缺省 8900）"
    ),
    url: Optional[str] = typer.Option(None, "--url", help="Direct URL to open"),
):
    """Launch the Web UI and open it in the browser."""
    if ctx.invoked_subcommand is None:
        _launch_web(port=port, url=url)

@web_app.command("token")
def web_token(
    rotate: bool = typer.Option(False, "--rotate", help="Rotate and generate a new token"),
) -> None:
    """查看或轮换 Web UI 的登录 Token。"""
    from rich.console import Console
    console = Console()
    from ethan.core.config import get_config, save_config
    config = get_config()

    if rotate:
        import secrets
        config.network.auth_token = secrets.token_hex(16)
        save_config(config)
        console.print("[green]✓ Web Token 已重新生成并保存。[/green]")

    token = config.network.auth_token
    if not token:
        console.print("[yellow]当前未配置 Web Token。[/yellow]")
    else:
        console.print(f"Web 登录 Token: [cyan]{token}[/cyan]")


_register_subcommands()


def _build_agent(model: str | None = None, user_id: str = ""):
    """CLI/REPL Agent 工厂，委托给 core.agent_factory。"""
    from ethan.core.agent_factory import create_agent
    return create_agent(model=model, channel="repl", user_id=user_id, toolset="full")


def version_callback(value: bool):
    if value:
        import typer
        from rich.console import Console

        from ethan import __version__
        console = Console()
        console.print(f"ethan-agent version [cyan]{__version__}[/cyan]")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def chat(
    ctx: typer.Context,
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Model ID"),
    prompt: Optional[str] = typer.Option(None, "-p", "--prompt", help="Single-turn prompt"),
    resume: Optional[str] = typer.Option(None, "-r", "--resume", help="Resume session (ID or 'last')"),
    profile: Optional[str] = typer.Option(None, "--profile", help="User ID/Profile to use"),
    yes: bool = typer.Option(False, "-y", "--yes", "--auto-consent", help="Auto-approve all tool authorizations"),
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    """Start a conversation. Defaults to lightweight REPL mode."""
    if ctx.invoked_subcommand is not None:
        return

    # ── Auto-launch web UI（端口跟随 config server.port）──────────────
    if not prompt:
        _launch_web()
    # ─────────────────────────────────────────────────────────────────

    import asyncio

    from ethan.interface.repl import ProfileSwitchException, run_once, run_repl

    if prompt and not resume:
        agent = _build_agent(model, user_id=profile or "")
        # -p 模式是非交互的单轮执行，必须用 AutoConsentProvider
        # 否则 browser/shell 等需 consent 的工具会挂起或崩溃
        from ethan.core.consent import AutoConsentProvider, set_consent_provider
        set_consent_provider(AutoConsentProvider())
        asyncio.run(run_once(agent, prompt))
    else:
        current_uid = profile or ""
        while True:
            agent = _build_agent(model, user_id=current_uid)
            try:
                asyncio.run(run_repl(agent, resume_id=resume, auto_consent=yes))
                break  # Normal exit (e.g., EOF/exit command)
            except ProfileSwitchException as e:
                current_uid = e.new_uid
                resume = None  # Clear resume to start a fresh session for the new profile
                from rich.console import Console
                Console().print(f"\n[green]Switched to profile: {current_uid}[/green]\n")


if __name__ == "__main__":
    app()
