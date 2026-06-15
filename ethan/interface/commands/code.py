"""code 子命令组：ACP Coding Agent commands。

命令：
  ethan code "query"            Dispatch task to an ACP agent
  ethan code --list             List supported ACP agents
"""
import typer
import shutil
import sys
import os
from typing import Optional
from rich.console import Console

try:
    import pexpect
    _pexpect_available = True
except ImportError:
    _pexpect_available = False

console = Console()
app = typer.Typer(help="ACP Coding Agent commands", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    query: Optional[str] = typer.Argument(None, help="The task query to dispatch"),
    list_agents: bool = typer.Option(False, "--list", help="List supported ACP agents"),
    agent: str = typer.Option("claude", "--agent", help="Specify the agent to use (e.g. claude, opencode)"),
) -> None:
    if list_agents:
        console.print("[bold]Supported ACP agents:[/bold]")
        console.print("- [cyan]claude[/cyan] (Claude Code)")
        console.print("- [cyan]opencode[/cyan] (OpenCode)")
        return

    if query is None:
        if ctx.invoked_subcommand is None:
            console.print(ctx.get_help())
        return
        
    _run_persistent_session(agent, query)


def _run_persistent_session(agent_name: str, query: str) -> None:
    """Run a persistent CLI session using pexpect."""
    if not _pexpect_available:
        console.print("[red]pexpect is not installed. Run: pip install ethan-agent[code][/red]")
        raise typer.Exit(1)

    agent_bin = shutil.which(agent_name)
    if not agent_bin:
        console.print(f"[red]Error: {agent_name} command not found.[/red]")
        if agent_name == "claude":
            console.print("Install Claude Code: https://claude.ai/code")
        raise typer.Exit(1)

    console.print(f"[dim]Starting persistent {agent_name} session...[/dim]")

    try:
        # We spawn the agent in interactive mode
        child = pexpect.spawn(agent_bin, encoding='utf-8', timeout=None, dimensions=(24, 80))

        try:
            child.expect(r'(>|\$|>>>|\?)', timeout=10)
            if child.before:
                sys.stdout.write(child.before)
            if child.after:
                sys.stdout.write(child.after)
        except pexpect.TIMEOUT:
            pass

        console.print(f"\\n[dim]Sending initial query: {query}[/dim]")
        child.sendline(query)

        child.interact()

    except pexpect.TIMEOUT:
        console.print("\\n[red]Timeout waiting for agent prompt.[/red]")
    except pexpect.EOF:
        console.print("\\n[dim]Session ended.[/dim]")
    except Exception as e:
        console.print(f"\\n[red]Error: {e}[/red]")
        
