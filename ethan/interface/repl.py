"""轻量 REPL 模式。

支持 Session 持久化、分层记忆、斜杠命令。
使用 prompt_toolkit 实现 Hermes 风格的状态栏 + 输入框。
"""
import asyncio
import signal
import time

from prompt_toolkit import PromptSession
from rich.live import Live
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from ethan.core.agent import Agent
from ethan.core.config import get_config
from ethan.memory.consolidator import Consolidator
from ethan.memory.episodic import EpisodeStore
from ethan.memory.facts import FactStore
from ethan.memory.session import Session, SessionStore, decide_title
from ethan.memory.working import MemoryConfig, WorkingMemory
from ethan.providers.base import Message

from .repl_commands import SlashCompleter, _handle_slash_command
from .repl_ui import _PT_STYLE, _banner, _fmt_tokens, _format_duration, _make_toolbar, _print_history, console


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


async def run_repl(agent: Agent, resume_id: str | None = None) -> None:
    """交互 REPL：Hermes 风格界面。"""
    config = get_config()
    model_id = agent._provider.model
    start_time = time.time()

    # 注入 TUI 授权 provider（敏感操作时 y/N 确认）。持有引用以便随 session 切换更新
    # session_id —— 同一会话内同工具授权过不再重复询问（与 Web 一致）。
    from ethan.core.consent import TuiConsentProvider, set_consent_provider
    consent_provider = TuiConsentProvider(console=console)
    set_consent_provider(consent_provider)

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
            agent._mode = getattr(session, "mode", "") or ""
            console.print(f"[green]Session restored: {session.title}[/green] [dim]({len(session.messages)} messages)[/dim]")
            if agent._mode:
                from ethan.core.modes import resolve_mode
                _m = resolve_mode(agent._mode)
                console.print(f"[dim]{_m.icon} 模式：{_m.label or agent._mode}[/dim]")
            _print_history(session.messages, limit=30)

    if not session:
        # 仅构造内存对象，不写 DB
        import time as _time
        _now = _time.time()
        from ethan.memory.session import _generate_id
        session = Session(id=_generate_id(), title="新对话", model=model_id, created_at=_now, updated_at=_now, source="repl")
        session_persisted = False

    _banner()

    # 当前 session 确定后，绑定到 consent provider 做 session 维度授权记忆
    consent_provider.session_id = session.id

    # ── Provider setup (runs any time no API key is configured) ──
    from ethan.core.onboarding import ONBOARDING_MESSAGE, is_first_time, needs_provider_setup
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

        from ethan.core.config import CONFIG_DIR, ProviderConfig, save_config
        from ethan.core.config import reload_config as _reload
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
        from ethan.core.config import CONFIG_DIR, reload_config, save_config
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
    from ethan.core.paths import user_episodes_path, user_facts_path
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
    btw_context_only = False  # /btw 单轮无历史模式，每轮用完即重置

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
            # /btw：顺带一问，不带历史，单轮轻量查询——不 continue，让它落到下面的 agent 流程
            from ethan.interface.channel_commands import btw_question, is_btw, resolve_custom_command
            if is_btw(user_input):
                q = btw_question(user_input)
                if not q:
                    console.print("[dim]/btw <问题>：不带历史的单轮查询[/dim]")
                    continue
                user_input = q
                # 设 btw_context_only = True，让下方 context 构建跳过 memory，只带本条消息
                btw_context_only = True
            elif (expanded := resolve_custom_command(user_input)) is not None:
                # 自定义命令展开后直接交 agent 处理（保留历史上下文）
                user_input = expanded
            else:
                result = await _handle_slash_command(user_input, store, session, agent)
                if result is not None:
                    session = result
                    session_persisted = True  # /resume 和 /new 返回的都是已持久化的 session
                    agent._mode = getattr(session, "mode", "") or ""  # 切会话同步模式
                    consent_provider.session_id = session.id  # 切换会话同步授权记忆作用域
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
                "INSERT INTO sessions (id, title, model, created_at, updated_at, source, mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session.id, session.title, session.model, session.created_at, session.updated_at, "repl", getattr(session, "mode", "") or ""),
            )
            await store._db.commit()
            session_persisted = True

        await store.save_message(session.id, msg)
        approx_tokens += len(user_input)

        # 标题策略：见 ethan.memory.session.decide_title
        # （短问题推迟到第 2 轮；第 3/6/9… 轮在仍是占位标题时兜底重试）
        title_snapshot = list(history)
        title_current = session.title
        async def _set_title():
            t = await decide_title(title_snapshot, title_current)
            if t and t != session.title:
                await store.update_title(session.id, t)
                session.title = t
        asyncio.create_task(_set_title())

        full = ""
        thought = ""
        first_chunk = True
        first_item = True  # for TTFT: fire on any first item (tool or text)
        last_was_tool = False  # 上一条输出是工具调用行，后续文字前加空行
        console.print()
        live = Live(Spinner("dots", text="thinking...", style="dim"), console=console, transient=True)
        live.start()
        send_time = time.time()
        ttft: float | None = None
        # Snapshot before this turn so we can compute per-turn delta
        prev_input = agent.usage.input_tokens
        prev_output = agent.usage.output_tokens
        prev_cache = agent.usage.cache_tokens

        context = [msg] if btw_context_only else memory.build_context() + [msg]
        btw_context_only = False  # 重置，不影响下一轮

        # Inner coroutine — captured by closure, can be awaited as a Task
        async def _consume_stream():
            nonlocal full, thought, first_chunk, first_item, ttft, last_was_tool
            from ethan.providers.base import ThinkingEvent, ToolEvent
            # transient=True：流式中原地更新（只渲染可见窗口，超长不重复刷屏），
            # 结束/切工具时擦除流式帧、再一次性 print 完整 markdown，保证层级稳定且不丢内容。
            render_live = Live(console=console, refresh_per_second=8, transient=True)
            try:
                async for item in agent.stream_chat(context):
                    if isinstance(item, ThinkingEvent):
                        continue  # 思考内容不打印
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
                            # A2UI 卡片：ui_card 工具产出的 envelope，用文本降级渲染器画成 Panel
                            if getattr(item, "ui", None):
                                try:
                                    from ethan.interface.a2ui_text import render_a2ui
                                    card = render_a2ui(item.ui)
                                    if card is not None:
                                        console.print(card)
                                        last_was_tool = True
                                        continue
                                except Exception:
                                    pass
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
                    # 全程用 markdown 渲染，保持标题/列表层级稳定，不再超长切纯文本
                    # （切纯文本是之前输出"混在一起"的主因）。流式帧用 transient Live，
                    # 结束/切工具时擦除并一次性 print 完整 markdown。
                    if not render_live.is_started:
                        if last_was_tool:
                            console.print()
                            last_was_tool = False
                        render_live.start()
                    render_live.update(RichMarkdown(full))
            finally:
                if render_live.is_started:
                    render_live.stop()  # transient：擦除流式帧
                    if full.strip():
                        console.print(RichMarkdown(full))  # 一次性提交最终 markdown，层级稳定且保留在屏
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
