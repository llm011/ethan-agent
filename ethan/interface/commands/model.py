"""model 子命令组：管理模型注册表。

命令：
  ethan model list              列出所有模型
  ethan model add <id>          注册新模型
  ethan model remove <id>       删除模型
  ethan model default <id>      设置默认模型
"""
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ethan.core.config import ModelEntry, get_config, reload_config, save_config

console = Console()
app = typer.Typer(help="管理模型注册表", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_models() -> None:
    """列出所有已配置的模型。"""
    config = get_config()
    table = Table(title="已配置模型", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Provider", style="yellow")
    table.add_column("描述")
    table.add_column("默认", style="green", justify="center")

    for m in config.models:
        is_default = "✓" if m.id == config.defaults.model else ""
        table.add_row(m.id, m.provider, m.description, is_default)

    console.print(table)


@app.command("add")
def add_model(
    model_id: str = typer.Argument(..., help="模型 ID，如 gpt-4o"),
    provider: str = typer.Option(..., "-p", "--provider", help="Provider key（anthropic / openai_compat）"),
    description: str = typer.Option("", "-d", "--desc", help="备注描述"),
) -> None:
    """注册一个新模型。"""
    config = get_config()
    if config.get_model(model_id):
        console.print(f"[yellow]模型 {model_id!r} 已存在，跳过。[/yellow]")
        raise typer.Exit(1)

    config.models.append(ModelEntry(id=model_id, provider=provider, description=description))
    save_config(config)
    reload_config()
    console.print(f"[green]✓ 已添加：{model_id} → {provider}[/green]")


@app.command("remove")
def remove_model(
    model_id: str = typer.Argument(..., help="要删除的模型 ID"),
) -> None:
    """从注册表中删除一个模型。"""
    config = get_config()
    original = len(config.models)
    config.models = [m for m in config.models if m.id != model_id]
    if len(config.models) == original:
        console.print(f"[red]模型 {model_id!r} 不存在。[/red]")
        raise typer.Exit(1)

    save_config(config)
    reload_config()
    console.print(f"[green]✓ 已删除：{model_id}[/green]")


@app.command("default")
def set_default(
    model_id: str = typer.Argument(..., help="设为默认的模型 ID"),
) -> None:
    """设置对话时使用的默认模型。"""
    config = get_config()
    if not config.get_model(model_id):
        console.print(f"[red]模型 {model_id!r} 未注册，请先运行 ethan model add。[/red]")
        raise typer.Exit(1)

    config.defaults.model = model_id
    save_config(config)
    reload_config()
    console.print(f"[green]✓ 默认模型已设为：{model_id}[/green]")
