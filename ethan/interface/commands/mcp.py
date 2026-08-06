"""mcp 子命令组：管理外部 MCP server 连接。

命令：
  ethan mcp list                列出已配置的 MCP server
  ethan mcp add <name> <url>    添加远程 MCP server（--token 可选）
  ethan mcp remove <name>       删除已配置的 MCP server
  ethan mcp test <name>         测试连接并列出该 server 暴露的工具

示例（滴答清单）：
  ethan mcp add dida365 https://mcp.dida365.com --token <API口令>
  之后 Agent 可直接读写你在滴答清单里的任务/清单/习惯。
"""
import typer
from rich.console import Console
from rich.table import Table

from ethan.core.config import get_config, save_config

console = Console()
app = typer.Typer(help="Manage external MCP servers", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def _find_server(config, name: str):
    for s in config.tools.mcp.servers:
        if s.name == name:
            return s
    return None


@app.command("list")
def list_servers() -> None:
    """List configured MCP servers."""
    config = get_config()
    servers = config.tools.mcp.servers
    if not servers:
        console.print("[dim]No MCP servers configured. Use `ethan mcp add <name> <url>`.[/dim]")
        return

    table = Table(title="MCP Servers")
    table.add_column("Name", style="cyan")
    table.add_column("URL / Command", style="yellow")
    table.add_column("Auth", style="dim")
    table.add_column("Enabled", style="green")
    for s in servers:
        endpoint = s.url or (s.command + (" " + " ".join(s.args)).strip())
        auth = "Bearer" if s.bearer_token else "—"
        table.add_row(s.name, endpoint, auth, "✓" if s.enabled else "✗")
    console.print(table)


@app.command("add")
def add_server(
    name: str = typer.Argument(..., help="Unique server name (prefix for tools, e.g. dida365)"),
    url: str = typer.Argument(..., help="MCP server URL (e.g. https://mcp.dida365.com)"),
    token: str = typer.Option("", "--token", "-t", help="Optional Bearer Token (e.g. 滴答清单 API 口令)"),
) -> None:
    """Add a remote (streamable-http) MCP server."""
    config = get_config()
    if _find_server(config, name):
        console.print(f"[red]MCP server '{name}' already exists.[/red]")
        raise typer.Exit(1)
    from ethan.core.config import MCPServerConfig
    config.tools.mcp.servers.append(
        MCPServerConfig(name=name, url=url, bearer_token=token, enabled=True)
    )
    save_config(config)

    # 已有连接缓存时清掉，让下次 build_tool_registry 重连
    try:
        from ethan.tools.mcp_client import get_mcp_manager
        get_mcp_manager().disconnect_all()
    except Exception:
        pass

    console.print(f"[green]✓ Added MCP server: {name} -> {url}[/green]")
    if token:
        console.print("[dim]Bearer Token 已保存。[/dim]")
    else:
        console.print("[yellow]未设置 Token：若 server 需要认证请在 config.yaml 的 tools.mcp 里补 bearer_token。[/yellow]")


@app.command("remove")
def remove_server(
    name: str = typer.Argument(..., help="Name of the MCP server to remove"),
) -> None:
    """Remove a configured MCP server."""
    config = get_config()
    s = _find_server(config, name)
    if not s:
        console.print(f"[red]MCP server '{name}' not found.[/red]")
        raise typer.Exit(1)
    config.tools.mcp.servers.remove(s)
    save_config(config)
    try:
        from ethan.tools.mcp_client import get_mcp_manager
        get_mcp_manager().disconnect_all()
    except Exception:
        pass
    console.print(f"[green]✓ Removed MCP server: {name}[/green]")


@app.command("test")
def test_server(
    name: str = typer.Argument(..., help="Name of the MCP server to test"),
) -> None:
    """Test connection to a configured MCP server and list its tools."""
    config = get_config()
    s = _find_server(config, name)
    if not s:
        console.print(f"[red]MCP server '{name}' not found.[/red]")
        raise typer.Exit(1)

    from ethan.tools.mcp_client import MCPClient

    client = MCPClient(name=s.name, url=s.url, command=s.command, args=s.args, bearer_token=s.bearer_token)

    import asyncio

    def _run():
        async def main():
            return await client.connect()

        return asyncio.run(main())

    try:
        metas = _run()
    except Exception as e:
        console.print(f"[red]连接失败: {e}[/red]")
        raise typer.Exit(1)
    finally:
        asyncio.run(client.disconnect())

    if not metas:
        console.print("[yellow]已连接，但该 server 未暴露任何工具。[/yellow]")
        return
    table = Table(title=f"MCP Server: {name} — Tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Description", style="dim")
    for m in metas:
        table.add_row(f"{name}_{m['name']}", m["description"])
    console.print(table)