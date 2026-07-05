"""REPL UI utilities: console singleton, styles, formatters, display helpers."""
import os

from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel

from ethan.core.config import get_config
from ethan.providers.base import Message

console = Console()

_PT_STYLE = Style.from_dict({
    "bottom-toolbar": "bg:#1a1a2e #e0e0e0",
    "bottom-toolbar.text": "#e0e0e0",
    "model": "#e6b800 bold",
    "separator": "#555555",
    "path": "#888888",
    "session": "#888888",
    "tokens": "#888888",
})


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s}s"
    h, m = divmod(m, 60)
    return f"{h}h{m}m"


def _fmt_tokens(n: int) -> str:
    """紧凑显示 token 数：890379 → '890k'，1500000 → '1.5M'。"""
    n = int(n or 0)
    if n >= 1_000_000:
        v = (n // 10000) / 100  # floor 到百分位，避免 999999 → 1.0M
        return f"{v:.1f}M".replace(".0M", "M")
    if n >= 10_000:
        return f"{n // 1000}k"
    if n >= 1000:
        return f"{(n // 100) / 10:.1f}k"
    return str(n)


def _shorten_path(path: str, max_len: int = 30) -> str:
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) <= max_len:
        return path
    parts = path.split(os.sep)
    if len(parts) <= 2:
        return path
    return parts[0] + os.sep + "…" + os.sep + parts[-1]


def _make_toolbar(model: str, tokens_in: int = 0, tokens_out: int = 0, tokens_cache: int = 0, session_id: str = "", activity: str = "", user_id: str = ""):
    """构建 prompt_toolkit bottom_toolbar。token 总消耗紧跟 model，保证醒目。"""
    cwd = _shorten_path(os.getcwd())
    parts = []
    parts.append(("class:model", f" ⚡ {model}"))
    # token 紧跟 model —— 这是用户最关心的会话级总消耗
    if tokens_in or tokens_out:
        token_str = f"↑{_fmt_tokens(tokens_in)} ↓{_fmt_tokens(tokens_out)}"
        if tokens_cache:
            token_str += f" ⚡{_fmt_tokens(tokens_cache)}"
        parts.append(("class:separator", " · "))
        parts.append(("class:tokens", token_str))
    if user_id:
        parts.append(("class:separator", " · "))
        parts.append(("class:tokens", f"user: {user_id}"))
    parts.append(("class:separator", " · "))
    parts.append(("class:path", cwd))
    if activity:
        parts.append(("class:separator", " · "))
        parts.append(("class:tokens", activity))
    return parts


def _print_history(messages: list[Message], limit: int = 30) -> None:
    """渲染最近的历史消息（最新 limit 条）。"""
    if not messages:
        return

    # 提取最新的 limit 条消息
    display_messages = messages[-limit:]

    # 打印一条提示
    from ethan.core.config import get_config
    config = get_config()
    agent_name = config.defaults.agent_name

    console.print(f"[dim]Showing last {len(display_messages)} messages of history...[/dim]\n")

    for msg in display_messages:
        if msg.role == "user":
            console.print(f"[bold cyan]› {msg.content}[/bold cyan]")
        elif msg.role == "assistant":
            # 如果是工具执行的提示，也以暗色打印
            if msg.tool_steps:
                for step in msg.tool_steps:
                    # step 结构类似：{"tool_name": "...", "args_summary": "...", "state": "done"}
                    name = step.get("tool_name", "")
                    args = step.get("args_summary", "")
                    args_str = f"({args})" if args else ""
                    console.print(f"[dim]⚡ {name}{args_str}[/dim]")
            if msg.content:
                console.print(RichMarkdown(msg.content))
            console.print()


def _banner():
    """启动 banner。"""
    from ethan import __version__
    config = get_config()
    name = config.defaults.agent_name
    console.print()
    console.print(Panel(
        f"[bold cyan]{name} Agent[/bold cyan] [dim]v{__version__}[/dim]\n"
        f"[dim]Type exit to quit · Ctrl+C to interrupt · /help for commands[/dim]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print()
