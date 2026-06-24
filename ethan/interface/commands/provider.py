"""provider 子命令组：管理 LLM provider 连接配置。

命令：
  ethan provider list                    列出所有 provider
  ethan provider set <key>               设置 API key / base_url
  ethan provider presets                 列出内置 provider 预设(一键配置)
"""
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ethan.core.config import ModelEntry, ProviderConfig, get_config, reload_config, save_config
from ethan.core.provider_presets import PROVIDER_PRESETS, get_preset

console = Console()
app = typer.Typer(help="管理 LLM provider 连接配置", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_providers() -> None:
    """列出所有已配置的 provider 及状态。"""
    config = get_config()
    table = Table(title="Provider 配置", show_lines=True)
    table.add_column("Key", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Base URL", style="yellow")
    table.add_column("API Key", style="dim")

    for key, p in config.providers.items():
        key_display = (p.api_key[:12] + "…") if p.api_key else "[red]未配置[/red]"
        url_display = p.base_url or "[dim]默认[/dim]"
        table.add_row(key, p.type, url_display, key_display)

    console.print(table)


@app.command("presets")
def list_presets() -> None:
    """列出内置 provider 预设(用 `ethan provider set <key>` 一键配置)。"""
    table = Table(title="内置 Provider 预设", show_lines=True)
    table.add_column("Key", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Base URL", style="yellow")
    table.add_column("说明")
    for key, p in PROVIDER_PRESETS.items():
        table.add_row(key, p.get("type", ""), p.get("base_url", ""), p.get("description", ""))
    console.print(table)
    console.print("\n[dim]用法:ethan provider set glm --api-key <你的key>[/dim]")


@app.command("set")
def set_provider(
    key: str = typer.Argument(..., help="Provider key，如 anthropic / openai_compat / glm（预设）"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API Key"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="自定义 Base URL（不填则用预设/已有值）"),
    type_: Optional[str] = typer.Option(None, "--type", help="anthropic | openai_compat（不填则用预设/推断）"),
    add_models: bool = typer.Option(True, "--models/--no-models", help="是否把预设的常用模型自动注册进模型列表"),
) -> None:
    """设置 provider 的 API key / base_url / type。

    内置预设(glm 等)会自动填好 base_url / type / disable_prompt_cache,并注册常用模型;
    也可用 --base-url / --type / --models 显式覆盖。
    """
    config = get_config()
    preset = get_preset(key)

    if key not in config.providers:
        config.providers[key] = ProviderConfig()
    p = config.providers[key]

    # type:CLI 显式 > 已有值 > 预设 > 按 key 推断
    if type_ is not None:
        p.type = type_
    elif not getattr(p, "type", None) or p.type == "openai_compat":
        # 未设过或仍是默认推断值时,优先用预设
        if preset and preset.get("type"):
            p.type = preset["type"]
        elif key == "anthropic":
            p.type = "anthropic"
        else:
            p.type = "openai_compat"

    if api_key is not None:
        p.api_key = api_key
    # base_url:CLI 显式 > 预设 > 已有值
    if base_url is not None:
        p.base_url = base_url
    elif preset and preset.get("base_url") and not p.base_url:
        p.base_url = preset["base_url"]
    # disable_prompt_cache:预设要求且用户没显式说过 → 开
    if preset and preset.get("disable_prompt_cache"):
        p.disable_prompt_cache = True

    # 注册预设常用模型(已存在同 id 则跳过)
    added_models: list[str] = []
    if add_models and preset and preset.get("models"):
        existing_ids = {m.id for m in config.models}
        for mid in preset["models"]:
            if mid not in existing_ids:
                config.models.append(ModelEntry(id=mid, provider=key, description=mid))
                added_models.append(mid)

    save_config(config)
    reload_config()
    console.print(f"[green]✓ Provider {key!r} 已更新。[/green]")
    console.print(f"  type={p.type}  base_url={p.base_url or '(默认)'}  disable_prompt_cache={p.disable_prompt_cache}")
    if added_models:
        console.print(f"  已注册模型:[cyan]{', '.join(added_models)}[/cyan]")
        console.print(f"  切换使用:[dim]ethan 的设置页选 {added_models[0]},或在 config.yaml defaults.model[/dim]")
