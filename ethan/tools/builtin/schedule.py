"""Schedule Tool — 让 agent 通过 tool call 创建和管理定时任务。"""
import json
import threading
from typing import Any

from ethan.tools.base import BaseTool

def fire_schedule_job(session_id: str, prompt: str):
    def _do_fire():
        import requests
        from ethan.core.config import get_config
        try:
            token = get_config().network.auth_token
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            # Fire and forget (don't care about the response stream here, it will be saved to session DB by the server)
            res = requests.post("http://127.0.0.1:8900/chat", json={
                "messages": [{"role": "user", "content": prompt}],
                "session_id": session_id,
            }, headers=headers, timeout=120)
            res.raise_for_status()
        except Exception as e:
            print(f"Schedule fire error: {e}")
            import asyncio
            from ethan.memory.session import SessionStore
            from ethan.providers.base import Message
            async def log_error():
                store = SessionStore()
                await store.init()
                err_msg = Message(role="assistant", content=f"⚠️ 定时任务后台执行失败:\n```text\n{e}\n```")
                await store.save_message(session_id, err_msg)
                await store.touch(session_id)
                await store.close()
            try:
                asyncio.run(log_error())
            except Exception as e2:
                print(f"Failed to log error to session: {e2}")
            
    # Run in a separate thread so we don't block the APScheduler worker pool!
    threading.Thread(target=_do_fire, daemon=True).start()

class ScheduleCreateTool(BaseTool):
    name = "schedule_create"
    description = "Create a scheduled task. Use for reminders, recurring checks, or timed automations."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Unique job ID (e.g. 'morning-reminder')"},
            "prompt": {"type": "string", "description": "What to do when the task fires (a prompt or description)"},
            "cron": {"type": "string", "description": "Cron expression (5-part: min hour day month weekday). E.g. '0 9 * * *' for 9am daily."},
            "interval_minutes": {"type": "integer", "description": "Alternative: run every N minutes."},
        },
        "required": ["job_id", "prompt"],
    }

    async def run(self, job_id: str, prompt: str, cron: str = "", interval_minutes: int = 0) -> str:
        from ethan.memory.session import SessionStore
        from ethan.core.config import get_config
        import httpx

        if not cron and interval_minutes <= 0:
            return "Error: provide either 'cron' or 'interval_minutes'"

        # Create a dedicated session for this task
        store = SessionStore()
        await store.init()
        session = await store.create(get_config().defaults.model)
        await store.update_title(session.id, f"[定时] {job_id}")
        await store.close()

        # Send request to FastAPI backend
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post("http://127.0.0.1:8900/schedule", json={
                    "job_id": job_id,
                    "prompt": prompt,
                    "cron": cron,
                    "interval_minutes": interval_minutes,
                    "session_id": session.id
                }, headers=headers)
                res.raise_for_status()
                return f"Scheduled '{job_id}' successfully. (Session: {session.id})"
        except Exception as e:
            return f"Failed to create job '{job_id}' via API: {e}"

class ScheduleListTool(BaseTool):
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
                res = await client.get("http://127.0.0.1:8900/schedule", headers=headers)
                res.raise_for_status()
                jobs = res.json().get("jobs", [])
                if not jobs:
                    return "No scheduled tasks."
                lines = [f"- {j['id']}: {j['trigger']} (next: {j['next_run']}, state: {j.get('state', 'active')})" for j in jobs]
                return "\n".join(lines)
        except Exception as e:
            return f"Failed to list schedules: {e}"


class ScheduleRemoveTool(BaseTool):
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
                res = await client.delete(f"http://127.0.0.1:8900/schedule/{job_id}", headers=headers)
                res.raise_for_status()
                return f"Removed '{job_id}'"
        except Exception as e:
            return f"Failed to remove job '{job_id}': {e}"
