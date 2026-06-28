"""router 子命令组：管理 embedding 语义路由模型。

命令：
  ethan router pull             下载 BGE-small-zh ONNX 模型（Docker/离线预拉）
  ethan router status           查看模型/依赖状态
"""
import typer
from rich.console import Console

console = Console()
app = typer.Typer(help="管理 embedding 语义路由模型", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("pull")
def pull(force: bool = typer.Option(False, "--force", help="已存在也重新下载")) -> None:
    """下载语义路由模型到 ~/.ethan/models/bge-small-zh/（约 95MB）。"""
    try:
        from ethan.skills.router import ensure_model
    except Exception as e:
        console.print(f"[red]router 模块不可用：{e}[/red]")
        raise typer.Exit(1)

    console.print("[dim]正在下载语义路由模型（约 95MB，仅首次）...[/dim]")
    path = ensure_model(force=force)
    if path is None:
        console.print(
            "[red]下载失败。[/red] 请确认已安装可选依赖："
            r"[cyan]pip install 'ethan-agent\[router]'[/cyan]，并检查网络。"
        )
        raise typer.Exit(1)
    console.print(f"[green]✓ 模型就绪：[/green]{path}")


@app.command("status")
def status() -> None:
    """查看 embedding 路由器的依赖与模型状态。"""
    try:
        from ethan.skills.router import _ENCODER, _default_model_dir
    except Exception as e:
        console.print(f"[red]router 模块不可用：{e}[/red]")
        raise typer.Exit(1)

    ready = _ENCODER._ensure()
    model_dir = _default_model_dir()
    if ready:
        console.print(f"[green]✓ 路由器就绪[/green]（模型目录：{model_dir}）")
    else:
        console.print(
            "[yellow]路由器不可用[/yellow] —— 将回退纯关键词匹配。\n"
            r"  装依赖： [cyan]pip install 'ethan-agent\[router]'[/cyan]" "\n"
            "  拉模型： [cyan]ethan router pull[/cyan]"
        )
