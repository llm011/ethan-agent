"""轻量 REPL 模式。

支持 Session 持久化、分层记忆、斜杠命令。
使用 prompt_toolkit 实现 Hermes 风格的状态栏 + 输入框。
"""
import asyncio
import os
import signal
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


class ProfileSwitchException(Exception):
    """Raised to trigger a profile switch and agent rebuild."""
    def __init__(self, new_uid: str):
        super().__init__(f"Switch to user {new_uid}")
        self.new_uid = new_uid

_SLASH_COMMANDS = [
    ("/sessions", "List recent sessions"),
    ("/resume", "Resume a session by ID"),
    ("/new", "Start new session"),
    ("/model", "Show or switch model"),
    ("/profile", "Show or switch user profile"),
    ("/config", "Edit settings interactively"),
    ("/token", "Show or rotate Web login token"),
    ("/skills", "List installed skills"),
    ("/update", "Update Ethan Agent"),
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


async def _background_consolidate(memory, consolidator, fact_store, session_id):
    try:
        if memory.needs_compression():
            batch = memory.get_compress_batch()
            summary = await consolidator.compress(batch, memory.warm_summary)
            memory.apply_summary(summary)
        if memory.needs_cold_extraction():
            result = await consolidator.extract_cold(memory.warm_summary, memory.cold_facts)
            for fact in result["key_facts"]:
                fact_store.add(fact, confidence=0.8, source=session_id)
            from ethan.core.profile import apply_extraction
            apply_extraction(result)
            memory.apply_cold_extraction(fact_store.build_context(), result["condensed"])
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
    direct_mode = False  # 长文本超过阈值后直接增量打印，不再用 Live 重渲染
    full = ""
    after_tool = False  # 上一条输出是工具调用行，后续文字前需加空行

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
                after_tool = True
            elif item.state in ("done", "error"):
                if item.sub_steps:
                    # 委派类工具（如 delegate_coding）的子步骤摘要
                    ok = sum(1 for s in item.sub_steps if s.get("state") == "done")
                    console.print(f"[dim]   ↳ {len(item.sub_steps)} 步工具调用（{ok} 成功）[/dim]")
                if item.result_preview:
                    prefix = "  → " if item.state == "done" else "  ✗ "
                    console.print(f"[dim]{prefix}{item.result_preview}[/dim]", soft_wrap=True)
            continue

        if not spinner_stopped:
            spinner.stop()
            spinner_stopped = True
        full += item
        if direct_mode:
            console.print(item, end="", highlight=False, soft_wrap=True)
            continue
        if not render_started:
            if after_tool:
                console.print()
            render_live.start()
            render_started = True
        render_live.update(RichMarkdown(full))
        # 超过阈值：提交 Live，切到直接打印（防 Rich Live 超长内容重复刷屏）
        if full.count("\n") >= 12:
            render_live.stop()
            render_started = False
            direct_mode = True

    if render_started:
        render_live.stop()
    if direct_mode:
        console.print()
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
            models_str = ", ".join(f"[{i}] {m.id}" for i, m in enumerate(config.models, start=1))
            console.print(f"[dim]Current: [cyan]{current}[/cyan][/dim]")
            console.print(f"[dim]Available: {models_str}[/dim]")
            console.print(f"[dim]Switch: /model <id_or_index>[/dim]")
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

    elif command in ("/profile", "/p"):
        from ethan.core.users import get_user_store
        user_store = get_user_store()
        all_uids = user_store.all_user_ids()
        current_uid = getattr(agent, "_user_id", "") or user_store.get_admin_user_id()

        if len(parts) < 2:
            profiles_str = ", ".join(
                f"[cyan]{uid}[/cyan]" + (" (current)" if uid == current_uid else "")
                for uid in all_uids
            )
            console.print(f"[dim]Available profiles: {profiles_str}[/dim]")
            console.print(f"[dim]Switch: /profile <profile_id>[/dim]")
        else:
            target_uid = parts[1].strip()
            if target_uid not in all_uids:
                console.print(f"[red]Profile not found: {target_uid}[/red]")
                profiles_str = ", ".join(all_uids)
                console.print(f"[dim]Available profiles: {profiles_str}[/dim]")
            elif target_uid == current_uid:
                console.print(f"[yellow]Already using profile: {target_uid}[/yellow]")
            else:
                console.print(f"[green]Switching profile to: {target_uid}...[/green]")
                raise ProfileSwitchException(target_uid)
        return None

    elif command in ("/help", "/h"):
        console.print("""[dim]Commands:
  /sessions      List recent sessions
  /resume ID     Resume a session
  /new           Start new session
  /model [ID]    Show or switch model
  /profile [ID]  Show or switch user profile
  /config        Edit settings interactively
  /token [rotate]  Show or rotate Web login token
  /skills        List installed skills
  /update        Update Ethan Agent
  /help          Show this help[/dim]""")
        return None

    elif command == "/config":
        from ethan.core.config import save_config, reload_config
        from ethan.interface.config_editor import run_config_editor
        config = get_config()
        old_model = config.defaults.model
        try:
            changed = await run_config_editor(config)
        except Exception as e:
            console.print(f"[red]配置编辑器异常: {e}[/red]")
            return None
        if changed:
            save_config(config)
            reload_config()
            config = get_config()
            # 模型改动 → 实时切换 provider
            if config.defaults.model != old_model:
                try:
                    from ethan.providers.manager import create_provider
                    agent._provider = create_provider(config.defaults.model)
                    console.print(f"[green]✓ 模型已切换: {agent._provider.model}[/green]")
                except Exception as e:
                    console.print(f"[yellow]模型切换失败（已保存，重启生效）: {e}[/yellow]")
            console.print("[green]✓ 配置已保存[/green]")
        else:
            console.print("[dim]未做改动[/dim]")
        return None

    elif command == "/token":
        from ethan.core.config import save_config
        config = get_config()
        arg = parts[1].strip().lower() if len(parts) > 1 else ""
        # 无参数或 show/get/view → 只显示；任何其它参数 → 轮转
        if arg in ("show", "get", "view", "?", "help"):
            arg = ""
        if arg:
            import secrets
            config.network.auth_token = secrets.token_hex(16)
            save_config(config)
            console.print("[green]✓ Web Token 已重新生成（旧 Token 失效）[/green]")
        token = config.network.auth_token
        if not token:
            console.print("[yellow]当前未配置 Web Token。[/yellow]")
        else:
            console.print(f"Web 登录 Token: [cyan]{token}[/cyan]")
        if not arg:
            console.print("[dim]轮换: /token rotate[/dim]")
        return None

    elif command == "/skills":
        skills = agent._skills.all() if agent._skills else []
        if not skills:
            console.print("[dim]No skills installed.[/dim]")
            return None
        table = Table(title="Skills", show_header=True, header_style="dim", padding=(0, 1))
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Description")
        table.add_column("Trigger", style="dim")
        for s in skills:
            trigger = ", ".join(s.trigger) if s.trigger else "—"
            table.add_row(s.name, s.description or "", trigger)
        console.print(table)
        console.print("[dim]管理 Skills: ethan skill list/create/delete[/dim]")
        return None

    elif command == "/update":
        import sys
        import subprocess
        console.print("[dim]Starting update process...[/dim]")
        # Execute the update command directly
        subprocess.run([sys.executable, "-m", "ethan.interface.cli", "update"])
        console.print("[yellow]Update check finished. If an update was installed, you may need to restart the REPL.[/yellow]")
        return None

    else:
        console.print(f"[dim]Unknown command: {command}. Type /help for available commands.[/dim]")
        return None


async def run_repl(agent: Agent, resume_id: str | None = None) -> None:
    """交互 REPL：Hermes 风格界面。"""
    config = get_config()
    model_id = agent._provider.model
    start_time = time.time()
    uid = getattr(agent, "_user_id", "") or ""

    # 注入 TUI 授权 provider（敏感操作时 y/N 确认）
    from ethan.core.consent import TuiConsentProvider, set_consent_provider
    set_consent_provider(TuiConsentProvider(console=console))

    from ethan.core.paths import user_sessions_db_path
    store = SessionStore(db_path=user_sessions_db_path())
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
            _print_history(session.messages, limit=30)

    if not session:
        # 仅构造内存对象，不写 DB
        import time as _time
        _now = _time.time()
        from ethan.memory.session import _generate_id
        session = Session(id=_generate_id(), title="新对话", model=model_id, created_at=_now, updated_at=_now, source="repl")
        session_persisted = False

    _banner()

    # ── Provider setup (runs any time no API key is configured) ──
    from ethan.core.onboarding import is_first_time, needs_provider_setup, ONBOARDING_MESSAGE
    if needs_provider_setup():
        console.print()
        console.print(Panel(
            "[bold yellow]No API key configured.[/bold yellow]\n\n"
            "Choose a provider:\n"
            "  [cyan]1[/cyan]  Anthropic (Claude)       — api.anthropic.com\n"
            "  [cyan]2[/cyan]  OpenAI-compatible        — OpenAI / Gemini / OpenRouter / Ollama\n\n"
            "You can also run [dim]ethan provider set[/dim] later to change this.",
            border_style="yellow", padding=(0, 2)
        ))
        console.print()

        from ethan.core.config import save_config, reload_config as _reload, CONFIG_DIR, ProviderConfig
        _cfg = get_config()

        raw_choice = await asyncio.to_thread(input, "  Provider [1/2] (default: 1): ")
        choice = raw_choice.strip() or "1"

        if choice == "2":
            raw_key = await asyncio.to_thread(input, "  API Key: ")
            api_key = raw_key.strip()
            raw_url = await asyncio.to_thread(input, "  Base URL (e.g. https://generativelanguage.googleapis.com/v1beta/openai): ")
            base_url = raw_url.strip() or None
            _cfg.providers.setdefault("openai_compat", ProviderConfig())
            _cfg.providers["openai_compat"].api_key = api_key
            if base_url:
                _cfg.providers["openai_compat"].base_url = base_url
            # default model
            raw_model = await asyncio.to_thread(input, "  Default model ID (e.g. gemini-2.5-flash): ")
            default_model = raw_model.strip()
            if default_model:
                _cfg.defaults.model = default_model
        else:
            raw_key = await asyncio.to_thread(input, "  Anthropic API Key (sk-ant-...): ")
            api_key = raw_key.strip()
            _cfg.providers.setdefault("anthropic", ProviderConfig())
            _cfg.providers["anthropic"].api_key = api_key
            _cfg.defaults.model = "claude-sonnet-4.6"

        save_config(_cfg)
        _reload()
        config = get_config()
        model_id = config.defaults.model
        current_uid = getattr(agent, "_user_id", "") or ""
        # rebuild agent with new config and same profile
        from ethan.interface.cli import _build_agent
        agent = _build_agent(model_id, user_id=current_uid)
        console.print()
        console.print(f"[green]Provider configured. Using model: [bold]{model_id}[/bold][/green]")
        console.print()

    # ── First-time onboarding (name + user info) ─────────────────
    if is_first_time():
        console.print()
        console.print(Panel(ONBOARDING_MESSAGE, border_style="dim", padding=(0, 2)))
        console.print()

        # Agent name
        raw_name = await asyncio.to_thread(input, "  Agent name (press Enter to keep 'Ethan'): ")
        agent_name = raw_name.strip() or "Ethan"

        # User info
        raw_info = await asyncio.to_thread(input, "  About you (e.g. 'I'm Alex, a software engineer'): ")
        user_info = raw_info.strip()

        # Persist agent name to config
        from ethan.core.config import save_config, reload_config, CONFIG_DIR
        _cfg = get_config()
        _cfg.defaults.agent_name = agent_name
        save_config(_cfg)
        reload_config()

        # Patch agent name in identity.md if user chose a non-default name
        if agent_name != "Ethan":
            identity_path = CONFIG_DIR / "system" / "identity.md"
            if identity_path.exists():
                _id_content = identity_path.read_text(encoding="utf-8")
                identity_path.write_text(_id_content.replace("Ethan", agent_name), encoding="utf-8")

        # Persist user info to FactStore
        if user_info:
            from ethan.core.paths import user_facts_path
            _fs = FactStore(path=user_facts_path())
            _fs.add(user_info, confidence=1.0, source="onboarding", category="preference")

        console.print()
        console.print(f"[green]Great! I'll go by [bold]{agent_name}[/bold] from now on.[/green]")
        if user_info:
            console.print(f"[dim]I'll remember: {user_info}[/dim]")
        console.print()

    # 初始化分层记忆（per-user）
    from ethan.core.paths import user_facts_path, user_episodes_path
    fact_store = FactStore(path=user_facts_path())
    episode_store = EpisodeStore(path=user_episodes_path())
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
        current_uid = getattr(agent, "_user_id", "") or ""
        toolbar = _make_toolbar(agent._provider.model, total_tokens_in, total_tokens_out, total_tokens_cache, session.id, user_id=current_uid)
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
                _print_history(session.messages, limit=30)
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

        # 第一条用户消息时用 _auto_title 占位；第 2 轮后改用智能标题
        user_msgs = [m for m in history if m.role == "user"]
        if len(user_msgs) == 1:
            title = _auto_title(history)
            await store.update_title(session.id, title)
            session.title = title
        elif len(user_msgs) == 2:
            async def _regen_title():
                t = await _generate_smart_title(history)
                await store.update_title(session.id, t)
                session.title = t
            asyncio.create_task(_regen_title())

        full = ""
        thought = ""
        first_chunk = True
        first_item = True  # for TTFT: fire on any first item (tool or text)
        last_was_tool = False  # 上一条输出是工具调用行，后续文字前加空行
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

        # Inner coroutine — captured by closure, can be awaited as a Task
        async def _consume_stream():
            nonlocal full, thought, first_chunk, first_item, ttft, last_was_tool
            from ethan.providers.base import ToolEvent
            render_live = Live(console=console, refresh_per_second=8, vertical_overflow="visible")
            direct_mode = False  # 长文本超过阈值后直接增量打印，不再用 Live 重渲染（防 Rich 溢出重复刷屏）
            try:
                async for item in agent.stream_chat(context):
                    if isinstance(item, ToolEvent):
                        if first_item:
                            ttft = time.time() - send_time
                            first_item = False
                        if item.state == "start":
                            if render_live.is_started:
                                # Erase the thinking text from screen before stopping the live render
                                render_live.update(Text(""))
                                render_live.stop()
                            if full:
                                thought += ("\n\n" if thought else "") + full
                                full = ""
                            activity_text = f"⚡ {item.tool_name}"
                            if item.args_summary:
                                activity_text += f"({item.args_summary})"
                            if first_chunk:
                                live.stop()
                                first_chunk = False
                            console.print(f"[dim]{activity_text}[/dim]")
                            last_was_tool = True
                        elif item.state in ("done", "error"):
                            if item.sub_steps:
                                ok = sum(1 for s in item.sub_steps if s.get("state") == "done")
                                console.print(f"[dim]   ↳ {len(item.sub_steps)} 步工具调用（{ok} 成功）[/dim]")
                            # 展示结果预览（shell/file_read 等的输出摘要），让用户看到工具做了什么
                            if item.result_preview:
                                prefix = "  → " if item.state == "done" else "  ✗ "
                                console.print(f"[dim]{prefix}{item.result_preview}[/dim]", soft_wrap=True)
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
                    full += item
                    if direct_mode:
                        # 长文本：直接增量打印，不再 Live 重渲染
                        console.print(item, end="", highlight=False, soft_wrap=True)
                    else:
                        if not render_live.is_started:
                            if last_was_tool:
                                console.print()
                                last_was_tool = False
                            render_live.start()
                        render_live.update(RichMarkdown(full))
                        # 超过阈值：Live 内容提交（transient=False 会保留），切到直接打印
                        # 避免 Rich Live 无法原地更新超长内容导致整块重复打印
                        if full.count("\n") >= 12:
                            render_live.stop()
                            direct_mode = True
            finally:
                if render_live.is_started:
                    render_live.stop()
                if direct_mode:
                    console.print()  # 直接打印模式结尾补换行
                if first_chunk:
                    live.stop()

        # Run stream as a cancellable asyncio Task
        _stream_task: asyncio.Task | None = None
        loop = asyncio.get_running_loop()

        def _sigint_during_stream():
            if _stream_task is not None and not _stream_task.done():
                _stream_task.cancel()

        loop.add_signal_handler(signal.SIGINT, _sigint_during_stream)
        try:
            _stream_task = asyncio.ensure_future(_consume_stream())
            await _stream_task
            console.print()
        except asyncio.CancelledError:
            full = ""   # discard partial; history.pop() in the else branch will clean up
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            if first_chunk:
                live.stop()
            console.print(f"\n[red]Error: {e}[/red]\n")
        finally:
            if first_chunk:
                live.stop()
            loop.remove_signal_handler(signal.SIGINT)
            signal.signal(signal.SIGINT, signal.default_int_handler)

        if full or thought:
            usage_dict = {
                "input": agent.usage.input_tokens,
                "output": agent.usage.output_tokens,
                "cache": agent.usage.cache_tokens,
            }
            resp = Message(role="assistant", content=full, thought=thought, usage=usage_dict)
            history.append(resp)
            await store.save_message(session.id, resp)
            await store.touch(session.id)

            if agent._skills and agent.last_matched_skills:
                for _name in agent.last_matched_skills:
                    asyncio.create_task(asyncio.to_thread(agent._skills.record_hit, _name))

            # Per-turn delta (not cumulative)
            turn_in = agent.usage.input_tokens - prev_input
            turn_out = agent.usage.output_tokens - prev_output
            turn_cache = agent.usage.cache_tokens - prev_cache

            # Print per-turn stats in dim color
            stats_parts = [f"↑{_fmt_tokens(turn_in)} ↓{_fmt_tokens(turn_out)}"]
            if turn_cache:
                stats_parts.append(f"⚡{_fmt_tokens(turn_cache)}")
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

    # 后台尝试提炼 Skill（fire-and-forget）
    if user_turns >= 3:
        async def _maybe_gen_skill():
            try:
                from ethan.skills.generator import SkillGenerator
                gen = SkillGenerator(agent._provider)
                path = await gen.maybe_generate(history[-30:])
                if path:
                    console.print(f"[dim]✨ 已自动创建 Skill：{path.parent.name}[/dim]")
            except Exception:
                pass
        asyncio.create_task(_maybe_gen_skill())

    # 清理历史空 session（包括本次如果没有发任何消息的情况）
    try:
        cleaned = await store.cleanup_empty()
        if cleaned:
            pass  # 静默清理，不打印
    except Exception:
        pass

    await store.close()
