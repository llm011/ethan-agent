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
    from ethan.interface.commands import model as model_cmd
    from ethan.interface.commands import provider as provider_cmd
    from ethan.interface.commands import router as router_cmd
    from ethan.interface.commands import schedule as schedule_cmd
    from ethan.interface.commands import server as server_cmd
    from ethan.interface.commands import session as session_cmd
    from ethan.interface.commands import skill as skill_cmd
    from ethan.interface.commands import update as update_cmd
    from ethan.interface.commands import wechat as wechat_cmd

    app.add_typer(model_cmd.app, name="model")
    app.add_typer(provider_cmd.app, name="provider")
    app.add_typer(session_cmd.app, name="session")
    app.add_typer(skill_cmd.app, name="skill")
    app.add_typer(schedule_cmd.app, name="schedule")
    app.add_typer(knowledge_cmd.app, name="knowledge")
    app.add_typer(code_cmd.app, name="code")
    app.add_typer(update_cmd.app, name="update")
    app.add_typer(channel_cmd.app, name="channel")
    app.add_typer(router_cmd.app, name="router")
    app.add_typer(command_cmd.app, name="command")
    app.add_typer(wechat_cmd.app, name="wechat")
    app.add_typer(server_cmd.app, name="server")


serve_app = typer.Typer(help="管理 API 服务")
app.add_typer(serve_app, name="serve")

@serve_app.callback(invoke_without_command=True)
def serve_main(
    ctx: typer.Context,
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8900, "--port", help="Bind port"),
) -> None:
    """Start the HTTP API server. Default runs in foreground."""
    if ctx.invoked_subcommand is None:
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


def _launch_web(port: int = 8900, url: Optional[str] = None) -> None:
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
    port: int = typer.Option(8900, "--port", help="Web UI port"),
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

    # ── Auto-launch web UI on port 8900 ──────────────────────────────
    if not prompt:
        _launch_web(8900)
    # ─────────────────────────────────────────────────────────────────

    import asyncio

    from ethan.interface.repl import ProfileSwitchException, run_once, run_repl

    if prompt and not resume:
        agent = _build_agent(model, user_id=profile or "")
        if yes:
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
