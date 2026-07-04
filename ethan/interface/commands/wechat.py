"""ethan wechat — 微信 iLink 渠道管理命令。

  ethan wechat login   扫码登录微信，凭证保存到 ~/.ethan/memory/wechat_credentials.json
  ethan wechat logout  清除登录凭证
  ethan wechat status  显示当前登录状态
"""
import asyncio

import typer
from rich.console import Console

app = typer.Typer(help="管理微信 iLink 渠道", no_args_is_help=True)
console = Console()


@app.command("login")
def wechat_login() -> None:
    """扫码登录微信（iLink Bot API）。"""
    from ethan.interface.wechat_ilink import login_via_qrcode

    console.print("[dim]正在请求二维码，请稍候...[/dim]")
    try:
        creds = asyncio.run(login_via_qrcode())
        console.print(f"[green]✓ 登录成功！bot_id={creds.ilink_bot_id or '(未知)'}[/green]")
        console.print("[dim]提示：在 config.yaml 中设置 wechat.enabled: true，重启 ethan serve 即可自动收发微信消息。[/dim]")
    except Exception as e:
        console.print(f"[red]登录失败：{e}[/red]")
        raise typer.Exit(1)


@app.command("logout")
def wechat_logout() -> None:
    """清除微信登录凭证。"""
    from ethan.interface.wechat_ilink import clear_credentials, _CREDS_PATH
    if _CREDS_PATH.exists():
        clear_credentials()
        console.print("[green]✓ 微信凭证已清除。[/green]")
    else:
        console.print("[yellow]当前没有保存的微信凭证。[/yellow]")


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
    else:
        console.print("[yellow]● 未登录（运行 ethan wechat login 扫码）[/yellow]")
