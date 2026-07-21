"""channel 子命令组：管理消息渠道（飞书 Lark / 微信 WeChat）。

命令：
  ethan channel list                  列出所有渠道及配置状态
  ethan channel add lark              引导式新建/配置飞书渠道
  ethan channel add wechat            扫码登录微信
  ethan channel set lark --app-id ... --app-secret ...   直接设置
  ethan channel unset lark            清除飞书配置
  ethan channel unset wechat          清除微信登录凭证
  ethan channel status wechat         查看微信登录状态
"""
import shutil

import typer
from rich.console import Console
from rich.table import Table

console = Console()
app = typer.Typer(help="管理消息渠道（飞书 / 微信）", invoke_without_command=True)


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
        console.print("  自动安装：[cyan]ethan channel set lark --app-id <id> --app-secret <secret>[/cyan]")
        console.print("  或仅装依赖：[cyan]ethan plugin add lark-channel[/cyan]")
    console.print("[dim]提示：ethan serve 启动时若有 app_id+app_secret 会自动建立飞书长连接。[/dim]")


@app.command("add")
def add_channel(
    ctx: typer.Context,
    channel: str = typer.Argument(None, help="渠道名: lark / wechat"),
):
    """引导式新建/配置渠道。lark=填写凭证，wechat=扫码登录。"""
    if not channel:
        console.print(ctx.get_help())
        raise typer.Exit()

    if channel == "wechat":
        _add_wechat()
        return

    if channel not in _CHANNEL_FIELDS:
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        console.print("目前支持: lark, wechat")
        raise typer.Exit(1)

    if channel == "lark":
        _add_lark_interactive()


@app.command("status")
def status_channel(
    ctx: typer.Context,
    channel: str = typer.Argument(None, help="渠道名: wechat"),
):
    """查看渠道详细状态。"""
    if not channel:
        console.print(ctx.get_help())
        raise typer.Exit()

    if channel == "wechat":
        _status_wechat()
    elif channel == "lark":
        console.print("[dim]飞书状态请查看：ethan channel list[/dim]")
    else:
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        raise typer.Exit(1)


@app.command("set")
def set_channel(
    ctx: typer.Context,
    channel: str = typer.Argument(None, help="渠道名: lark"),
    app_id: str = typer.Option("", "--app-id", help="App ID"),
    app_secret: str = typer.Option("", "--app-secret", help="App Secret"),
    verification_token: str = typer.Option("", "--verification-token", help="Verification Token"),
    encrypt_key: str = typer.Option("", "--encrypt-key", help="Encrypt Key"),
    skip_deps: bool = typer.Option(False, "--skip-deps", help="跳过自动安装 lark-oapi / lark-cli 依赖"),
):
    """直接设置渠道字段（非交互，适合脚本）。保存后会自动安装 lark-oapi / lark-cli 并同步 app。"""
    if not channel:
        console.print(ctx.get_help())
        raise typer.Exit()
    if channel != "lark":
        console.print("[red]set 目前只支持 lark（微信请用 ethan channel add wechat 扫码）[/red]")
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

    # 脚本化配置也触发依赖安装（除非显式 --skip-deps）
    if not skip_deps and (config.lark.app_id or config.lark.app_secret):
        from ethan.interface.lark_deps import ensure_lark_deps
        console.print()
        console.print("[bold]依赖就绪检查与安装[/bold]")
        ensure_lark_deps(
            config.lark.app_id or "",
            config.lark.app_secret or "",
            interactive=True,
            triggered_by="cli",
        )


@app.command("unset")
def unset_channel(
    ctx: typer.Context,
    channel: str = typer.Argument(None, help="渠道名: lark / wechat"),
):
    """清除渠道配置/登录凭证。"""
    if not channel:
        console.print(ctx.get_help())
        raise typer.Exit()

    if channel == "lark":
        from ethan.core.config import get_config, reload_config, save_config
        config = get_config()
        config.lark.app_id = ""
        config.lark.app_secret = ""
        config.lark.verification_token = ""
        config.lark.encrypt_key = ""
        save_config(config)
        reload_config()
        console.print("[green]✓ lark 配置已清除[/green]")
    elif channel == "wechat":
        _unset_wechat()
    else:
        console.print(f"[red]不支持的渠道: {channel}[/red]")
        raise typer.Exit(1)


# ── 飞书 ──────────────────────────────────────────────────────

