"""定时任务 session 轮转接线测试：job_id 注入 + count_today_runs 计数。"""
import asyncio

from ethan.core.config import get_config
from ethan.scheduler.cron import Scheduler


def test_rotate_threshold_config_exists():
    cfg = get_config()
    assert hasattr(cfg.defaults, "schedule_session_rotate_threshold")
    assert cfg.defaults.schedule_session_rotate_threshold >= 0


def test_add_cron_injects_job_id_into_kwargs():
    """add_cron 必须把 job_id 写进 job.kwargs：fire_schedule_job 依赖它
    在 session 轮转时回写新 session_id（modify_kwargs），缺失则轮转失效
    ——旧 session 计数恒超阈值，每次触发都会新建会话。"""
    def _fake_fire(**kwargs):
        pass

    sched = Scheduler()
    job_id = "test-rotate-job-id"
    try:
        sched.add_cron(job_id, _fake_fire, "* * * * *")
        job = sched._scheduler.get_job(job_id)
        assert job is not None
        assert job.kwargs.get("job_id") == job_id
        # modify_kwargs 能合并回写（轮转路径依赖）
        assert sched.modify_kwargs(job_id, session_id="sess-new")
        job = sched._scheduler.get_job(job_id)
        assert job.kwargs.get("session_id") == "sess-new"
        assert job.kwargs.get("job_id") == job_id  # 原有字段保留
    finally:
        sched.remove(job_id)


def test_count_today_runs_counts_user_messages(tmp_path):
    from ethan.memory.session import SessionStore

    async def _run():
        store = SessionStore(db_path=tmp_path / "s.db")
        await store.init()
        sid = (await store.create("test-model", source="schedule", mode="")).id
        from ethan.providers.base import Message

        for _ in range(3):
            await store.save_message(sid, Message(role="user", content="run"))
        return await store.count_today_runs(sid)

    assert asyncio.run(_run()) == 3
