"""knowledge 子命令组：管理个人知识库。

命令：
  ethan knowledge list              列出所有知识条目
  ethan knowledge search <query>    搜索知识库
  ethan knowledge add               添加新条目
"""
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ethan.core.config import CONFIG_DIR
from ethan.knowledge.base import FilesystemKnowledgeBase

console = Console()
app = typer.Typer(help="管理个人知识库", invoke_without_command=True)

_KB_DIR = CONFIG_DIR / "knowledge"


def _get_kb() -> FilesystemKnowledgeBase:
    return FilesystemKnowledgeBase(_KB_DIR)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@app.command("list")
def list_knowledge() -> None:
    """列出所有知识库条目。"""
    kb = _get_kb()
    items = kb.list_all()
    if not items:
        console.print("[dim]Knowledge base is empty. Add notes with: ethan knowledge add[/dim]")
        return

    table = Table(title="Knowledge Base", show_lines=True)
    table.add_column("Title", style="cyan", max_width=40)
    table.add_column("Tags", style="yellow")
    table.add_column("Preview", max_width=50)

    for item in items:
        table.add_row(item.title, ", ".join(item.tags), item.snippet(80))

    console.print(table)


@app.command("search")
def search_knowledge(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, "-n", "--limit", help="Max results"),
) -> None:
    """搜索知识库。"""
    kb = _get_kb()
    results = kb.search(query, limit=limit)
    if not results:
        console.print(f"[dim]No results for: {query}[/dim]")
        return
    for item in results:
        console.print(f"\n[bold cyan]{item.title}[/bold cyan] [dim]{item.source}[/dim]")
        console.print(item.snippet(200))


@app.command("add")
def add_knowledge(
    title: str = typer.Argument(..., help="Title of the note"),
    file: Optional[str] = typer.Option(None, "-f", "--file", help="Read content from file"),
    tags: Optional[str] = typer.Option(None, "-t", "--tags", help="Comma-separated tags"),
) -> None:
    """添加新的知识库条目。"""
    if file:
        from pathlib import Path
        content = Path(file).expanduser().read_text(encoding="utf-8")
    else:
        console.print("[dim]Enter content (Ctrl+D to finish):[/dim]")
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        content = "\n".join(lines)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    kb = _get_kb()
    path = kb.add(title, content, tags=tag_list)
    console.print(f"[green]✓ Saved: {path}[/green]")