def _add_lark_interactive():
    """飞书引导式配置。"""
    console.print()
    console.print("[bold cyan]飞书（Lark）渠道配置[/bold cyan]")
    console.print()
    console.print("前置准备（在飞书开放平台 https://open.feishu.cn 创建企业自建应用）：")
    console.print("  1. [凭证与基础信息] → 获取 App ID 和 App Secret")
    console.print("  2. [事件与回调] → 选择 [长连接] 模式（无需公网 IP / Webhook）")
    console.print("  3. 订阅事件（[red]三项都要勾[/red]，否则启动会报 validation 错）：")
    console.print("       • im.message.receive_v1          — 接收消息（必选）")
    console.print("       • im.message.reaction.created_v1 — 消息被加表情（可选但建议）")
    console.print("       • card.action.trigger            — [red]交互卡片按钮回调[/red]（不勾则按钮点击无效、日志频繁报错）")
    console.print("  4. [权限管理] 开通：im:message、im:message.group_at_msg、im:chat（按需）")
    console.print("  5. lark-cli 与 lark-oapi 会在保存配置后自动安装")
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

    # 自动安装依赖 + 同步 lark-cli app（lark-oapi 包 / lark-cli 二进制 / app sync）
    from ethan.interface.lark_deps import ensure_lark_deps
    console.print()
    console.print("[bold]依赖就绪检查与安装[/bold]")
    status = ensure_lark_deps(
        values.get("app_id", ""),
        values.get("app_secret", ""),
        interactive=True,
        triggered_by="cli",
    )
    console.print()
    if status.lark_oapi_installed and status.lark_cli_installed and status.lark_cli_app_matches:
        console.print("[green]✓ 飞书依赖全部就绪[/green]")
    else:
        console.print("[yellow]⚠ 部分依赖未就绪，详见上方输出[/yellow]")
        if status.last_error:
            console.print(f"[dim]{status.last_error}[/dim]")

    console.print("[dim]重启 ethan serve 后生效（自动建立长连接）。[/dim]")
    console.print("  重启：ethan server restart")


def _save_lark(values: dict) -> None:
    from ethan.core.config import get_config, reload_config, save_config
    config = get_config()
    for k, v in values.items():
        if hasattr(config.lark, k):
            setattr(config.lark, k, v)
    save_config(config)
    reload_config()


# ── 微信 ──────────────────────────────────────────────────────

def _find_serve_pid() -> int | None:
    from ethan.interface.commands.update import _find_serve_pid as _find
    return _find()


def _restart_serve() -> None:
    from ethan.interface.commands.update import _restart_serve
    _restart_serve(None)


def _set_wechat_enabled(enabled: bool) -> None:
    from ethan.core.config import get_config, reload_config, save_config
    cfg = get_config()
    cfg.wechat.enabled = enabled
    save_config(cfg)
    reload_config()


def _add_wechat():
    """扫码登录微信（iLink Bot API），自动开启监听并重启 serve。"""
    import asyncio

    from ethan.interface.wechat_ilink import login_via_qrcode

    console.print()
    console.print("[bold cyan]微信（WeChat）渠道配置[/bold cyan]")
    console.print()
    console.print("[dim]正在请求二维码，请稍候...[/dim]")
    try:
        creds = asyncio.run(login_via_qrcode())
    except Exception as e:
        console.print(f"[red]登录失败：{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓ 登录成功！bot_id={creds.ilink_bot_id or '(未知)'}[/green]")

    # 自动开启 wechat.enabled
    _set_wechat_enabled(True)
    console.print("[dim]已自动设置 wechat.enabled: true[/dim]")

    # 重启 serve（如果正在运行）
    pid = _find_serve_pid()
    if pid:
        console.print(f"[dim]检测到 ethan serve 正在运行（pid={pid}），正在重启以加载微信渠道...[/dim]")
        try:
            _restart_serve()
            console.print("[green]✓ ethan serve 已重启，微信消息监听已开启。[/green]")
        except Exception as e:
            console.print(f"[yellow]自动重启失败（{e}），请手动运行：ethan server restart[/yellow]")
    else:
        console.print("[dim]ethan serve 未运行，启动后将自动监听微信消息：ethan serve[/dim]")


def _unset_wechat():
    """清除微信登录凭证并关闭监听。"""
    from ethan.interface.wechat_ilink import _CREDS_PATH, clear_credentials
    if _CREDS_PATH.exists():
        clear_credentials()
        console.print("[green]✓ 微信凭证已清除。[/green]")
    else:
        console.print("[yellow]当前没有保存的微信凭证。[/yellow]")

    _set_wechat_enabled(False)
    console.print("[dim]已设置 wechat.enabled: false[/dim]")

    pid = _find_serve_pid()
    if pid:
        console.print(f"[dim]正在重启 ethan serve（pid={pid}）以停止微信监听...[/dim]")
        try:
            _restart_serve()
            console.print("[green]✓ ethan serve 已重启。[/green]")
        except Exception as e:
            console.print(f"[yellow]自动重启失败（{e}），请手动运行：ethan server restart[/yellow]")


def _status_wechat():
    """显示当前微信登录状态。"""
    from ethan.core.config import get_config
    from ethan.interface.wechat_ilink import load_credentials

    creds = load_credentials()
    cfg = get_config()
    enabled = getattr(cfg.wechat, "enabled", False)

    if creds:
        console.print("[green]● 已登录[/green]")
        if creds.ilink_bot_id:
            console.print(f"  bot_id   : {creds.ilink_bot_id}")
        console.print(f"  base_url : {creds.base_url}")
        console.print(f"  监听状态 : {'已启用' if enabled else '未启用（wechat.enabled=false）'}")
        pid = _find_serve_pid()
        if pid:
            console.print(f"  serve    : 运行中（pid={pid}）")
        else:
            console.print("  serve    : [yellow]未运行[/yellow]")
    else:
        console.print("[yellow]● 未登录（运行 ethan channel add wechat 扫码）[/yellow]")


# 注：lark-cli 检测 / 安装 / app 同步逻辑已迁移到 ethan/interface/lark_deps.py，
# 三条入口（Web API / channel add|set / plugin add lark-channel）统一调用 ensure_lark_deps。
