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

    app.add_typer(model_cmd.app, name="model")
    app.add_typer(provider_cmd.app, name="provider")
    app.add_typer(session_cmd.app, name="session")
    app.add_typer(skill_cmd.app, name="skill")
    app.add_typer(schedule_cmd.app, name="schedule")
    app.add_typer(knowledge_cmd.app, name="knowledge")


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8900, "--port", help="Bind port"),
) -> None:
    """Start the HTTP API server."""
    from ethan.interface.api import run_server
    run_server(host=host, port=port)


_register_subcommands()


def _build_agent(model: str | None = None):
    from ethan.core.agent import Agent
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.builtin.acp import DelegateCodingTool
    from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
    from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeSearchTool
    from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
    from ethan.tools.builtin.shell import ShellTool
    from ethan.tools.builtin.web import WebFetchTool
    from ethan.tools.builtin.web_search import WebSearchTool
    from ethan.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())
    registry.register(ScheduleCreateTool())
    registry.register(ScheduleListTool())
    registry.register(ScheduleRemoveTool())
    registry.register(KnowledgeSearchTool())
    registry.register(KnowledgeAddTool())
    registry.register(DelegateCodingTool())

    skills = SkillRegistry()
    skills.load()

    return Agent(tool_registry=registry, skill_registry=skills, model=model)


@app.callback(invoke_without_command=True)
def chat(
    ctx: typer.Context,
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Model ID"),
    prompt: Optional[str] = typer.Option(None, "-p", "--prompt", help="Single-turn prompt"),
    resume: Optional[str] = typer.Option(None, "-r", "--resume", help="Resume session (ID or 'last')"),
) -> None:
    """Start a conversation. Defaults to lightweight REPL mode."""
    if ctx.invoked_subcommand is not None:
        return

    import uvloop
    from ethan.interface.repl import run_repl, run_once

    agent = _build_agent(model)
    if prompt and not resume:
        uvloop.run(run_once(agent, prompt))
    else:
        uvloop.run(run_repl(agent, resume_id=resume))


if __name__ == "__main__":
    app()
