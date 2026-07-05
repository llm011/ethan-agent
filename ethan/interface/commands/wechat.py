"""ethan wechat — 微信 iLink 渠道管理命令。

  ethan wechat login   扫码登录微信，凭证保存到 ~/.ethan/memory/wechat_credentials.json
  ethan wechat logout  清除登录凭证
  ethan wechat status  显示当前登录状态
"""
import asyncio
import os
import signal

import typer
from rich.console import Console

app = typer.Typer(help="管理微信 iLink 渠道", no_args_is_help=True)
console = Console()


def _set_wechat_enabled(enabled: bool) -> None:
    from ethan.core.config import get_config, save_config, reload_config
    cfg = get_config()
    cfg.wechat.enabled = enabled
    save_config(cfg)
    reload_config()


def _find_serve_pid() -> int | None:
    from ethan.interface.commands.update import _find_serve_pid as _find
    return _find()


def _restart_serve() -> None:
    from ethan.interface.commands.update import _restart_serve
    _restart_serve(None)


@app.command("login")
def wechat_login() -> None:
    """扫码登录微信（iLink Bot API），自动开启监听并重启 serve。"""
    from ethan.interface.wechat_ilink import login_via_qrcode

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
            console.print(f"[yellow]自动重启失败（{e}），请手动运行：ethan serve restart[/yellow]")
    else:
        console.print("[dim]ethan serve 未运行，启动后将自动监听微信消息：ethan serve[/dim]")


@app.command("logout")
def wechat_logout() -> None:
    """清除微信登录凭证并关闭监听。"""
    from ethan.interface.wechat_ilink import clear_credentials, _CREDS_PATH
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
            console.print(f"[yellow]自动重启失败（{e}），请手动运行：ethan serve restart[/yellow]")


@app.command("status")
def wechat_status() -> None:
    """显示当前微信登录状态。"""
    from ethan.interface.wechat_ilink import load_credentials
    from ethan.core.config import get_config

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
        console.print("[yellow]● 未登录（运行 ethan wechat login 扫码）[/yellow]")
