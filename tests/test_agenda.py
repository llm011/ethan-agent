"""Agenda（日程）模块测试：store CRUD、调度注册、fire 回调、reconcile 对账。

隔离：scheduler.db / agenda.json 都指向 tmp_path，不碰真实 ~/.ethan。
"""
from datetime import timedelta

import pytest

import ethan.scheduler.agenda as agenda_mod
import ethan.scheduler.cron as cron_mod


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """隔离存储 + 重置单例。"""
    monkeypatch.setattr(cron_mod, "DB_PATH", tmp_path / "scheduler.db")
    monkeypatch.setattr(agenda_mod, "DB_PATH", tmp_path / "agenda.json")
    monkeypatch.setattr(cron_mod, "_shared_scheduler", None)
    monkeypatch.setattr(agenda_mod, "_store", None)
    yield
    sched = cron_mod._shared_scheduler
    if sched is not None:
        sched.shutdown()
    monkeypatch.setattr(cron_mod, "_shared_scheduler", None)


def _when_future(days=1, hour=9, minute=30):
    from datetime import datetime

    from ethan.core.timezone import get_local_timezone
    tz = get_local_timezone()
    now = datetime.now(tz)
    target = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target.strftime("%Y-%m-%d %H:%M")


# ── store ────────────────────────────────────────────────


def test_store_roundtrip(isolated):
    store = agenda_mod.get_agenda_store()
    ev = agenda_mod.create_event("写周报", _when_future(), note="先拉数据")
    assert ev["status"] == "pending"
    assert ev["id"].startswith("agenda:")

    got = store.get(ev["id"])
    assert got["title"] == "写周报"
    assert got["note"] == "先拉数据"

    # 持久化：新实例（模拟重启）能读回
    store2 = agenda_mod.AgendaStore(agenda_mod.DB_PATH)
    store2.load()
    assert store2.get(ev["id"])["title"] == "写周报"

    assert store.remove(ev["id"]) is True
    assert store.get(ev["id"]) is None


def test_create_validation(isolated):
    with pytest.raises(agenda_mod.AgendaError):
        agenda_mod.create_event("", _when_future())  # 空 title
    with pytest.raises(agenda_mod.AgendaError):
        agenda_mod.create_event("x", "2026-13-40 99:00")  # 非法时间
    with pytest.raises(agenda_mod.AgendaError):
        agenda_mod.create_event("x", _when_future(), repeat="yearly")  # 非法 repeat
    with pytest.raises(agenda_mod.AgendaError):
        agenda_mod.create_event("x", _when_future(), repeat="weekly")  # weekly 缺 weekdays
    with pytest.raises(agenda_mod.AgendaError):
        agenda_mod.create_event("x", "2020-01-01 09:00")  # 远古时间


# ── 调度注册 ─────────────────────────────────────────────


def test_job_registered_and_prefixed(isolated):
    from ethan.scheduler.cron import AGENDA_JOB_PREFIX, get_scheduler
    ev = agenda_mod.create_event("站会", _when_future())
    job = get_scheduler()._scheduler.get_job(ev["id"])
    assert job is not None
    assert job.id.startswith(AGENDA_JOB_PREFIX)


def test_repeat_daily_cron(isolated):
    from ethan.scheduler.cron import get_scheduler
    ev = agenda_mod.create_event("日报", _when_future(), repeat="daily")
    job = get_scheduler()._scheduler.get_job(ev["id"])
    # 明天同点位次日触发
    assert job.next_run_time is not None


def test_update_reschedules_and_reactivates(isolated):
    from ethan.scheduler.cron import get_scheduler
    ev = agenda_mod.create_event("旧标题", _when_future())
    store = agenda_mod.get_agenda_store()
    store.set_status(ev["id"], "fired")

    new_when = _when_future(days=2, hour=15)
    updated = agenda_mod.update_event(ev["id"], title="新标题", when=new_when)
    assert updated["title"] == "新标题"
    assert updated["status"] == "pending"  # 改时间重新激活
    job = get_scheduler()._scheduler.get_job(ev["id"])
    assert job is not None
    assert f"{job.next_run_time.hour:02d}:{job.next_run_time.minute:02d}" == "15:30"


