"""Single-turn streaming: run_once."""
from rich.live import Live
from rich.markdown import Markdown as RichMarkdown
from rich.spinner import Spinner

from ethan.core.agent import Agent
from ethan.providers.base import Message

from .repl_ui import console


async def run_once(agent: Agent, prompt: str) -> None:
    """单轮对话：发送一句，流式打印回复，退出。同时持久化到 session 列表。"""
    from ethan.core.config import get_config
    from ethan.core.paths import user_sessions_db_path
    from ethan.memory.session import SessionStore, _generate_id
    from ethan.providers.base import ThinkingEvent, ToolEvent

    # 创建 session
    session_id = _generate_id()
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    model_id = agent._provider.model or get_config().defaults.model
    await store.create_with_id(session_id, model_id, source="cli")

    # 直接用命令行参数作初始标题（_auto_title 在后面 decide_title 时可能被智能标题覆盖）
    init_title = prompt.strip().replace("\n", " ")[:40]
    if init_title:
        await store.update_title(session_id, init_title)

    # 保存用户消息
    user_msg = Message(role="user", content=prompt)
    await store.save_message(session_id, user_msg)

    messages = [user_msg]

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

    # 保存 assistant 回复并更新 session
    if full:
        usage_dict = {"input": agent.usage.input_tokens, "output": agent.usage.output_tokens, "cache": agent.usage.cache_tokens}
        await store.save_message(session_id, Message(role="assistant", content=full, usage=usage_dict))
        await store.touch(session_id)

    # 生成标题（CLI 模式下同步执行，因为 asyncio.run 结束后 create_task 没机会跑）
    try:
        from ethan.memory.session import decide_title
        session_obj = await store.load(session_id)
        if session_obj:
            title = await decide_title(session_obj.messages, session_obj.title)
            if title and title != session_obj.title:
                await store.update_title(session_id, title)
    except Exception:
        pass  # 标题生成失败不影响主流程

    await store.close()

    # 打印 session_id 供用户后续引用
    console.print()
    console.print(f"[dim]session: {session_id}[/dim]")
