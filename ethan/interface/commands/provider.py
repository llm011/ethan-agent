"""provider 子命令组：管理 LLM provider 连接配置。

命令：
  ethan provider list                    列出所有 provider
  ethan provider set <key>               设置 API key / base_url
"""
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ethan.core.config import ProviderConfig, get_config, reload_config, save_config

console = Console()
app = typer.Typer(help="管理 LLM provider 连接配置", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@app.command("list")
def list_providers() -> None:
    """列出所有已配置的 provider 及状态。"""
    config = get_config()
    table = Table(title="Provider 配置", show_lines=True)
    table.add_column("Key", style="cyan")
    table.add_column("Base URL", style="yellow")
    table.add_column("API Key", style="dim")

    for key, p in config.providers.items():
        key_display = (p.api_key[:12] + "…") if p.api_key else "[red]未配置[/red]"
        url_display = p.base_url or "[dim]默认[/dim]"
        table.add_row(key, url_display, key_display)

    console.print(table)


@app.command("set")
def set_provider(
    key: str = typer.Argument(..., help="Provider key，如 anthropic / openai_compat"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API Key"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="自定义 Base URL"),
) -> None:
    """设置 provider 的 API key 或 base_url。"""
    config = get_config()

    if key not in config.providers:
        config.providers[key] = ProviderConfig()

    p = config.providers[key]
    if api_key is not None:
        p.api_key = api_key
    if base_url is not None:
        p.base_url = base_url

    save_config(config)
    reload_config()
    console.print(f"[green]✓ Provider {key!r} 已更新。[/green]")
