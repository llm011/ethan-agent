"""trust 子命令组：管理文件写入授权的信任目录白名单。

命令：
  ethan trust add <dir>      添加信任目录（该目录及子目录内的写入/编辑不再弹授权）
  ethan trust list           列出信任目录
  ethan trust remove <dir>   移除信任目录

存储：config.yaml → tools.trusted_dirs（持久化，跨会话生效）。
默认豁免目录（/tmp 等）见 ethan/tools/builtin/file.py:_is_safe_path；
.secrets 目录永不豁免。
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()
app = typer.Typer(help="管理文件写入授权的信任目录白名单", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def _normalize(dir_path: str) -> str:
    """展开 ~ 并 resolve 成绝对路径（不要求目录已存在——外置卷可能未挂载）。"""
    return str(Path(dir_path).expanduser().resolve())


@app.command("add")
def add_dir(dir_path: str = typer.Argument(..., help="目录路径（支持 ~ 和相对路径），含子目录生效")) -> None:
    """添加信任目录：该目录及子目录内的文件写入/编辑不再弹授权提示。"""
    from ethan.core.config import get_config, save_config

    norm = _normalize(dir_path)
    if norm == "/":
        console.print("[red]拒绝：不能把根目录 / 加入白名单（等于全盘免授权）。[/red]")
        raise typer.Exit(1)
    cfg = get_config()
    if norm in cfg.tools.trusted_dirs:
        console.print(f"[yellow]已在白名单中: {norm}[/yellow]")
        return
    cfg.tools.trusted_dirs.append(norm)
    save_config(cfg)
    console.print(f"[green]✓ 已添加信任目录: {norm}[/green]")
    console.print("[dim]该目录及子目录内的文件写入/编辑不再弹授权提示（.secrets 除外）。[/dim]")


@app.command("list")
def list_dirs() -> None:
    """列出信任目录白名单。"""
    from ethan.core.config import get_config

    dirs = get_config().tools.trusted_dirs
    if not dirs:
        console.print("[dim]（白名单为空。用 ethan trust add <dir> 添加。）[/dim]")
        return
    console.print("[bold]信任目录白名单:[/bold]")
    for d in dirs:
        mark = "" if Path(d).is_dir() else "  [dim](目录当前不存在/未挂载，仍保留配置)[/dim]"
        console.print(f"  [cyan]{d}[/cyan]{mark}")


@app.command("remove")
def remove_dir(dir_path: str = typer.Argument(..., help="要移除的目录（add 时的路径或原样字符串均可）")) -> None:
    """从白名单移除信任目录。"""
    from ethan.core.config import get_config, save_config

    cfg = get_config()
    norm = _normalize(dir_path)
    for candidate in (norm, dir_path):
        if candidate in cfg.tools.trusted_dirs:
            cfg.tools.trusted_dirs.remove(candidate)
            save_config(cfg)
            console.print(f"[green]✓ 已移除: {candidate}[/green]")
            return
    console.print(f"[red]不在白名单中: {dir_path}[/red]")
    console.print("[dim]用 ethan trust list 查看当前白名单。[/dim]")
    raise typer.Exit(1)
