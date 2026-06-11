"""Schedule Tool — 让 agent 通过 tool call 创建和管理定时任务。"""
import json
from typing import Any

from ethan.tools.base import BaseTool


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
        from ethan.scheduler.cron import Scheduler

        def _fire():
            import subprocess
            subprocess.Popen(["uv", "run", "python", "-m", "ethan.interface.cli", "-p", prompt],
                             cwd="/Users/jsongo/code/life/ethan-ai")

        s = Scheduler()
        s.start()
        if cron:
            s.add_cron(job_id, _fire, cron)
        elif interval_minutes > 0:
            s.add_interval(job_id, _fire, minutes=interval_minutes)
        else:
            s.shutdown()
            return "Error: provide either 'cron' or 'interval_minutes'"

        jobs = s.list_jobs()
        job = next((j for j in jobs if j["id"] == job_id), None)
        s.shutdown()

        if job:
            return f"Scheduled '{job_id}': {job['trigger']} — next run: {job['next_run']}"
        return f"Failed to create job '{job_id}'"


class ScheduleListTool(BaseTool):
    name = "schedule_list"
    description = "List all scheduled tasks."
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self) -> str:
        from ethan.scheduler.cron import Scheduler
        s = Scheduler()
        s.start()
        jobs = s.list_jobs()
        s.shutdown()
        if not jobs:
            return "No scheduled tasks."
        lines = [f"- {j['id']}: {j['trigger']} (next: {j['next_run']})" for j in jobs]
        return "\n".join(lines)


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
        from ethan.scheduler.cron import Scheduler
        s = Scheduler()
        s.start()
        ok = s.remove(job_id)
        s.shutdown()
        return f"Removed '{job_id}'" if ok else f"Job '{job_id}' not found"
