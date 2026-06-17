"""model 子命令组：管理模型注册表。

命令：
  ethan model list              列出所有模型
  ethan model add <id>          注册新模型
  ethan model remove <id>       删除模型
  ethan model default <id>      设置默认模型
"""
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from ethan.core.config import ModelEntry, get_config, reload_config, save_config

console = Console()
app = typer.Typer(help="管理模型注册表", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_models() -> None:
    """列出所有已配置的模型。"""
    config = get_config()
    table = Table(title="已配置模型", show_lines=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("ID", style="cyan")
    table.add_column("Alias", style="magenta")
    table.add_column("Provider", style="yellow")
    table.add_column("描述")
    table.add_column("默认", style="green", justify="center")

    for idx, m in enumerate(config.models, start=1):
        is_default = "✓" if m.id == config.defaults.model else ""
        alias_str = ", ".join(m.alias) if m.alias else ""
        table.add_row(str(idx), m.id, alias_str, m.provider, m.description, is_default)

    console.print(table)


@app.command("add")
def add_model(
    model_ids: List[str] = typer.Argument(..., help="模型 ID，支持多个，如 gpt-4o gpt-4o-mini"),
    provider: str = typer.Option(..., "-p", "--provider", help="Provider 名称（自定义，如 my-openai）"),
    provider_type: str = typer.Option("openai_compat", "--type", help="Provider 类型：openai_compat | anthropic"),
    description: str = typer.Option("", "-d", "--desc", help="备注描述"),
    alias: Optional[str] = typer.Option(None, "-a", "--alias", help="别名，逗号分隔（只在单模型注册时有效）"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Provider Base URL"),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Provider API Key"),
) -> None:
    """注册一个或多个新模型。"""
    config = get_config()

    # 1. 优先创建或更新 Provider 配置
    provider_updated = False
    if base_url is not None or api_key is not None or provider_type:
        from ethan.core.config import ProviderConfig
        if provider not in config.providers:
            config.providers[provider] = ProviderConfig()
        p = config.providers[provider]

        # 显式传参时才覆盖设置
        if api_key is not None:
            p.api_key = api_key
            provider_updated = True
        if base_url is not None:
            p.base_url = base_url
            provider_updated = True
        if provider_type:
            p.type = provider_type
            provider_updated = True

    # 2. 处理别名（只支持单模型注册）
    alias_list = []
    if alias:
        if len(model_ids) > 1:
            console.print("[yellow]警告：同时注册多个模型时，--alias 参数将被忽略。[/yellow]")
        else:
            alias_list = [a.strip() for a in alias.split(",") if a.strip()]

    # 3. 循环注册模型
    added_models = []
    skipped_models = []
    for mid in model_ids:
        # 检查是否在该 provider 下已存在
        exists = any(m.id == mid and m.provider == provider for m in config.models)
        if exists:
            skipped_models.append(mid)
            continue

        kwargs = {"id": mid, "provider": provider}
        if description:
            kwargs["description"] = description
        if len(model_ids) == 1 and alias_list:
            kwargs["alias"] = alias_list

        config.models.append(ModelEntry(**kwargs))
        added_models.append(mid)

    if skipped_models:
        console.print(f"[yellow]模型 {', '.join(skipped_models)!r} 已存在，跳过。[/yellow]")

    if not added_models:
        if provider_updated:
            save_config(config)
            reload_config()
            console.print(f"[green]✓ Provider '{provider}' 参数已成功更新。[/green]")
        raise typer.Exit()

    # 4. 保存
    save_config(config)
    reload_config()

    console.print(f"[green]✓ 已成功添加模型：{', '.join(added_models)} → {provider}[/green]")
    if len(added_models) == 1 and alias_list:
        console.print(f"[dim]  别名：{', '.join(alias_list)}[/dim]")
    if provider_updated:
        console.print(f"[dim]  已同步配置 provider '{provider}' 的连接参数 (类型: {provider_type})[/dim]")


@app.command("remove")
def remove_model(
    model_id: str = typer.Argument(..., help="要删除的模型 ID (支持 provider/model_id 格式)"),
) -> None:
    """从注册表中删除一个模型。"""
    config = get_config()

    target_provider = None
    target_model = model_id
    if "/" in model_id:
        target_provider, target_model = model_id.split("/", 1)

    original = len(config.models)

    if target_provider:
        config.models = [m for m in config.models if not (m.id == target_model and m.provider == target_provider)]
    else:
        config.models = [m for m in config.models if m.id != target_model]

    if len(config.models) == original:
        console.print(f"[red]模型 {model_id!r} 不存在。[/red]")
        raise typer.Exit(1)

    save_config(config)
    reload_config()
    console.print(f"[green]✓ 已删除：{model_id}[/green]")


@app.command("default")
def set_default(
    model_id: str = typer.Argument(..., help="设为默认的模型 ID (支持 provider/model_id 格式)"),
) -> None:
    """设置对话时使用的默认模型。"""
    config = get_config()

    # 获取完整的带 provider 的标准格式，如果用户输入的有歧义，以配置中的实际 ID 为准
    entry = config.get_model(model_id)
    if not entry:
        console.print(f"[red]模型 {model_id!r} 未注册，请先运行 ethan model add。[/red]")
        raise typer.Exit(1)

    # 存储时使用用户传入的格式，如果用户通过 my-provider/gpt-4 找到的，可以直接存带有 namespace 的，防止重名时飘移
    config.defaults.model = model_id
    save_config(config)
    reload_config()
    console.print(f"[green]✓ 默认模型已设为：{model_id}[/green]")
