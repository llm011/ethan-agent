"""调度器 — 基于 APScheduler 的定时任务系统。

支持 cron 表达式 and interval 两种模式，Job 持久化到 SQLite，重启后自动恢复。
"""
from typing import Callable

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ethan.core.config import CONFIG_DIR

_DB_DIR = CONFIG_DIR / "db"
_DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DB_DIR / "scheduler.db"

# 一次性迁移：旧位置 → 新位置。try/except 兜底并发首次启动的竞态。
_OLD_DB = CONFIG_DIR / "scheduler.db"
if _OLD_DB.exists() and not DB_PATH.exists():
    import shutil
    try:
        shutil.move(str(_OLD_DB), str(DB_PATH))
    except (FileNotFoundError, OSError):
        pass  # 另一进程已迁移/正在迁移，忽略


class Scheduler:
    def __init__(self):
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        from ethan.core.timezone import ensure_timezone_in_config, get_local_timezone
        # 确保时区已持久化到 config，避免探测漂移
        ensure_timezone_in_config()
        jobstores = {
            "default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}"),
        }
        self._scheduler = BackgroundScheduler(jobstores=jobstores, timezone=get_local_timezone())
        self._tz = get_local_timezone()

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            self._migrate_job_timezones()

    def _migrate_job_timezones(self) -> None:
        """启动时检查所有 cron job 的 trigger 时区，与当前配置时区不一致的自动修复。

        旧 job 可能在未配置时区（默认 UTC）时创建，trigger 内部绑定了 UTC，
        导致即使 scheduler 现在用本地时区，旧 job 仍按 UTC 计算下次执行时间。
        修复方式：用相同的 cron 字段 + 正确时区重建 trigger。
        """
        import logging
        logger = logging.getLogger(__name__)
        tz_name = getattr(self._tz, "key", None) or str(self._tz)
        for job in self._scheduler.get_jobs():
            trigger = job.trigger
            if not isinstance(trigger, CronTrigger):
                continue
            trigger_tz = getattr(trigger, "timezone", None)
            trigger_tz_name = getattr(trigger_tz, "key", None) or str(trigger_tz) if trigger_tz else "UTC"
            if trigger_tz_name == tz_name:
                continue
            # 从现有 trigger 提取 cron 字段，用正确时区重建
            try:
                fields = {}
                for field in trigger.fields:
                    expr = str(field)
                    if expr != "*":
                        fields[field.name] = expr
                new_trigger = CronTrigger(timezone=self._tz, **fields)
                # 保留 end_date
                if hasattr(trigger, "end_date") and trigger.end_date:
                    new_trigger.end_date = trigger.end_date
                self._scheduler.reschedule_job(job.id, trigger=new_trigger)
                logger.info("Migrated job %s timezone: %s → %s", job.id, trigger_tz_name, tz_name)
            except Exception:
                logger.warning("Failed to migrate timezone for job %s", job.id, exc_info=True)

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
        name: str | None = None,
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
            name=name or job_id,
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
        name: str | None = None,
        **kwargs,
    ) -> None:
        """添加 interval 定时任务。end_date 到期后自动删除 job。"""
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours, end_date=self._parse_end_date(end_date)),
            id=job_id,
            name=name or job_id,
            replace_existing=True,
            kwargs=kwargs,
        )

    def add_date(
        self,
        job_id: str,
        func: Callable,
        run_date: str,
        name: str | None = None,
        **kwargs,
    ) -> None:
        """添加一次性定时任务，在指定时间触发一次后自动删除。

        run_date: 'YYYY-MM-DD HH:MM' 或 'YYYY-MM-DD'（默认 10:00）
        """
        from datetime import datetime
        if " " not in run_date:
            run_date = f"{run_date} 10:00"
        dt = datetime.strptime(run_date, "%Y-%m-%d %H:%M")
        aware = self._tz.localize(dt) if hasattr(self._tz, "localize") else dt.replace(tzinfo=self._tz)
        self._scheduler.add_job(
            func,
            trigger=DateTrigger(run_date=aware, timezone=self._tz),
            id=job_id,
            name=name or job_id,
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

    def run_job_now(self, job_id: str) -> bool:
        """手动触发一次任务执行（不影响下次调度时间）。

        直接调用 job.func(**job.kwargs)，绕过 APScheduler 的 reschedule 逻辑，
        避免 modify_job(next_run_time=now) 把周期任务的整体时间表往前挪。
        fire_schedule_job 内部起线程异步跑，这里立即返回。
        """
        try:
            job = self._scheduler.get_job(job_id)
            if not job:
                return False
            # job.func 是 APScheduler 包装后的；直接调会走 fire_schedule_job
            # kwargs 里可能有 source_timeline 等元数据，fire_schedule_job 用 **_extra 接收
            job.func(**job.kwargs)
            return True
        except Exception:
            return False

    def modify_kwargs(self, job_id: str, **new_kwargs) -> bool:
        """修改定时任务的执行参数（如 prompt）。合并到现有 kwargs 中。"""
        try:
            job = self._scheduler.get_job(job_id)
            if not job:
                return False
            merged = dict(job.kwargs or {})
            merged.update(new_kwargs)
            self._scheduler.modify_job(job_id, kwargs=merged)
            return True
        except Exception:
            return False