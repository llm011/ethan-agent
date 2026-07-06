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
app = typer.Typer(help="管理消息渠道（飞书 Lark 等）", invoke_without_command=True)


@app.callback()
def _main(ctx: typer.Context):
    """管理消息渠道。无子命令时打印 help。"""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())

# 支持的渠道及其字段定义：key → (字段名, 说明, 是否必填)
_CHANNEL_FIELDS = {
    "lark": [
        ("app_id", "App ID（cli_ 开头）", True),
        ("app_secret", "App Secret", True),
        ("verification_token", "Verification Token（事件订阅校验，长连接可选）", False),
        ("encrypt_key", "Encrypt Key（事件加密，可选）", False),
    ],
}


@app.command("list", context_settings={"allow_extra_args": True})
def list_channels(ctx: typer.Context):
    """列出所有渠道及配置状态。忽略多余参数（如 `list lark` 仍列出全部）。"""
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

    # wechat
    from ethan.interface.wechat_ilink import load_credentials as _wechat_creds
    wechat_cred = _wechat_creds()
    wechat_enabled = bool(config.wechat.enabled)
    wechat_fields = []
    if wechat_cred:
        wechat_fields.append(f"bot_id={wechat_cred.ilink_bot_id[:16]}...")
    if wechat_enabled:
        wechat_fields.append("enabled")
    wechat_ok = bool(wechat_cred and wechat_enabled)
    table.add_row(
        "wechat (微信)",
        "[green]✓ 已启用[/green]" if wechat_ok else (
            "[yellow]已登录，未启用[/yellow]" if wechat_cred else "[dim]✗ 未登录[/dim]"
        ),
        ", ".join(wechat_fields) or "—",
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
    ctx: typer.Context,
    channel: str = typer.Argument(None, help="渠道名，目前支持: lark"),
):
    """引导式新建/配置渠道（会提示每个字段填什么、从哪获取）。"""
    if not channel:
        console.print(ctx.get_help())
        raise typer.Exit()
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

    # 同步到 lark-cli（事件监听依赖它，且必须用同一个 app 才能收到消息）
    _ensure_lark_cli_sync(values.get("app_id", ""), values.get("app_secret", ""))

    console.print("[dim]重启 ethan serve 后生效（自动建立长连接）。[/dim]")
    console.print("  重启：ethan server restart")


@app.command("set")
def set_channel(
    ctx: typer.Context,
    channel: str = typer.Argument(None, help="渠道名: lark"),
    app_id: str = typer.Option("", "--app-id", help="App ID"),
    app_secret: str = typer.Option("", "--app-secret", help="App Secret"),
    verification_token: str = typer.Option("", "--verification-token", help="Verification Token"),
    encrypt_key: str = typer.Option("", "--encrypt-key", help="Encrypt Key"),
):
    """直接设置渠道字段（非交互，适合脚本）。"""
    if not channel:
        console.print(ctx.get_help())
        raise typer.Exit()
    if channel != "lark":
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        raise typer.Exit(1)

    from ethan.core.config import get_config, reload_config, save_config
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
    ctx: typer.Context,
    channel: str = typer.Argument(None, help="渠道名: lark"),
):
    """清除渠道配置。"""
    if not channel:
        console.print(ctx.get_help())
        raise typer.Exit()
    if channel != "lark":
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        raise typer.Exit(1)

    from ethan.core.config import get_config, reload_config, save_config
    config = get_config()
    config.lark.app_id = ""
    config.lark.app_secret = ""
    config.lark.verification_token = ""
    config.lark.encrypt_key = ""
    save_config(config)
    reload_config()
    console.print(f"[green]✓ {channel} 配置已清除[/green]")


def _save_lark(values: dict) -> None:
    from ethan.core.config import get_config, reload_config, save_config
    config = get_config()
    for k, v in values.items():
        if hasattr(config.lark, k):
            setattr(config.lark, k, v)
    save_config(config)
    reload_config()


# ── lark-cli 检测 / 安装 / app 同步 ──────────────────────────────

_LARK_CLI_INSTALL_HINT = (
    "  macOS:  brew install larksuite/tap/lark-cli\n"
    "  或参考: https://github.com/larksuite/lark-cli"
)


def _lark_cli_current_app() -> str | None:
    """读取 lark-cli 当前配置的第一个 app_id，没有返回 None。"""
    import json
    from pathlib import Path
    cfg = Path.home() / ".lark-cli" / "config.json"
    if not cfg.exists():
        return None
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        apps = data.get("apps") or []
        return apps[0].get("appId") if apps else None
    except Exception:
        return None


def _ensure_lark_cli_sync(app_id: str, app_secret: str) -> None:
    """检测 lark-cli 是否安装、app 是否与 config 一致；不一致则引导同步。

    ethan 收飞书消息靠 lark-cli 的长连接，lark-cli 必须用同一个 app
    才能收到事件。这里在配置后自动检查并引导同步，避免「配了却收不到消息」。
    """
    import subprocess

    console.print()
    lark_cli = shutil.which("lark-cli")

    # 1. 没装 → 提示安装
    if not lark_cli:
        console.print("[yellow]⚠ 未检测到 lark-cli，飞书事件监听无法启动[/yellow]")
        console.print("  ethan 收飞书消息依赖 lark-cli 的长连接，请先安装：")
        console.print(_LARK_CLI_INSTALL_HINT)
        console.print("  安装后重新运行 [cyan]ethan channel add lark[/cyan] 完成同步。")
        return

    # 2. 装了 → 检查 app 是否一致
    current = _lark_cli_current_app()
    if current == app_id:
        console.print(f"[green]✓ lark-cli 已绑定同一应用（{app_id}）[/green]")
        return

    # 3. 不一致（或 lark-cli 还没配 app）→ 引导同步
    if current:
        console.print(
            f"[yellow]⚠ lark-cli 当前绑定的是另一个应用：{current}[/yellow]\n"
            f"  你刚配置的是 {app_id}，两者不一致会导致收不到消息。"
        )
    else:
        console.print("[yellow]⚠ lark-cli 还没绑定任何应用[/yellow]")

    console.print("  需要把 app 同步到 lark-cli（用 app secret 初始化）。")
    ans = input("  现在同步？[Y/n]: ").strip().lower()
    if ans in ("n", "no"):
        console.print("[dim]已跳过。手动同步：lark-cli config init --app-id <id> --app-secret-stdin[/dim]")
        return

    if not app_secret:
        console.print("[red]缺少 app_secret，无法同步。请用 `ethan channel set lark --app-secret ...` 补上。[/red]")
        return

    # lark-cli config init --app-id <id> --app-secret-stdin（secret 走 stdin 防泄露）
    try:
        proc = subprocess.run(
            [lark_cli, "config", "init", "--app-id", app_id, "--app-secret-stdin", "--brand", "feishu"],
            input=app_secret.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
    except Exception as e:
        console.print(f"[red]同步失败：{e}[/red]")
        return

    if proc.returncode == 0:
        console.print(f"[green]✓ 已同步应用到 lark-cli（{app_id}）[/green]")
        console.print("[dim]若需要用户身份能力（如以本人身份发消息），再跑：lark-cli auth login --domain im[/dim]")
    else:
        console.print("[red]lark-cli config init 失败[/red]")
        console.print(f"[dim]{proc.stderr.decode(errors='replace').strip()[-400:]}[/dim]")
        console.print("  可手动执行：lark-cli config init --app-id <id> --app-secret-stdin")
