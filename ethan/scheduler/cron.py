"""调度器 — 基于 APScheduler 的定时任务系统。

支持 cron 表达式 and interval 两种模式，Job 持久化到 SQLite，重启后自动恢复。
"""
from typing import Callable

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ethan.core.config import CONFIG_DIR

DB_PATH = CONFIG_DIR / "scheduler.db"


class Scheduler:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        from ethan.core.timezone import get_local_timezone
        jobstores = {
            "default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}"),
        }
        self._scheduler = BackgroundScheduler(jobstores=jobstores, timezone=get_local_timezone())
        self._tz = get_local_timezone()

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _parse_end_date(self, end_date: str | None):
        """将 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM' 解析为 tz-aware datetime，解析失败返回 None。"""
        if not end_date:
            return None
        from datetime import datetime
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(end_date, fmt)
                # APScheduler 要求 tz-aware datetime；用 scheduler 自身的 timezone 本地化
                return self._tz.localize(dt) if hasattr(self._tz, "localize") else dt.replace(tzinfo=self._tz)
            except ValueError:
                continue
        return None

    def add_cron(
        self,
        job_id: str,
        func: Callable,
        cron_expr: str,
        end_date: str | None = None,
        **kwargs,
    ) -> None:
        """添加 cron 定时任务。cron_expr 格式：'分 时 日 月 周' 或标准 cron。

        统一走 from_crontab 解析，使用标准 cron 数字约定（0/7=周日，1=周一 … 5=周五，6=周六），
        而非 APScheduler 原生 CronTrigger 构造器（0=周一）——两者 day_of_week 含义不同，
        手动拆分传入会导致 '1-5' 被解释为 周二~周六。
        end_date：到期后 APScheduler 自动不再触发并删除 job。
        """
        # APScheduler 的 CronTrigger.from_crontab 在某些老版本或特定实现中可能不支持 end_date 关键字参数，
        # 我们需要在实例化 CronTrigger 之后手动或通过其他方式设置，或者在 add_job 时直接传，
        # 更好的做法是在实例化后，直接作为 CronTrigger 的属性或者通过 add_job 参数传递。
        # 事实上，CronTrigger 对象的属性有 end_date。
        # 为了兼容性，我们可以实例化之后单独赋值。
        trigger = CronTrigger.from_crontab(cron_expr, timezone=self._tz)
        if end_date:
            parsed_end_date = self._parse_end_date(end_date)
            if parsed_end_date:
                trigger.end_date = parsed_end_date

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
        end_date: str | None = None,
        **kwargs,
    ) -> None:
        """添加 interval 定时任务。end_date 到期后自动删除 job。"""
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours, end_date=self._parse_end_date(end_date)),
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

    def modify_name(self, job_id: str, new_name: str) -> bool:
        """修改定时任务的显示名称（持久化到 SQLite）。"""
        try:
            self._scheduler.modify_job(job_id, name=new_name)
            return True
        except Exception:
            return False