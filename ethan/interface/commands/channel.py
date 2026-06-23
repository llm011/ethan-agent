"""channel 子命令组：管理消息渠道（飞书 Lark 等）。

命令：
  ethan channel list                  列出所有渠道及配置状态
  ethan channel add lark              引导式新建/配置飞书渠道
  ethan channel set lark --app-id ... --app-secret ...   直接设置
  ethan channel unset lark            清除飞书配置
"""
import shutil
import typer
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(help="管理消息渠道（飞书 Lark 等）")

# 支持的渠道及其字段定义：key → (字段名, 说明, 是否必填)
_CHANNEL_FIELDS = {
    "lark": [
        ("app_id", "App ID（cli_ 开头）", True),
        ("app_secret", "App Secret", True),
        ("verification_token", "Verification Token（事件订阅校验，长连接可选）", False),
        ("encrypt_key", "Encrypt Key（事件加密，可选）", False),
    ],
}


@app.command("list")
def list_channels():
    """列出所有渠道及配置状态。"""
    from ethan.core.config import get_config
    config = get_config()

    table = Table(title="消息渠道", show_header=True)
    table.add_column("渠道")
    table.add_column("状态")
    table.add_column("已配置字段")

    # lark
    lark = config.lark
    lark_fields = []
    if lark.app_id:
        lark_fields.append("app_id")
    if lark.app_secret:
        lark_fields.append("app_secret")
    if lark.verification_token:
        lark_fields.append("verification_token")
    if lark.encrypt_key:
        lark_fields.append("encrypt_key")
    lark_ok = bool(lark.app_id and lark.app_secret)
    table.add_row(
        "lark (飞书)",
        "[green]✓ 已启用[/green]" if lark_ok else "[dim]✗ 未配置[/dim]",
        ", ".join(lark_fields) or "—",
    )

    # lark-cli 依赖检查
    lark_cli = shutil.which("lark-cli")
    console.print(table)
    console.print()
    if lark_ok and not lark_cli:
        console.print("[yellow]⚠ 已配置飞书但未检测到 lark-cli，事件监听不会启动。[/yellow]")
        console.print("  安装：参考 https://github.com/larksuite/lark-cli 或 brew/tap 文档")
    console.print("[dim]提示：ethan serve 启动时若有 app_id+app_secret 会自动建立飞书长连接。[/dim]")


@app.command("add")
def add_channel(
    channel: str = typer.Argument(..., help="渠道名，目前支持: lark"),
):
    """引导式新建/配置渠道（会提示每个字段填什么、从哪获取）。"""
    if channel not in _CHANNEL_FIELDS:
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        console.print(f"目前支持: {', '.join(_CHANNEL_FIELDS.keys())}")
        raise typer.Exit(1)

    if channel == "lark":
        _add_lark_interactive()


def _add_lark_interactive():
    """飞书引导式配置。"""
    console.print()
    console.print("[bold cyan]飞书（Lark）渠道配置[/bold cyan]")
    console.print()
    console.print("前置准备（在飞书开放平台 https://open.feishu.cn 创建企业自建应用）：")
    console.print("  1. [凭证与基础信息] → 获取 App ID 和 App Secret")
    console.print("  2. [事件与回调] → 选择 [长连接] 模式（无需公网 IP / Webhook）")
    console.print("  3. 订阅事件：im.message.receive_v1（接收消息）")
    console.print("  4. [权限管理] 开通：im:message、im:message.group_at_msg、im:chat（按需）")
    console.print("  5. 安装 lark-cli（事件监听依赖）：参考 lark-cli 文档")
    console.print()

    values = {}
    for key, label, required in _CHANNEL_FIELDS["lark"]:
        while True:
            hint = "[必填]" if required else "[可选，回车跳过]"
            val = input(f"  {label} {hint}: ").strip()
            if required and not val:
                console.print("[yellow]该字段必填，请重新输入[/yellow]")
                continue
            values[key] = val
            break

    _save_lark(values)
    console.print()
    console.print("[green]✓ 飞书配置已保存[/green]")
    console.print("[dim]重启 ethan serve 后生效（自动建立长连接）。[/dim]")
    console.print("  重启：ethan serve restart")


@app.command("set")
def set_channel(
    channel: str = typer.Argument(..., help="渠道名: lark"),
    app_id: str = typer.Option("", "--app-id", help="App ID"),
    app_secret: str = typer.Option("", "--app-secret", help="App Secret"),
    verification_token: str = typer.Option("", "--verification-token", help="Verification Token"),
    encrypt_key: str = typer.Option("", "--encrypt-key", help="Encrypt Key"),
):
    """直接设置渠道字段（非交互，适合脚本）。"""
    if channel != "lark":
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        raise typer.Exit(1)

    from ethan.core.config import get_config, save_config, reload_config
    config = get_config()
    if app_id:
        config.lark.app_id = app_id
    if app_secret:
        config.lark.app_secret = app_secret
    if verification_token:
        config.lark.verification_token = verification_token
    if encrypt_key:
        config.lark.encrypt_key = encrypt_key
    save_config(config)
    reload_config()
    console.print(f"[green]✓ {channel} 已更新[/green]")


@app.command("unset")
def unset_channel(
    channel: str = typer.Argument(..., help="渠道名: lark"),
):
    """清除渠道配置。"""
    if channel != "lark":
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        raise typer.Exit(1)

    from ethan.core.config import get_config, save_config, reload_config
    config = get_config()
    config.lark.app_id = ""
    config.lark.app_secret = ""
    config.lark.verification_token = ""
    config.lark.encrypt_key = ""
    save_config(config)
    reload_config()
    console.print(f"[green]✓ {channel} 配置已清除[/green]")


def _save_lark(values: dict) -> None:
    from ethan.core.config import get_config, save_config, reload_config
    config = get_config()
    for k, v in values.items():
        if hasattr(config.lark, k):
            setattr(config.lark, k, v)
    save_config(config)
    reload_config()