def test_remove_event_removes_job(isolated):
    from ethan.scheduler.cron import get_scheduler
    ev = agenda_mod.create_event("临时", _when_future())
    assert agenda_mod.remove_event(ev["id"]) is True
    assert get_scheduler()._scheduler.get_job(ev["id"]) is None


# ── fire 回调 ────────────────────────────────────────────


def test_fire_marks_one_off_fired(monkeypatch, isolated):
    ev = agenda_mod.create_event("一次性", _when_future())
    sent = []
    monkeypatch.setattr(agenda_mod, "_dispatch_notification", lambda e: sent.append(e))

    agenda_mod.fire_agenda_event(ev["id"])
    store = agenda_mod.get_agenda_store()
    assert store.get(ev["id"])["status"] == "fired"
    assert sent and sent[0]["title"] == "一次性"


def test_fire_repeating_stays_pending(monkeypatch, isolated):
    ev = agenda_mod.create_event("每天喝水", _when_future(), repeat="daily")
    monkeypatch.setattr(agenda_mod, "_dispatch_notification", lambda e: None)

    agenda_mod.fire_agenda_event(ev["id"])
    store = agenda_mod.get_agenda_store()
    assert store.get(ev["id"])["status"] == "pending"


def test_fire_ignores_done(monkeypatch, isolated):
    ev = agenda_mod.create_event("已取消", _when_future())
    agenda_mod.complete_event(ev["id"])
    called = []
    monkeypatch.setattr(agenda_mod, "_dispatch_notification", lambda e: called.append(e))
    agenda_mod.fire_agenda_event(ev["id"])
    assert not called


# ── reconcile 对账 ───────────────────────────────────────


def test_reconcile_missed(isolated, monkeypatch):
    from datetime import datetime

    from ethan.core.timezone import get_local_timezone
    tz = get_local_timezone()
    past = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")

    # create_event 会拒绝远古时间；直接构造 store 数据模拟“创建后服务宕机一天”
    store = agenda_mod.get_agenda_store()
    raw = {
        "id": "agenda:deadbeef", "title": "昨天的会", "note": "", "when": past,
        "repeat": "none", "weekdays": [], "status": "pending",
        "created_at": past, "updated_at": past,
    }
    store.upsert(raw)

    notified = []
    monkeypatch.setattr(agenda_mod, "_dispatch_notification", lambda e: notified.append(e))
    stats = agenda_mod.reconcile()
    assert stats["missed"] == 1
    assert store.get("agenda:deadbeef")["status"] == "missed"
    assert notified  # 补发错过通知


def test_reconcile_restores_lost_job(isolated):
    from ethan.scheduler.cron import get_scheduler
    ev = agenda_mod.create_event("恢复我", _when_future())
    get_scheduler().remove(ev["id"])  # 模拟 scheduler.db 损坏丢 job
    stats = agenda_mod.reconcile()
    assert stats["restored"] == 1
    assert get_scheduler()._scheduler.get_job(ev["id"]) is not None


def test_reconcile_removes_orphan_jobs(isolated):
    from ethan.scheduler.cron import get_scheduler
    ev = agenda_mod.create_event("孤儿", _when_future())
    agenda_mod.get_agenda_store().remove(ev["id"])  # store 删了，job 留下
    stats = agenda_mod.reconcile()
    assert stats["orphans_removed"] == 1
    assert get_scheduler()._scheduler.get_job(ev["id"]) is None


# ── 工具 ────────────────────────────────────────────────


def test_agenda_tools_flow(isolated):
    import asyncio

    from ethan.tools.builtin.agenda import (
        AgendaAddTool,
        AgendaListTool,
        AgendaRemoveTool,
        AgendaUpdateTool,
    )

    out = asyncio.run(AgendaAddTool().run(title="测试日程", when=_when_future(hour=10)))
    assert "已添加" in out and "测试日程" in out
    events = agenda_mod.get_agenda_store().list_events()
    event_id = next(e["id"] for e in events if e["title"] == "测试日程")
    assert event_id.startswith("agenda:")

    listing = asyncio.run(AgendaListTool().run())
    assert "测试日程" in listing

    upd = asyncio.run(AgendaUpdateTool().run(event_id=event_id, title="改名日程"))
    assert "改名日程" in upd

    rm = asyncio.run(AgendaRemoveTool().run(event_id=event_id))
    assert "已删除" in rm
    listing2 = asyncio.run(AgendaListTool().run())
    assert "改名日程" not in listing2
