"""日程（Agenda）— 独立于定时任务的一天日程管理系统。

与定时任务（schedule）的区别：
- 定时任务到点跑一个完整 agent 会话（fire_schedule_job）；
- 日程到点**只发桌面通知**（DesktopHub → WS → Tauri 系统通知），不产生会话，
  确定性触发、零模型成本。未来接入 app 推送时只需在 _dispatch_notification 加一路。

调度内核复用同一个 APScheduler 实例（见 cron.get_scheduler），
job id 以 "agenda:" 前缀隔离；日程元数据（重复规则/状态）独立存 agenda.json。
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ethan.core.config import CONFIG_DIR
from ethan.scheduler.cron import AGENDA_JOB_PREFIX, get_scheduler

logger = logging.getLogger("ethan.agenda")

DB_PATH = CONFIG_DIR / "db" / "agenda.json"

# 与 APScheduler misfire_grace_time 一致的宽限窗口（秒）：
# 一次性日程错过在该窗口内仍会补触发，超过则标记 missed。
MISFIRE_GRACE_SECONDS = 300

_REPEAT_VALUES = ("none", "daily", "weekly")
# ISO weekday：1=周一 … 7=周日
_WEEKDAY_ABBR = {1: "mon", 2: "tue", 3: "wed", 4: "thu", 5: "fri", 6: "sat", 7: "sun"}


def _now() -> datetime:
    from ethan.core.timezone import get_local_timezone
    tz = get_local_timezone()
    return datetime.now(tz)


def _parse_when(when: str) -> datetime:
    """'YYYY-MM-DD HH:MM' → tz-aware datetime（本地时区）。失败抛 ValueError。"""
    from ethan.core.timezone import get_local_timezone
    tz = get_local_timezone()
    dt = datetime.strptime(when, "%Y-%m-%d %H:%M")
    return tz.localize(dt) if hasattr(tz, "localize") else dt.replace(tzinfo=tz)


class AgendaError(ValueError):
    """参数校验错误（时间格式非法、时间过早等）。"""


class AgendaStore:
    """日程元数据存储（agenda.json）。线程安全：APScheduler 回调线程与
    API async 线程都会写（标 fired/missed），用锁 + 原子写保护。"""

    def __init__(self, path: Path | None = None):
        self._path = path or DB_PATH
        self._lock = threading.Lock()
        self._data: dict = {"events": []}

    def load(self) -> None:
        with self._lock:
            self._data = self._read()

    def _read(self) -> dict:
        if not self._path.exists():
            return {"events": []}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("events"), list):
                return data
        except (json.JSONDecodeError, OSError):
            logger.warning("agenda.json unreadable, starting empty", exc_info=True)
        return {"events": []}

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ── CRUD ───────────────────────────────────────────────

    def list_events(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._data["events"]]

    def get(self, event_id: str) -> dict | None:
        with self._lock:
            for e in self._data["events"]:
                if e["id"] == event_id:
                    return dict(e)
        return None

    def upsert(self, event: dict) -> None:
        with self._lock:
            for i, e in enumerate(self._data["events"]):
                if e["id"] == event["id"]:
                    self._data["events"][i] = event
                    break
            else:
                self._data["events"].append(event)
            self._write()

    def set_status(self, event_id: str, status: str) -> dict | None:
        with self._lock:
            for e in self._data["events"]:
                if e["id"] == event_id:
                    e["status"] = status
                    e["updated_at"] = _now().isoformat()
                    self._write()
                    return dict(e)
        return None

    def remove(self, event_id: str) -> bool:
        with self._lock:
            before = len(self._data["events"])
            self._data["events"] = [e for e in self._data["events"] if e["id"] != event_id]
            removed = len(self._data["events"]) < before
            if removed:
                self._write()
        return removed


_store: AgendaStore | None = None


def get_agenda_store() -> AgendaStore:
    global _store
    if _store is None:
        _store = AgendaStore(DB_PATH)
        _store.load()
    return _store


# ── 调度桥接 ─────────────────────────────────────────────


def _validate_payload(title: str, when: str, repeat: str, weekdays: list[int]) -> datetime:
    if not title.strip():
        raise AgendaError("title 不能为空")
    try:
        dt = _parse_when(when)
    except ValueError:
        raise AgendaError(f"when 格式非法：{when!r}，应为 'YYYY-MM-DD HH:MM'")
    if repeat not in _REPEAT_VALUES:
        raise AgendaError(f"repeat 必须是 {'/'.join(_REPEAT_VALUES)}， got {repeat!r}")
    if repeat == "weekly":
        if not weekdays:
            raise AgendaError("repeat=weekly 需要非空 weekdays（1=周一 … 7=周日）")
        for d in weekdays:
            if not isinstance(d, int) or not 1 <= d <= 7:
                raise AgendaError(f"weekdays 取值须为 1-7（ISO，1=周一），got {weekdays!r}")
    return dt


def _register_job(event: dict) -> None:
    """把日程事件注册到共享 APScheduler（replace_existing 幂等）。"""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger

    from ethan.core.timezone import get_local_timezone

    scheduler = get_scheduler()
    tz = get_local_timezone()
    dt = _parse_when(event["when"])
    if event["repeat"] == "none":
        trigger: object = DateTrigger(run_date=dt, timezone=tz)
    elif event["repeat"] == "daily":
        trigger = CronTrigger(hour=dt.hour, minute=dt.minute, timezone=tz)
    else:  # weekly
        days = ",".join(sorted({_WEEKDAY_ABBR[d] for d in event["weekdays"]}))
        trigger = CronTrigger(day_of_week=days, hour=dt.hour, minute=dt.minute, timezone=tz)

    scheduler._scheduler.add_job(
        fire_agenda_event,
        trigger=trigger,
        id=event["id"],
        name=event["title"] or event["id"],
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        kwargs={"event_id": event["id"]},
    )


def create_event(title: str, when: str, repeat: str = "none", weekdays: list[int] | None = None,
                 note: str = "") -> dict:
    """创建日程：写 store + 注册调度。时间过早（超出宽限窗口）直接报错。"""
    weekdays = weekdays or []
    dt = _validate_payload(title, when, repeat, weekdays)

    if repeat == "none" and dt < _now() - timedelta(seconds=MISFIRE_GRACE_SECONDS):
        raise AgendaError(f"时间 {when} 已过去超过 {MISFIRE_GRACE_SECONDS // 60} 分钟，无法创建日程")

    event = {
        "id": f"{AGENDA_JOB_PREFIX}{secrets.token_hex(4)}",
        "title": title.strip(),
        "note": note or "",
        "when": when,
        "repeat": repeat,
        "weekdays": sorted(set(weekdays)) if repeat == "weekly" else [],
        "status": "pending",
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    store = get_agenda_store()
    _register_job(event)
    store.upsert(event)
    return event


def update_event(event_id: str, title: str | None = None, when: str | None = None,
                 repeat: str | None = None, weekdays: list[int] | None = None,
                 note: str | None = None) -> dict:
    """修改日程。时间/重复规则变化时重建调度 job；已终结（fired/missed/done）
    的事件改时间会重新激活为 pending。"""
    store = get_agenda_store()
    ev = store.get(event_id)
    if not ev:
        raise AgendaError(f"日程不存在：{event_id}")

    new_title = title if title is not None else ev["title"]
    new_when = when if when is not None else ev["when"]
    new_repeat = repeat if repeat is not None else ev["repeat"]
    new_weekdays = weekdays if weekdays is not None else ev.get("weekdays", [])
    new_note = note if note is not None else ev["note"]

    dt = _validate_payload(new_title, new_when, new_repeat, new_weekdays)
    rescheduled = (new_when != ev["when"] or new_repeat != ev["repeat"]
                   or new_weekdays != ev.get("weekdays", []))
    if rescheduled and new_repeat == "none" and dt < _now() - timedelta(seconds=MISFIRE_GRACE_SECONDS):
        raise AgendaError(f"时间 {new_when} 已过去超过 {MISFIRE_GRACE_SECONDS // 60} 分钟")

    updated = dict(ev)
    updated.update({
        "title": new_title.strip(), "note": new_note, "when": new_when,
        "repeat": new_repeat,
        "weekdays": sorted(set(new_weekdays)) if new_repeat == "weekly" else [],
        "updated_at": _now().isoformat(),
    })
    if rescheduled:
        updated["status"] = "pending"
    store.upsert(updated)
    if rescheduled:
        _register_job(updated)  # replace_existing 原子替换
    return updated


def remove_event(event_id: str) -> bool:
    store = get_agenda_store()
    ok = store.remove(event_id)
    get_scheduler().remove(event_id)  # job 不存在时 remove 返回 False，无碍
    return ok


def complete_event(event_id: str) -> dict | None:
    """手动标记完成：终态，取消后续提醒（重复日程也停止）。"""
    store = get_agenda_store()
    ev = store.set_status(event_id, "done")
    if ev:
        get_scheduler().remove(event_id)
    return ev


def next_run_of(event_id: str) -> str | None:
    try:
        job = get_scheduler()._scheduler.get_job(event_id)
        return str(job.next_run_time) if job and job.next_run_time else None
    except Exception:
        return None


# ── 触发回调 ─────────────────────────────────────────────


def fire_agenda_event(event_id: str) -> None:
    """日程到点回调（APScheduler 工作线程）。只发通知 + 更新状态，不跑 agent。"""
    store = get_agenda_store()
    ev = store.get(event_id)
    if not ev or ev["status"] != "pending":
        return  # 已删除/已完成/已提醒过（防御：正常情况下 job 已随状态移除）
    if ev["repeat"] == "none":
        store.set_status(event_id, "fired")
    _dispatch_notification(ev)


def _dispatch_notification(ev: dict) -> None:
    """把提醒派发到所有通知通道（当前：桌面端 WS；未来：app push 等）。"""
    import asyncio

    from ethan.tools.builtin.schedule import get_server_loop

    async def _send() -> None:
        from ethan.desktop.hub import get_desktop_hub
        hub = get_desktop_hub()
        sent = await hub.notify("notification", {
            "title": "日程提醒",
            "body": ev["title"],
        })
        if sent == 0:
            logger.warning("[Agenda] 日程 '%s' 触发但无桌面端在线，通知未送达", ev["title"])
        # 让打开着的日程页自动刷新（fired 状态/今日列表）
        await hub.notify("agenda_changed", {"event_id": ev["id"]})

    loop = get_server_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(_send(), loop)
    else:
        logger.info("[Agenda] no server loop, notification for '%s' skipped", ev["title"])


# ── 对账（准确性兜底） ────────────────────────────────────


def reconcile() -> dict:
    """启动/重载时对账 store ↔ scheduler：
    - 一次性日程过期未触发（服务宕机期间到期）→ 标 missed + 补发错过通知；
    - pending 事件缺 job（scheduler.db 损坏/回滚）→ 补注册；
    - scheduler 里的孤儿 agenda job（store 已删）→ 移除。

    missed 判定以 store 的 when 为准（用户意图的权威数据源），不依赖
    jobstore 状态：APScheduler 恢复 misfire job 是异步的，若此处依赖
    get_job() 判存，可能在它移除超宽限 job 之前误判「job 还在」而跳过，
    导致事件永远停在 pending。
    """
    store = get_agenda_store()
    scheduler = get_scheduler()
    now = _now()
    stats = {"missed": 0, "restored": 0, "orphans_removed": 0}

    for ev in store.list_events():
        if ev["status"] != "pending":
            continue
        try:
            dt = _parse_when(ev["when"])
        except ValueError:
            logger.warning("[Agenda] reconcile: invalid when %r, marking missed", ev["when"])
            store.set_status(ev["id"], "missed")
            stats["missed"] += 1
            continue
        if ev["repeat"] == "none" and dt < now - timedelta(seconds=MISFIRE_GRACE_SECONDS):
            # 超宽限的一次性日程：无论 job 是否残留（APScheduler 可能
            # 尚未清理 misfire job），统一标 missed + 摘 job + 补发通知
            store.set_status(ev["id"], "missed")
            scheduler.remove(ev["id"])
            stats["missed"] += 1
            logger.info("[Agenda] event '%s' missed (was due %s)", ev["title"], ev["when"])
            _dispatch_notification({**ev, "title": f"【已错过】{ev['title']}（{ev['when']}）"})
            continue
        if scheduler._scheduler.get_job(ev["id"]) is not None:
            continue
        try:
            _register_job(ev)
            stats["restored"] += 1
        except Exception:
            logger.exception("[Agenda] reconcile: failed to re-register %s", ev["id"])

    # 孤儿 job 清理
    known_ids = {e["id"] for e in store.list_events()}
    for job in scheduler._scheduler.get_jobs():
        if job.id.startswith(AGENDA_JOB_PREFIX) and job.id not in known_ids:
            scheduler.remove(job.id)
            stats["orphans_removed"] += 1
    if any(stats.values()):
        logger.info("[Agenda] reconcile: %s", stats)
    return stats
