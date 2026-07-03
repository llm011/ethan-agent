"""command 子命令组：管理用户自定义斜杠命令。

命令：
  ethan command list              列出所有自定义命令
  ethan command add <name>        添加自定义命令（交互输入描述，可带 -d 直接传）
  ethan command remove <name>     删除自定义命令
"""
import typer
from rich.console import Console

console = Console()
app = typer.Typer(help="管理自定义斜杠命令", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_commands() -> None:
    """列出所有自定义命令。"""
    from ethan.core.custom_commands import load_commands
    from rich.table import Table

    cmds = load_commands()
    if not cmds:
        console.print("[dim]暂无自定义命令。用 ethan command add <name> 添加。[/dim]")
        return

    table = Table(title="自定义命令", show_lines=True)
    table.add_column("命令", style="cyan")
    table.add_column("描述 / Prompt 前缀")
    for name, prompt in cmds.items():
        preview = prompt if len(prompt) <= 80 else prompt[:77] + "…"
        table.add_row(f"/{name}", preview)
    console.print(table)


@app.command("add")
def add_command(
    name: str = typer.Argument(..., help="命令名（不含 /），如 review-cn"),
    description: str = typer.Option("", "-d", "--desc", help="命令描述/Prompt 前缀（不传则交互输入）"),
) -> None:
    """添加自定义斜杠命令。

    用法示例：
      ethan command add review-cn -d "用中文做代码审查，重点关注安全和性能"
      ethan command add greet       # 交互输入
    """
    from ethan.core.custom_commands import load_commands, save_command

    # 校验命令名
    if not name.replace("-", "").replace("_", "").isalnum():
        console.print(f"[red]命令名只允许字母、数字、连字符和下划线。[/red]")
        raise typer.Exit(1)

    # 保留名与内置命令冲突检测
    _BUILTIN = {"new", "btw", "review", "compact", "sessions", "stop",
                "resume", "model", "mode", "token", "owner", "help", "command"}
    if name.lower() in _BUILTIN:
        console.print(f"[red]'{name}' 与内置命令冲突，请换一个名字。[/red]")
        raise typer.Exit(1)

    if not description:
        console.print(f"[bold]添加命令 /{name}[/bold]")
        console.print("[dim]输入这条命令的 Prompt 前缀（用户发 /name <内容> 时，前缀会拼在内容前面一起发给模型）：[/dim]")
        description = typer.prompt("")

    description = description.strip()
    if not description:
        console.print("[red]描述不能为空。[/red]")
        raise typer.Exit(1)

    existing = load_commands()
    if name in existing:
        overwrite = typer.confirm(f"命令 /{name} 已存在，覆盖？", default=False)
        if not overwrite:
            raise typer.Exit()

    save_command(name, description)
    console.print(f"[green]✓ 已保存 /{name}[/green]")
    console.print(f"[dim]使用方式：/{name} <内容>  →  模型收到：\"{description}\\n<内容>\"[/dim]")


@app.command("remove")
def remove_command(
    name: str = typer.Argument(..., help="要删除的命令名（不含 /）"),
) -> None:
    """删除自定义命令。"""
    from ethan.core.custom_commands import remove_command as _remove

    if _remove(name):
        console.print(f"[green]✓ 已删除 /{name}[/green]")
    else:
        console.print(f"[yellow]命令 /{name} 不存在。[/yellow]")
        raise typer.Exit(1)
