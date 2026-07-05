"""REPL slash commands: ProfileSwitchException, command list, completer, handler."""
from datetime import datetime

from prompt_toolkit.completion import Completer, Completion
from rich.table import Table

from ethan.core.agent import Agent
from ethan.core.config import get_config
from ethan.memory.session import Session, SessionStore
from .repl_ui import console


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
    ("/mode", "Show or switch conversation mode"),
    ("/profile", "Show or switch user profile"),
    ("/config", "Edit settings interactively"),
    ("/token", "Show or rotate Web login token"),
    ("/skills", "List installed skills"),
    ("/update", "Update Ethan Agent"),
    ("/compact", "Summarize history to free context"),
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
        # 新会话沿用当前模式（在法律/陪伴模式里 /new 通常想继续同模式）
        cur_mode = getattr(agent, "_mode", "") or ""
        new_session = await store.create(agent._provider.model, source="repl", mode=cur_mode)
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

    elif command == "/mode":
        from ethan.core.modes import MODES, match_mode, resolve_mode
        if len(parts) < 2:
            cur = resolve_mode(getattr(agent, "_mode", "") or "")
            avail = "，".join(
                ["默认 (default)"] + [f"{m.label or m.key} ({'/'.join(a for a in m.aliases if a)})" for m in MODES]
            )
            console.print(f"[dim]当前模式：[cyan]{cur.label or '默认（工作助手）'}[/cyan][/dim]")
            console.print(f"[dim]切换：/mode <名称>（如 /mode 法律）；/mode default 切回默认[/dim]")
            console.print(f"[dim]可用：{avail}[/dim]")
        else:
            target = match_mode(parts[1].strip())
            if target is None:
                console.print(f"[yellow]未识别的模式：{parts[1].strip()}，当前模式保持不变。[/yellow]")
            else:
                agent._mode = target.key
                session.mode = target.key
                # 持久化；session 尚未入库时为 no-op，首条消息入库会带上 session.mode
                try:
                    await store.update_mode(session.id, target.key)
                except Exception:
                    pass
                if not target.key:
                    console.print("[green]🛠 已切回默认（工作助手）模式。[/green]")
                else:
                    console.print(f"[green]{target.icon} 已切换到「{target.label or target.key}」模式。[/green]")
                    if target.blurb:
                        console.print(f"[dim]{target.blurb}[/dim]")
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
  /compact       Summarize history to free context
  /model [ID]    Show or switch model
  /mode [NAME]   Show or switch conversation mode (e.g. /mode 法律, /mode default)
  /profile [ID]  Show or switch user profile
  /config        Edit settings interactively
  /token [rotate]  Show or rotate Web login token
  /skills        List installed skills
  /update        Update Ethan Agent
  /help          Show this help[/dim]""")
        return None

    elif command == "/compact":
        from ethan.core.session_ops import compact_session
        with console.status("[dim]压缩历史中...[/dim]"):
            summary = await compact_session(store, session.id, agent._provider.model)
        if summary.startswith(("对话太短", "没有可压缩", "压缩失败", "会话不存在")):
            console.print(f"[yellow]{summary}[/yellow]")
            return None
        preview = summary if len(summary) <= 120 else summary[:120] + "…"
        console.print(f"[green]✓ 已压缩历史[/green] [dim]（保留最近一轮）[/dim]")
        console.print(f"[dim]{preview}[/dim]")
        # 重载 session，触发主循环重建 history/memory
        reloaded = await store.load(session.id)
        return reloaded

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
