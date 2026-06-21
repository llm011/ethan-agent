"""session 子命令组：管理对话会话。

命令：
  ethan session list              列出最近的会话
  ethan session show <id>         查看某个会话摘要
  ethan session delete <id>       删除会话
"""
import asyncio
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from ethan.memory.session import SessionStore

console = Console()
app = typer.Typer(help="管理对话会话", invoke_without_command=True)


def _user_session_db_path() -> "Path":
    """CLI session 命令默认操作 admin 用户的会话库。"""
    from ethan.core.users import get_user_store
    from ethan.core.paths import user_sessions_db_path
    return user_sessions_db_path(get_user_store().get_admin_user_id())


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_sessions(
    limit: int = typer.Option(20, "-n", "--limit", help="显示数量"),
) -> None:
    """列出最近的会话。"""
    async def _run():
        store = SessionStore(db_path=_user_session_db_path())
        await store.init()
        sessions = await store.list_recent(limit)
        await store.close()

        if not sessions:
            console.print("[dim]暂无历史会话。[/dim]")
            return

        table = Table(title="历史会话", show_lines=True)
        table.add_column("ID", style="cyan", max_width=20)
        table.add_column("标题", max_width=40)
        table.add_column("模型", style="yellow")
        table.add_column("时间", style="dim")

        for s in sessions:
            t = datetime.fromtimestamp(s.updated_at).strftime("%m-%d %H:%M")
            table.add_row(s.id, s.title, s.model, t)

        console.print(table)

    asyncio.run(_run())


@app.command("show")
def show_session(
    session_id: str = typer.Argument(..., help="会话 ID"),
) -> None:
    """查看某个会话的消息摘要。"""
    async def _run():
        store = SessionStore(db_path=_user_session_db_path())
        await store.init()
        session = await store.load(session_id)
        await store.close()

        if not session:
            console.print(f"[red]会话 {session_id!r} 不存在。[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]{session.title}[/bold]  [dim]({session.model})[/dim]\n")
        for msg in session.messages:
            if msg.role == "user":
                console.print(f"[green]> {msg.content[:80]}[/green]")
            elif msg.role == "assistant" and msg.content:
                preview = msg.content[:100].replace("\n", " ")
                console.print(f"  {preview}{'…' if len(msg.content) > 100 else ''}")

    asyncio.run(_run())


@app.command("delete")
def delete_session(
    session_id: str = typer.Argument(..., help="要删除的会话 ID"),
) -> None:
    """删除一个会话及其所有消息。"""
    async def _run():
        store = SessionStore(db_path=_user_session_db_path())
        await store.init()
        ok = await store.delete(session_id)
        await store.close()

        if ok:
            console.print(f"[green]✓ 已删除会话：{session_id}[/green]")
        else:
            console.print(f"[red]会话 {session_id!r} 不存在。[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())
