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
    from ethan.interface.commands import model as model_cmd
    from ethan.interface.commands import provider as provider_cmd
    from ethan.interface.commands import session as session_cmd
    from ethan.interface.commands import skill as skill_cmd
    from ethan.interface.commands import schedule as schedule_cmd
    from ethan.interface.commands import knowledge as knowledge_cmd
    from ethan.interface.commands import code as code_cmd
    from ethan.interface.commands import update as update_cmd

    app.add_typer(model_cmd.app, name="model")
    app.add_typer(provider_cmd.app, name="provider")
    app.add_typer(session_cmd.app, name="session")
    app.add_typer(skill_cmd.app, name="skill")
    app.add_typer(schedule_cmd.app, name="schedule")
    app.add_typer(knowledge_cmd.app, name="knowledge")
    app.add_typer(code_cmd.app, name="code")
    app.add_typer(update_cmd.app, name="update")


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8900, "--port", help="Bind port"),
) -> None:
    """Start the HTTP API server."""
    from ethan.interface.api import run_server
    run_server(host=host, port=port)


def _launch_web(port: int = 8900, url: Optional[str] = None) -> None:
    import os, socket, subprocess, sys, time, webbrowser
    from pathlib import Path

    if url:
        webbrowser.open(url)
        return

    def _port_open(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", p)) == 0

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
        # Wait up to 60s for the server to come up (cold start can take ~35s)
        for _ in range(300):
            if _port_open(port):
                break
            time.sleep(0.2)

    if _port_open(port):
        webbrowser.open(f"http://localhost:{port}")
    else:
        from rich.console import Console
        Console().print(
            f"[yellow]Web UI 未能自动启动，请手动运行 [bold]ethan serve[/bold] 后访问 http://localhost:{port}[/yellow]"
        )


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
        config.network.auth_token = secrets.token_hex(6)
        save_config(config)
        console.print("[green]✓ Web Token 已重新生成并保存。[/green]")

    token = config.network.auth_token
    if not token:
        console.print("[yellow]当前未配置 Web Token。[/yellow]")
    else:
        console.print(f"Web 登录 Token: [cyan]{token}[/cyan]")


_register_subcommands()


def _build_agent(model: str | None = None):
    from ethan.core.agent import Agent
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.builtin.acp import DelegateCodingTool
    from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
    from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeSearchTool
    from ethan.tools.builtin.memory_write import MemoryWriteTool
    from ethan.tools.builtin.procedure_write import ProcedureWriteTool
    from ethan.tools.builtin.profile_update import ProfileUpdateTool
    from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
    from ethan.tools.builtin.skill_create import SkillCreateTool
    from ethan.tools.builtin.shell import ShellTool
    from ethan.tools.builtin.search import RipgrepTool, FdTool
    from ethan.tools.builtin.web import WebFetchTool
    from ethan.tools.builtin.web_search import WebSearchTool
    from ethan.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(RipgrepTool())
    registry.register(FdTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())
    registry.register(ScheduleCreateTool())
    registry.register(ScheduleListTool())
    registry.register(ScheduleRemoveTool())
    registry.register(KnowledgeSearchTool())
    registry.register(KnowledgeAddTool())
    registry.register(MemoryWriteTool())
    registry.register(ProcedureWriteTool())
    registry.register(ProfileUpdateTool())
    registry.register(SkillCreateTool())
    registry.register(DelegateCodingTool())

    skills = SkillRegistry()
    skills.load()

    return Agent(tool_registry=registry, skill_registry=skills, model=model, channel="repl")


def version_callback(value: bool):
    if value:
        from ethan import __version__
        import typer
        from rich.console import Console
        console = Console()
        console.print(f"ethan-agent version [cyan]{__version__}[/cyan]")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def chat(
    ctx: typer.Context,
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Model ID"),
    prompt: Optional[str] = typer.Option(None, "-p", "--prompt", help="Single-turn prompt"),
    resume: Optional[str] = typer.Option(None, "-r", "--resume", help="Resume session (ID or 'last')"),
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    """Start a conversation. Defaults to lightweight REPL mode."""
    if ctx.invoked_subcommand is not None:
        return

    # ── Auto-launch web UI on port 8900 ──────────────────────────────
    _launch_web(8900)
    # ─────────────────────────────────────────────────────────────────

    import asyncio
    from ethan.interface.repl import run_repl, run_once

    agent = _build_agent(model)
    if prompt and not resume:
        asyncio.run(run_once(agent, prompt))
    else:
        asyncio.run(run_repl(agent, resume_id=resume))


if __name__ == "__main__":
    app()
