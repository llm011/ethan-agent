"""调度器 — 基于 APScheduler 的定时任务系统。

支持 cron 表达式和 interval 两种模式，Job 持久化到 SQLite，重启后自动恢复。
"""
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ethan.core.config import CONFIG_DIR

DB_PATH = CONFIG_DIR / "scheduler.db"


class Scheduler:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        jobstores = {
            "default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}"),
        }
        self._scheduler = BackgroundScheduler(jobstores=jobstores)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def add_cron(
        self,
        job_id: str,
        func: Callable,
        cron_expr: str,
        **kwargs,
    ) -> None:
        """添加 cron 定时任务。cron_expr 格式：'分 时 日 月 周' 或标准 cron。"""
        parts = cron_expr.strip().split()
        if len(parts) == 5:
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
        else:
            trigger = CronTrigger.from_crontab(cron_expr)

        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs=kwargs,
        )

    def add_interval(
        self,
        job_id: str,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        **kwargs,
    ) -> None:
        """添加 interval 定时任务。"""
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours),
            id=job_id,
            replace_existing=True,
            kwargs=kwargs,
        )

    def remove(self, job_id: str) -> bool:
        try:
            self._scheduler.remove_job(job_id)
            return True
        except Exception:
            return False

    def list_jobs(self) -> list[dict]:
        jobs = self._scheduler.get_jobs()
        result = []
        for job in jobs:
            result.append({
                "id": job.id,
                "name": job.name or job.id,
                "trigger": str(job.trigger),
                "next_run": str(job.next_run_time) if job.next_run_time else "paused",
            })
        return result

    def pause(self, job_id: str) -> bool:
        try:
            self._scheduler.pause_job(job_id)
            return True
        except Exception:
            return False

    def resume(self, job_id: str) -> bool:
        try:
            self._scheduler.resume_job(job_id)
            return True
        except Exception:
            return False
