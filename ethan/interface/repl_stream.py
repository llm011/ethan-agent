"""Single-turn streaming: run_once."""
from rich.live import Live
from rich.markdown import Markdown as RichMarkdown
from rich.spinner import Spinner

from ethan.core.agent import Agent
from ethan.providers.base import Message

from .repl_ui import console


async def run_once(agent: Agent, prompt: str) -> None:
    """单轮对话：发送一句，流式打印回复，退出。"""
    from ethan.providers.base import ThinkingEvent, ToolEvent
    messages = [Message(role="user", content=prompt)]

    spinner = Live(Spinner("dots", text="thinking...", style="dim"), console=console, transient=True)
    spinner.start()
    spinner_stopped = False
    render_live = Live(console=console, refresh_per_second=8, transient=True)
    render_started = False
    full = ""
    after_tool = False  # 上一条输出是工具调用行，后续文字前需加空行

    async for item in agent.stream_chat(messages):
        if isinstance(item, ThinkingEvent):
            continue  # 思考内容不打印（spinner 已显示 thinking...）
        if isinstance(item, ToolEvent):
            if item.state == "start":
                if not spinner_stopped:
                    spinner.stop()
                    spinner_stopped = True
                if render_started:
                    render_live.stop()
                    if full.strip():
                        console.print(RichMarkdown(full))
                    full = ""
                    render_started = False
                    console.print()
                args = f"({item.args_summary})" if item.args_summary else ""
                console.print(f"[dim]⚡ {item.tool_name}{args}[/dim]")
                after_tool = True
            elif item.state in ("done", "error"):
                if item.sub_steps:
                    # 委派类工具（如 delegate_coding）的子步骤摘要
                    ok = sum(1 for s in item.sub_steps if s.get("state") == "done")
                    console.print(f"[dim]   ↳ {len(item.sub_steps)} 步工具调用（{ok} 成功）[/dim]")
                # A2UI 卡片：ui_card 工具产出的 envelope，文本降级渲染
                if getattr(item, "ui", None):
                    try:
                        from ethan.interface.a2ui_text import render_a2ui
                        card = render_a2ui(item.ui)
                        if card is not None:
                            console.print(card)
                            after_tool = True
                            continue
                    except Exception:
                        pass
                if item.result_preview:
                    prefix = "  → " if item.state == "done" else "  ✗ "
                    console.print(f"[dim]{prefix}{item.result_preview}[/dim]", soft_wrap=True)
            continue

        if not spinner_stopped:
            spinner.stop()
            spinner_stopped = True
        full += item
        if not render_started:
            if after_tool:
                console.print()
                after_tool = False
            render_live.start()
            render_started = True
        render_live.update(RichMarkdown(full))

    if render_started:
        render_live.stop()
        if full.strip():
            console.print(RichMarkdown(full))
    if not spinner_stopped:
        spinner.stop()
    if full:
        console.print()
