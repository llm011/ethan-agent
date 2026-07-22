"""Schedule Tool — 让 agent 通过 tool call 创建和管理定时任务。"""
import json
import os
import threading
from contextvars import ContextVar

from ethan.tools.base import BaseTool

# 存储当前请求的飞书 chat_id，在 lark webhook 里设置，ScheduleCreateTool 里读取
lark_chat_id_var: ContextVar[str] = ContextVar("lark_chat_id", default="")
wechat_chat_id_var: ContextVar[str] = ContextVar("wechat_chat_id", default="")


def _try_strptime(s: str, fmt: str) -> bool:
    from datetime import datetime
    try:
        datetime.strptime(s, fmt)
        return True
    except ValueError:
        return False


def _base_url() -> str:
    """返回本地 serve 的 base URL（读取 ETHAN_SERVER_PORT，默认 8900）。"""
    port = os.environ.get("ETHAN_SERVER_PORT", "8900")
    return f"http://127.0.0.1:{port}"


def _make_fallback_title(prompt: str) -> str:
    """无 title 时从 prompt 生成短标题：中文取前 15 字，英文取前 5 个单词。"""
    text = prompt.replace("\n", " ").strip()
    if not text:
        return "未命名任务"
    words = text.split()
    # 含中文字符 → 按字数截取
    if any('\u4e00' <= c <= '\u9fff' for c in text[:20]):
        return text[:15] + ("…" if len(text) > 15 else "")
    # 纯英文 → 按单词截取
    if len(words) <= 5:
        return text
    return " ".join(words[:5]) + "…"


def fire_schedule_job(session_id: str, prompt: str, channel: str = "web", channel_context: str = "{}", user_id: str = "", title: str = "", **_extra):
    """定时任务触发时的回调。

    **_extra 接收并忽略 timeline / scene / source_timeline 等元数据字段，
    它们用于 UI 分类展示，不参与 fire 行为。
    """
    def _do_fire():
        import requests

        from ethan.core.config import get_config
        result_text = ""
        try:
            # 用该 job 所属用户的 web_token 调 /chat（落到该用户的会话/记忆）
            token = ""
            if user_id:
                from ethan.core.users import get_user_store
                user = get_user_store().get_user(user_id)
                if user:
                    token = user.web_token
            if not token:
                token = get_config().network.auth_token
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            res = requests.post(f"{_base_url()}/api/chat", json={
                "messages": [{"role": "user", "content": prompt}],
                "session_id": session_id,
            }, headers=headers, timeout=120)
            res.raise_for_status()
            result_text = res.json().get("content", "")
        except Exception as e:
            print(f"Schedule fire error: {e}")
            result_text = f"⚠️ 定时任务执行失败: {e}"
            import asyncio

            # 本路径跑在 daemon 线程的 asyncio.run() 临时 loop 里，
            # 而 get_session_store() 的 _session_store_lock 是绑定到主
            # server loop 的模块级 asyncio.Lock（非线程安全）。跨 loop
            # await 会触发 "got Future attached to a different loop"。
            # 这里像 core/heartbeat.py:_rotate_session_dbs 那样开独立
            # 连接写错误日志，绕开单例。
            from ethan.core.paths import user_sessions_db_path
            from ethan.memory.session import SessionStore
            from ethan.providers.base import Message
            async def log_error():
                store = SessionStore(db_path=user_sessions_db_path())
                await store.init()
                try:
                    err_msg = Message(role="assistant", content=f"⚠️ 定时任务后台执行失败:\n```text\n{e}\n```")  # noqa: F821 — closure over except-var
                    await store.save_message(session_id, err_msg)
                    await store.touch(session_id)
                finally:
                    await store.close()
            try:
                asyncio.run(log_error())
            except Exception as e2:
                print(f"Failed to log error to session: {e2}")

        # 把结果发回来源渠道（飞书/微信）
        if result_text:
            display_title = title or _make_fallback_title(prompt)
            formatted = f"【定时任务】{display_title}\n{result_text}"

            if channel == "lark":
                try:
                    ctx = json.loads(channel_context)
                    chat_id = ctx.get("chat_id", "")
                    if chat_id:
                        import asyncio

                        from ethan.interface.lark import _get_lark_client, _send_lark_reply
                        client = _get_lark_client()
                        if client:
                            try:
                                asyncio.run(_send_lark_reply(client, chat_id, formatted))
                            except RuntimeError:
                                # 当前处于 event loop 内时降级：用 create_task 异步发送
                                loop = asyncio.get_running_loop()
                                loop.create_task(_send_lark_reply(client, chat_id, formatted))
                except Exception as e3:
                    print(f"Schedule lark reply error: {e3}")

            elif channel == "wechat":
                try:
                    ctx = json.loads(channel_context)
                    to_user_id = ctx.get("to_user_id", "")
                    if to_user_id:
                        import asyncio

                        import httpx

                        from ethan.interface.wechat_ilink import load_credentials, send_text
                        creds = load_credentials()
                        if creds:
                            async def _send_wechat():
                                async with httpx.AsyncClient() as client:
                                    await send_text(client, creds, to_user_id, "", formatted)
                            try:
                                asyncio.run(_send_wechat())
                            except RuntimeError:
                                # 当前处于 event loop 内时降级：用 create_task 异步发送
                                loop = asyncio.get_running_loop()
                                loop.create_task(_send_wechat())
                except Exception as e4:
                    print(f"Schedule wechat reply error: {e4}")

    # Run in a separate thread so we don't block the APScheduler worker pool!
    threading.Thread(target=_do_fire, daemon=True).start()

class ScheduleCreateTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "schedule_create"
    description = "Create a scheduled task. Use for reminders, recurring checks, or timed automations. Cron expressions are interpreted in the user's local timezone."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Unique job ID (e.g. 'morning-reminder')"},
            "title": {"type": "string", "description": "Short human-readable title for this task (e.g. '每日早报', 'Weekly report'). Shown in task list and notifications."},
            "prompt": {"type": "string", "description": "What to do when the task fires (a prompt or description)"},
            "cron": {"type": "string", "description": "Cron expression (5-part: min hour day month weekday). E.g. '0 9 * * *' for 9am daily. IMPORTANT: for weekday, always use names (mon-fri, sat, sun) not numbers — APScheduler's numeric weekday convention differs from standard cron (1-5 means Tue-Sat, not Mon-Fri)."},
            "interval_minutes": {"type": "integer", "description": "Alternative: run every N minutes."},
            "end_date": {"type": "string", "description": "Optional: date (YYYY-MM-DD) or datetime (YYYY-MM-DD HH:MM) when the job should stop firing. After this date the job is automatically removed."},
            "category": {"type": "string", "description": "Task category for UI grouping: 'one_off' (one-time reminder), 'recurring' (regular repeat), or 'timeline' (driven by team-manager timeline). Default 'one_off' for one-time tasks, 'recurring' for cron/interval."},
        },
        "required": ["job_id", "prompt"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, job_id: str, prompt: str, title: str = "", cron: str = "", interval_minutes: int = 0, end_date: str = "", category: str = "") -> str:
        import httpx

        from ethan.core.config import get_config
        from ethan.memory.session import get_session_store

        if not cron and interval_minutes <= 0:
            return "Error: provide either 'cron' or 'interval_minutes'"

        # title 兜底：模型没给 title 时自动从 prompt 生成
        if not title:
            title = _make_fallback_title(prompt)

        # category 兜底：未显式指定时按 trigger 推断
        if not category:
            category = "recurring" if cron or interval_minutes > 0 else "one_off"

        # 验证 end_date 格式（早于实际创建 session 前拦截，避免 job 创建成功但日期无效）
        if end_date and not any(_try_strptime(end_date, fmt) for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d")):
            return f"Error: invalid end_date '{end_date}'. Use YYYY-MM-DD or YYYY-MM-DD HH:MM format."

        # 读取当前请求上下文中的渠道信息
        chat_id = lark_chat_id_var.get("")
        wechat_id = wechat_chat_id_var.get("")
        if chat_id:
            channel = "lark"
            channel_context = json.dumps({"chat_id": chat_id})
        elif wechat_id:
            channel = "wechat"
            channel_context = json.dumps({"to_user_id": wechat_id})
        else:
            channel = "web"
            channel_context = "{}"

        # Create a dedicated session for this task (per-user)
        store = await get_session_store()
        session = await store.create(get_config().defaults.model, source="schedule")
        await store.update_title(session.id, f"[定时] {title}")

        # Send request to FastAPI backend
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{_base_url()}/api/schedule", json={
                    "job_id": job_id,
                    "title": title,
                    "prompt": prompt,
                    "cron": cron,
                    "interval_minutes": interval_minutes,
                    "end_date": end_date,
                    "session_id": session.id,
                    "channel": channel,
                    "channel_context": channel_context,
                    "user_id": self._user_id,
                    "category": category,
                }, headers=headers)
                res.raise_for_status()
                msg = f"Scheduled '{job_id}' successfully."
                if end_date:
                    msg += f" Auto-expires on {end_date}."
                return msg + f" (Session: {session.id})"
        except Exception as e:
            return f"Failed to create job '{job_id}' via API: {e}"


class ScheduleListTool(BaseTool):
    fast_path = False
    name = "schedule_list"
    description = "List all scheduled tasks."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self) -> str:
        import httpx

        from ethan.core.config import get_config
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{_base_url()}/api/schedule", headers=headers)
                res.raise_for_status()
                jobs = res.json().get("jobs", [])
                if not jobs:
                    return "No scheduled tasks."
                lines = []
                for j in jobs:
                    title = j.get("title", "") or j["id"]
                    prompt = j.get("prompt", "")
                    prompt_preview = (prompt[:80] + "…") if len(prompt) > 80 else prompt
                    line = f"- {j['id']}: {j['trigger']} (next: {j.get('next_run_time', 'None')}, status: {j.get('status', 'active')})"
                    if title and title != j["id"]:
                        line += f"\n  title: {title}"
                    if prompt_preview:
                        line += f"\n  prompt: {prompt_preview}"
                    lines.append(line)
                return "\n".join(lines)
        except Exception as e:
            return f"Failed to list schedules: {e}"


class ScheduleRemoveTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "schedule_remove"
    description = "Remove a scheduled task by its ID."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to remove"},
        },
        "required": ["job_id"],
    }

    async def run(self, job_id: str) -> str:
        import httpx

        from ethan.core.config import get_config
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.delete(f"{_base_url()}/api/schedule/{job_id}", headers=headers)
                res.raise_for_status()
                return f"Removed '{job_id}'"
        except Exception as e:
            return f"Failed to remove job '{job_id}': {e}"
