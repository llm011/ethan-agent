"""Schedule Tool — 让 agent 通过 tool call 创建和管理定时任务。"""
import json
import os
import threading
from contextvars import ContextVar
from typing import Any

from ethan.tools.base import BaseTool

# 存储当前请求的飞书 chat_id，在 lark webhook 里设置，ScheduleCreateTool 里读取
lark_chat_id_var: ContextVar[str] = ContextVar("lark_chat_id", default="")


def _base_url() -> str:
    """返回本地 serve 的 base URL（读取 ETHAN_SERVER_PORT，默认 8900）。"""
    port = os.environ.get("ETHAN_SERVER_PORT", "8900")
    return f"http://127.0.0.1:{port}"


def fire_schedule_job(session_id: str, prompt: str, channel: str = "web", channel_context: str = "{}", user_id: str = ""):
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
            from ethan.memory.session import SessionStore
            from ethan.providers.base import Message
            from ethan.core.paths import user_sessions_db_path
            async def log_error():
                store = SessionStore(db_path=user_sessions_db_path())
                await store.init()
                err_msg = Message(role="assistant", content=f"⚠️ 定时任务后台执行失败:\n```text\n{e}\n```")
                await store.save_message(session_id, err_msg)
                await store.touch(session_id)
                await store.close()
            try:
                asyncio.run(log_error())
            except Exception as e2:
                print(f"Failed to log error to session: {e2}")

        # 如果是飞书渠道发起的定时任务，把结果回发到对应的 chat
        if channel == "lark" and result_text:
            try:
                ctx = json.loads(channel_context)
                chat_id = ctx.get("chat_id", "")
                if chat_id:
                    from ethan.interface.lark import _get_lark_client, _send_lark_reply
                    import asyncio
                    client = _get_lark_client()
                    if client:
                        asyncio.run(_send_lark_reply(client, chat_id, result_text))
            except Exception as e3:
                print(f"Schedule lark reply error: {e3}")

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
            "prompt": {"type": "string", "description": "What to do when the task fires (a prompt or description)"},
            "cron": {"type": "string", "description": "Cron expression (5-part: min hour day month weekday). E.g. '0 9 * * *' for 9am daily. IMPORTANT: for weekday, always use names (mon-fri, sat, sun) not numbers — APScheduler's numeric weekday convention differs from standard cron (1-5 means Tue-Sat, not Mon-Fri)."},
            "interval_minutes": {"type": "integer", "description": "Alternative: run every N minutes."},
        },
        "required": ["job_id", "prompt"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, job_id: str, prompt: str, cron: str = "", interval_minutes: int = 0) -> str:
        from ethan.memory.session import SessionStore
        from ethan.core.config import get_config
        from ethan.core.paths import user_sessions_db_path
        import httpx

        if not cron and interval_minutes <= 0:
            return "Error: provide either 'cron' or 'interval_minutes'"

        # 读取当前请求上下文中的飞书 chat_id（非飞书渠道时为空字符串）
        chat_id = lark_chat_id_var.get("")
        channel = "lark" if chat_id else "web"
        channel_context = json.dumps({"chat_id": chat_id}) if chat_id else "{}"

        # Create a dedicated session for this task (per-user)
        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        session = await store.create(get_config().defaults.model)
        await store.update_title(session.id, f"[定时] {job_id}")
        await store.close()

        # Send request to FastAPI backend
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{_base_url()}/api/schedule", json={
                    "job_id": job_id,
                    "prompt": prompt,
                    "cron": cron,
                    "interval_minutes": interval_minutes,
                    "session_id": session.id,
                    "channel": channel,
                    "channel_context": channel_context,
                    "user_id": self._user_id,
                }, headers=headers)
                res.raise_for_status()
                return f"Scheduled '{job_id}' successfully. (Session: {session.id})"
        except Exception as e:
            return f"Failed to create job '{job_id}' via API: {e}"

class ScheduleListTool(BaseTool):
    fast_path = False
    name = "schedule_list"
    description = "List all scheduled tasks."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self) -> str:
        from ethan.core.config import get_config
        import httpx
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{_base_url()}/api/schedule", headers=headers)
                res.raise_for_status()
                jobs = res.json().get("jobs", [])
                if not jobs:
                    return "No scheduled tasks."
                lines = [f"- {j['id']}: {j['trigger']} (next: {j.get('next_run_time', 'None')}, status: {j.get('status', 'active')})" for j in jobs]
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
        from ethan.core.config import get_config
        import httpx
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.delete(f"{_base_url()}/api/schedule/{job_id}", headers=headers)
                res.raise_for_status()
                return f"Removed '{job_id}'"
        except Exception as e:
            return f"Failed to remove job '{job_id}': {e}"
