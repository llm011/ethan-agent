"""plugin 子命令组：管理工具插件（搜索后端等可插拔组件）。

命令：
  ethan plugin list                    列出所有可用插件及启用状态
  ethan plugin add <name>              添加/启用插件（交互式配置）
  ethan plugin remove <name>           移除/禁用插件
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ethan.core.config import get_config, save_config

console = Console()
app = typer.Typer(help="管理工具插件（搜索后端等可插拔组件）", invoke_without_command=True)


# ── 插件注册表 ─────────────────────────────────────────────────────────────────
# 每个插件定义：name, description, config_fields（需要用户输入的字段）, config_path（写入 config 的位置）

class _PluginField:
    """插件需要用户输入的单个配置字段。"""
    def __init__(self, key: str, label: str, secret: bool = False, default: str = "", hint: str = ""):
        self.key = key
        self.label = label
        self.secret = secret      # True 则输入时隐藏（如 API key）
        self.default = default
        self.hint = hint          # 输入提示

class _PluginDef:
    """插件定义。"""
    def __init__(self, name: str, description: str, fields: list[_PluginField], config_path: str):
        self.name = name
        self.description = description
        self.fields = fields
        self.config_path = config_path  # 点分路径前缀，如 "tools.web_search"


PLUGIN_REGISTRY: dict[str, _PluginDef] = {
    "tavily": _PluginDef(
        name="tavily",
        description="Tavily AI 搜索引擎（需要 API Key，https://tavily.com 免费注册）",
        fields=[
            _PluginField("api_key", "Tavily API Key", secret=True, hint="tvly-xxxxx"),
        ],
        config_path="tools.web_search",
    ),
    "searxng": _PluginDef(
        name="searxng",
        description="SearXNG 自建搜索实例（需要 base_url，通常是 Docker 部署）",
        fields=[
            _PluginField("base_url", "SearXNG Base URL", hint="http://localhost:8888"),
        ],
        config_path="tools.web_search",
    ),
}


# ── 命令实现 ────────────────────────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_plugins() -> None:
    """列出所有可用插件及启用状态。"""
    config = get_config()
    table = Table(title="可用插件", show_lines=True)
    table.add_column("名称", style="cyan")
    table.add_column("说明")
    table.add_column("状态", style="green")

    for name, plugin in PLUGIN_REGISTRY.items():
        enabled = _is_enabled(config, plugin)
        status = "[green]已启用[/green]" if enabled else "[dim]未配置[/dim]"
        table.add_row(name, plugin.description, status)

    # duckduckgo 作为内置兜底
    table.add_row("duckduckgo", "DuckDuckGo 搜索（内置，零配置兜底）", "[green]始终可用[/green]")
    console.print(table)


@app.command("add")
def add_plugin(
    name: str = typer.Argument(..., help="插件名称，如 tavily / searxng"),
) -> None:
    """添加/启用插件，交互式输入所需配置。"""
    plugin = PLUGIN_REGISTRY.get(name)
    if not plugin:
        console.print(f"[red]未知插件: {name}[/red]")
        console.print(f"可用插件: {', '.join(PLUGIN_REGISTRY.keys())}")
        raise typer.Exit(1)

    console.print(f"\n[bold]配置插件: {name}[/bold]")
    console.print(f"  {plugin.description}\n")

    # 交互式收集配置
    values: dict[str, str] = {}
    for field in plugin.fields:
        prompt = f"  {field.label}"
        if field.hint:
            prompt += f" [dim]({field.hint})[/dim]"
        prompt += ": "
        if field.secret:
            value = typer.prompt(f"  {field.label}", hide_input=True, default=field.default or "")
        else:
            value = typer.prompt(f"  {field.label}", default=field.default or "")
        if not value.strip():
            console.print(f"[yellow]跳过: {field.label} 未填写[/yellow]")
            raise typer.Exit(1)
        values[field.key] = value.strip()

    # 写入 config
    config = get_config()
    _apply_plugin_config(config, plugin, values)
    save_config(config)

    console.print(f"\n[green]✓ 插件 {name} 配置已写入。[/green]")
    console.print("[yellow]⚠ 需要重启 server 生效：ethan server restart[/yellow]")


@app.command("remove")
def remove_plugin(
    name: str = typer.Argument(..., help="要移除的插件名称"),
) -> None:
    """移除/禁用插件（清除其配置）。"""
    plugin = PLUGIN_REGISTRY.get(name)
    if not plugin:
        console.print(f"[red]未知插件: {name}[/red]")
        raise typer.Exit(1)

    config = get_config()
    if not _is_enabled(config, plugin):
        console.print(f"[dim]插件 {name} 当前未启用，无需移除。[/dim]")
        raise typer.Exit()

    # 清除配置
    _clear_plugin_config(config, plugin)
    save_config(config)

    console.print(f"[green]✓ 插件 {name} 已移除。[/green]")
    console.print("[yellow]⚠ 需要重启 server 生效：ethan server restart[/yellow]")


# ── 辅助函数 ────────────────────────────────────────────────────────────────────

def _is_enabled(config, plugin: _PluginDef) -> bool:
    """检测插件是否已启用（配置字段有值）。"""
    obj = _resolve_config_obj(config, plugin.config_path)
    if obj is None:
        return False
    for field in plugin.fields:
        if getattr(obj, field.key, ""):
            return True
    return False


def _apply_plugin_config(config, plugin: _PluginDef, values: dict[str, str]) -> None:
    """将用户输入写入 config 对象。"""
    obj = _resolve_config_obj(config, plugin.config_path)
    if obj is None:
        return
    for key, val in values.items():
        if hasattr(obj, key):
            setattr(obj, key, val)


def _clear_plugin_config(config, plugin: _PluginDef) -> None:
    """清除插件配置字段。"""
    obj = _resolve_config_obj(config, plugin.config_path)
    if obj is None:
        return
    for field in plugin.fields:
        if hasattr(obj, field.key):
            setattr(obj, field.key, "")


def _resolve_config_obj(config, path: str):
    """按点分路径解析到 config 子对象。如 "tools.web_search" → config.tools.web_search"""
    obj = config
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj
