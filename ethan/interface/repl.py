"""轻量 REPL 模式。

支持 Session 持久化、分层记忆、斜杠命令。
使用 prompt_toolkit 实现 Hermes 风格的状态栏 + 输入框。
"""
import asyncio
import os
import time
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.table import Table
from rich.text import Text

from ethan.core.agent import Agent
from ethan.core.config import get_config
from ethan.memory.consolidator import Consolidator
from ethan.memory.episodic import EpisodeStore
from ethan.memory.facts import FactStore
from ethan.memory.session import Session, SessionStore, _auto_title, _generate_smart_title
from ethan.memory.working import MemoryConfig, WorkingMemory
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


_SLASH_COMMANDS = [
    ("/sessions", "List recent sessions"),
    ("/resume", "Resume a session by ID"),
    ("/new", "Start new session"),
    ("/model", "Show or switch model"),
    ("/help", "Show available commands"),
]


class SlashCompleter(Completer):
    """Auto-complete slash commands with dynamic matching."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        for cmd, desc in _SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display_meta=desc,
                )


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


def _make_toolbar(model: str, tokens_in: int = 0, tokens_out: int = 0, tokens_cache: int = 0, session_id: str = "", activity: str = ""):
    """构建 prompt_toolkit bottom_toolbar。"""
    cwd = _shorten_path(os.getcwd())
    parts = []
    parts.append(("class:model", f" ⚡ {model}"))
    parts.append(("class:separator", " · "))
    parts.append(("class:path", cwd))
    if tokens_in or tokens_out:
        token_str = f"↑{tokens_in} ↓{tokens_out}"
        if tokens_cache:
            token_str += f" ⚡{tokens_cache}"
        parts.append(("class:separator", " · "))
        parts.append(("class:tokens", token_str))
    if activity:
        parts.append(("class:separator", " · "))
        parts.append(("class:tokens", activity))
    return parts


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


async def _background_consolidate(memory, consolidator, fact_store, session_id):
    try:
        if memory.needs_compression():
            batch = memory.get_compress_batch()
            summary = await consolidator.compress(batch, memory.warm_summary)
            memory.apply_summary(summary)
        if memory.needs_cold_extraction():
            facts_list, condensed = await consolidator.extract_cold(memory.warm_summary, memory.cold_facts)
            for fact in facts_list:
                fact_store.add(fact, confidence=0.8, source=session_id)
            memory.apply_cold_extraction(fact_store.build_context(), condensed)
    except Exception:
        pass


async def run_once(agent: Agent, prompt: str) -> None:
    """单轮对话：发送一句，流式打印回复，退出。"""
    from ethan.providers.base import ToolEvent
    messages = [Message(role="user", content=prompt)]

    spinner = Live(Spinner("dots", text="thinking...", style="dim"), console=console, transient=True)
    spinner.start()
    spinner_stopped = False
    render_live = Live(console=console, refresh_per_second=8, vertical_overflow="visible")
    render_started = False
    full = ""

    async for item in agent.stream_chat(messages):
        if isinstance(item, ToolEvent):
            if item.state == "start":
                if not spinner_stopped:
                    spinner.stop()
                    spinner_stopped = True
                if render_started:
                    render_live.stop()
                    render_started = False
                    console.print()
                args = f"({item.args_summary})" if item.args_summary else ""
                console.print(f"[dim]⚡ {item.tool_name}{args}[/dim]")
            continue

        if not spinner_stopped:
            spinner.stop()
            spinner_stopped = True
        if not render_started:
            render_live.start()
            render_started = True
        full += item
        render_live.update(RichMarkdown(full))

    if render_started:
        render_live.stop()
    if not spinner_stopped:
        spinner.stop()
    if full:
        console.print()


async def _handle_slash_command(cmd: str, store: SessionStore, session: Session, agent: Agent) -> Session | None:
    """处理斜杠命令。返回新 session 或 None 表示不切换。"""
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()

    if command in ("/sessions", "/ls"):
        sessions = await store.list_recent(10)
        if not sessions:
            console.print("[dim]No sessions yet.[/dim]")
        else:
            table = Table(show_lines=False, show_header=False, padding=(0, 1))
            table.add_column(style="cyan", max_width=20)
            table.add_column(max_width=40)
            table.add_column(style="dim")
            for s in sessions:
                marker = " ←" if s.id == session.id else ""
                t = datetime.fromtimestamp(s.updated_at).strftime("%m-%d %H:%M")
                table.add_row(s.id[-12:], s.title, t + marker)
            console.print(table)
        return None

    elif command == "/resume":
        if len(parts) < 2:
            console.print("[dim]Usage: /resume <session_id>[/dim]")
            return None
        target_id = parts[1].strip()
        sessions = await store.list_recent(50)
        match = None
        for s in sessions:
            if s.id == target_id or s.id.endswith(target_id):
                match = s
                break
        if not match:
            console.print(f"[red]Session not found: {target_id}[/red]")
            return None
        loaded = await store.load(match.id)
        if loaded:
            console.print(f"[green]Session restored: {loaded.title}[/green] [dim]({len(loaded.messages)} messages)[/dim]")
            return loaded
        return None

    elif command == "/new":
        new_session = await store.create(agent._provider.model, source="repl")
        console.print(f"[green]New session created[/green]")
        return new_session

    elif command in ("/model", "/m"):
        if len(parts) < 2:
            config = get_config()
            current = agent._provider.model
            models = config.model_ids()
            console.print(f"[dim]Current: [cyan]{current}[/cyan][/dim]")
            console.print(f"[dim]Available: {', '.join(models)}[/dim]")
            console.print(f"[dim]Switch: /model <id>[/dim]")
        else:
            # Return special signal — caller handles model switch
            from ethan.providers.manager import create_provider
            new_model = parts[1].strip()
            try:
                agent._provider = create_provider(new_model)
                console.print(f"[green]Switched to: {agent._provider.model}[/green]")
            except Exception as e:
                console.print(f"[red]Failed: {e}[/red]")
        return None

    elif command in ("/help", "/h"):
        console.print("""[dim]Commands:
  /sessions      List recent sessions
  /resume ID     Resume a session
  /new           Start new session
  /model [ID]    Show or switch model
  /help          Show this help[/dim]""")
        return None

    else:
        console.print(f"[dim]Unknown command: {command}. Type /help for available commands.[/dim]")
        return None


async def run_repl(agent: Agent, resume_id: str | None = None) -> None:
    """交互 REPL：Hermes 风格界面。"""
    config = get_config()
    model_id = agent._provider.model
    start_time = time.time()

    store = SessionStore()
    await store.init()

    # 恢复或新建 session（新建时先不写 DB，等到第一条消息再持久化）
    session: Session | None = None
    session_persisted = False
    if resume_id:
        if resume_id == "last":
            recent = await store.list_recent(1)
            if recent:
                session = await store.load(recent[0].id)
        else:
            session = await store.load(resume_id)
        if session:
            session_persisted = True
            console.print(f"[green]Session restored: {session.title}[/green] [dim]({len(session.messages)} messages)[/dim]")

    if not session:
        # 仅构造内存对象，不写 DB
        import time as _time
        _now = _time.time()
        from ethan.memory.session import _generate_id
        session = Session(id=_generate_id(), title="新对话", model=model_id, created_at=_now, updated_at=_now, source="repl")
        session_persisted = False

    _banner()

    # ── First-time onboarding ────────────────────────────────────
    from ethan.core.onboarding import is_first_time, ONBOARDING_MESSAGE
    if is_first_time():
        import asyncio
        console.print()
        console.print(Panel(ONBOARDING_MESSAGE, border_style="yellow", padding=(0, 2)))
        console.print()

        # Agent name
        raw_name = await asyncio.to_thread(input, "  Agent name (press Enter to keep 'Ethan'): ")
        agent_name = raw_name.strip() or "Ethan"

        # User info
        raw_info = await asyncio.to_thread(input, "  About you (e.g. 'I'm Alex, a software engineer'): ")
        user_info = raw_info.strip()

        # Persist agent name to config
        from ethan.core.config import save_config, reload_config
        _cfg = get_config()
        _cfg.defaults.agent_name = agent_name
        save_config(_cfg)
        reload_config()

        # Persist user info to FactStore
        if user_info:
            _fs = FactStore()
            _fs.add(user_info, confidence=1.0, source="onboarding", category="preference")

        console.print()
        console.print(f"[green]Great! I'll go by [bold]{agent_name}[/bold] from now on.[/green]")
        if user_info:
            console.print(f"[dim]I'll remember: {user_info}[/dim]")
        console.print()

    # 初始化分层记忆
    fact_store = FactStore()
    episode_store = EpisodeStore()
    memory = WorkingMemory(config=MemoryConfig(hot_size=10))
    memory.cold_facts = fact_store.build_context()
    consolidator = Consolidator(main_model=model_id)

    # 从 session 恢复历史到记忆系统，最多恢复 hot_size 轮到热区
    history = list(session.messages)
    pairs = []
    i = 0
    while i < len(history) - 1:
        if history[i].role == "user" and history[i + 1].role == "assistant":
            pairs.append((history[i], history[i + 1]))
            i += 2
        else:
            i += 1
    for user_msg, asst_msg in pairs[-memory.config.hot_size:]:
        memory.hot.append(user_msg)
        memory.hot.append(asst_msg)

    approx_tokens = sum(len(m.content) for m in history)

    # Token tracking
    total_tokens_in = 0
    total_tokens_out = 0
    total_tokens_cache = 0

    # prompt_toolkit session with slash command completion
    pt_session = PromptSession(style=_PT_STYLE, completer=SlashCompleter(), complete_while_typing=True)
    _exit_press_time = 0.0

    while True:
        toolbar = _make_toolbar(model_id, total_tokens_in, total_tokens_out, total_tokens_cache, session.id)
        try:
            console.print()
            console.rule(style="dim")
            user_input = (await pt_session.prompt_async(
                "› ",
                bottom_toolbar=toolbar,
            )).strip()
            _exit_press_time = 0.0  # reset on successful input
        except (EOFError, KeyboardInterrupt):
            now = time.time()
            if now - _exit_press_time < 2.0:
                elapsed = _format_duration(now - start_time)
                console.print(f"\n[dim]Bye · {elapsed}[/dim]")
                break
            else:
                _exit_press_time = now
                console.print("\n[dim]Press Ctrl+C again to exit[/dim]")
                continue

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            elapsed = _format_duration(time.time() - start_time)
            console.print(f"[dim]Bye · {elapsed}[/dim]")
            break

        # 斜杠命令
        if user_input.startswith("/"):
            result = await _handle_slash_command(user_input, store, session, agent)
            if result is not None:
                session = result
                session_persisted = True  # /resume 和 /new 返回的都是已持久化的 session
                history = list(session.messages)
                approx_tokens = sum(len(m.content) for m in history)
                model_id = session.model
                memory = WorkingMemory(config=MemoryConfig(hot_size=10))
                memory.cold_facts = fact_store.build_context()
                # 恢复历史到热区
                pairs = []
                j = 0
                while j < len(history) - 1:
                    if history[j].role == "user" and history[j + 1].role == "assistant":
                        pairs.append((history[j], history[j + 1]))
                        j += 2
                    else:
                        j += 1
                for u, a in pairs[-memory.config.hot_size:]:
                    memory.hot.append(u)
                    memory.hot.append(a)
            continue

        msg = Message(role="user", content=user_input)
        history.append(msg)

        # 第一条消息时才真正持久化 session
        if not session_persisted:
            await store._db.execute(
                "INSERT INTO sessions (id, title, model, created_at, updated_at, source) VALUES (?, ?, ?, ?, ?, ?)",
                (session.id, session.title, session.model, session.created_at, session.updated_at, "repl"),
            )
            await store._db.commit()
            session_persisted = True

        await store.save_message(session.id, msg)
        approx_tokens += len(user_input)

        # 第一条用户消息时用 _auto_title 占位；第 3 轮后改用智能标题
        user_msgs = [m for m in history if m.role == "user"]
        if len(user_msgs) == 1:
            title = _auto_title(history)
            await store.update_title(session.id, title)
            session.title = title
        elif len(user_msgs) == 3:
            import asyncio
            async def _regen_title():
                t = await _generate_smart_title(history)
                await store.update_title(session.id, t)
                session.title = t
            asyncio.create_task(_regen_title())

        full = ""
        first_chunk = True
        first_item = True  # for TTFT: fire on any first item (tool or text)
        current_activity = ""
        console.print()
        live = Live(Spinner("dots", text="thinking...", style="dim"), console=console, transient=True)
        live.start()
        send_time = time.time()
        ttft: float | None = None
        # Snapshot before this turn so we can compute per-turn delta
        prev_input = agent.usage.input_tokens
        prev_output = agent.usage.output_tokens
        prev_cache = agent.usage.cache_tokens

        context = memory.build_context()
        context.append(msg)

        try:
            from ethan.providers.base import ToolEvent
            render_live = Live(console=console, refresh_per_second=8, vertical_overflow="visible")
            async for item in agent.stream_chat(context):
                if isinstance(item, ToolEvent):
                    if first_item:
                        ttft = time.time() - send_time
                        first_item = False
                    if item.state == "start":
                        activity_text = f"⚡ {item.tool_name}"
                        if item.args_summary:
                            activity_text += f"({item.args_summary})"
                        current_activity = activity_text
                        if first_chunk:
                            live.stop()
                            first_chunk = False
                        if render_live.is_started:
                            render_live.stop()
                        console.print(f"[dim]{activity_text}[/dim]")
                    elif item.state in ("done", "error"):
                        current_activity = ""
                    continue

                # Text chunk
                if first_item:
                    ttft = time.time() - send_time
                    first_item = False
                if first_chunk:
                    if ttft is None:
                        ttft = time.time() - send_time
                    live.stop()
                    first_chunk = False
                if not render_live.is_started:
                    render_live.start()
                full += item
                render_live.update(RichMarkdown(full))

            if render_live.is_started:
                render_live.stop()
            console.print()
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as e:
            if first_chunk:
                live.stop()
            console.print(f"\n[red]Error: {e}[/red]\n")
        finally:
            if first_chunk:
                live.stop()

        if full:
            usage_dict = {
                "input": agent.usage.input_tokens,
                "output": agent.usage.output_tokens,
                "cache": agent.usage.cache_tokens,
            }
            resp = Message(role="assistant", content=full, usage=usage_dict)
            history.append(resp)
            await store.save_message(session.id, resp)
            await store.touch(session.id)

            if agent._skills and agent.last_matched_skills:
                import asyncio as _asyncio
                for _name in agent.last_matched_skills:
                    _asyncio.create_task(_asyncio.to_thread(agent._skills.record_hit, _name))

            # Per-turn delta (not cumulative)
            turn_in = agent.usage.input_tokens - prev_input
            turn_out = agent.usage.output_tokens - prev_output
            turn_cache = agent.usage.cache_tokens - prev_cache

            # Print per-turn stats in dim color
            stats_parts = [f"↑{turn_in} ↓{turn_out}"]
            if turn_cache:
                stats_parts.append(f"⚡{turn_cache}")
            if ttft is not None:
                stats_parts.append(f"TTFT {ttft*1000:.0f}ms" if ttft < 1 else f"TTFT {ttft:.1f}s")
            console.print(f"[dim]  {' · '.join(stats_parts)}[/dim]")

            memory.add_turn(msg, resp)

            if memory.needs_compression() or memory.needs_cold_extraction():
                asyncio.create_task(_background_consolidate(memory, consolidator, fact_store, session.id))
        else:
            history.pop()

    # Save episode summary on exit (if enough turns)
    user_turns = sum(1 for m in history if m.role == "user")
    if user_turns >= 2 and session.id:
        try:
            summary = " ".join(
                m.content[:50] for m in history if m.role == "user" and m.content
            )[:200]
            keywords = list(set(
                w for m in history if m.role == "user" and m.content
                for w in m.content.split()[:5]
            ))[:10]
            episode_store.add(
                session_id=session.id,
                summary=summary,
                model=model_id,
                turn_count=user_turns,
                keywords=keywords,
            )
        except Exception:
            pass

    # 清理历史空 session（包括本次如果没有发任何消息的情况）
    try:
        cleaned = await store.cleanup_empty()
        if cleaned:
            pass  # 静默清理，不打印
    except Exception:
        pass

    await store.close()
