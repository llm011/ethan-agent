"""schedule 子命令组：管理定时任务。

命令：
  ethan schedule list             列出所有定时任务
  ethan schedule add              添加定时任务
  ethan schedule remove <id>      删除定时任务
  ethan schedule pause <id>       暂停
  ethan schedule resume <id>      恢复
"""
import typer
from rich.console import Console
from rich.table import Table

from ethan.scheduler.cron import Scheduler

console = Console()
app = typer.Typer(help="Manage scheduled tasks", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def _get_scheduler() -> Scheduler:
    s = Scheduler()
    s.start()
    return s


@app.command("list")
def list_jobs() -> None:
    """List all scheduled jobs."""
    s = _get_scheduler()
    jobs = s.list_jobs()
    s.shutdown()

    if not jobs:
        console.print("[dim]No scheduled jobs.[/dim]")
        return

    table = Table(title="Scheduled Jobs", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("Trigger", style="yellow")
    table.add_column("Next Run", style="dim")

    for j in jobs:
        table.add_row(j["id"], j["trigger"], j["next_run"])

    console.print(table)


@app.command("remove")
def remove_job(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
) -> None:
    """Remove a scheduled job."""
    s = _get_scheduler()
    ok = s.remove(job_id)
    s.shutdown()

    if ok:
        console.print(f"[green]✓ Removed job: {job_id}[/green]")
    else:
        console.print(f"[red]Job '{job_id}' not found.[/red]")
        raise typer.Exit(1)


@app.command("pause")
def pause_job(
    job_id: str = typer.Argument(..., help="Job ID to pause"),
) -> None:
    """Pause a scheduled job."""
    s = _get_scheduler()
    ok = s.pause(job_id)
    s.shutdown()

    if ok:
        console.print(f"[green]✓ Paused: {job_id}[/green]")
    else:
        console.print(f"[red]Job '{job_id}' not found.[/red]")
        raise typer.Exit(1)


@app.command("resume")
def resume_job(
    job_id: str = typer.Argument(..., help="Job ID to resume"),
) -> None:
    """Resume a paused job."""
    s = _get_scheduler()
    ok = s.resume(job_id)
    s.shutdown()

    if ok:
        console.print(f"[green]✓ Resumed: {job_id}[/green]")
    else:
        console.print(f"[red]Job '{job_id}' not found.[/red]")
        raise typer.Exit(1)
