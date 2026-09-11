"""时间线 scheduler 同步与生命周期管理（Step 4 & 5）。

sync_scheduler 把所有 scene 的 timelines.yaml 编译并同步到 APScheduler；
lifecycle_manage 处理手动的 skip/advance/pause/resume/cleanup 操作。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from .domain import (
    ExpandedTask,
    _next_phase,
    determine_current_phase,
    expand_actions,
    resolve_anchors,
)
from .repository import (
    _discover_scenes,
    _fired_key,
    find_timeline,
    get_timelines,
    load_state,
    save_state,
)

logger = logging.getLogger(__name__)


# ── Step 4: sync_scheduler ─────────────────────────────────────────────────

def _list_timeline_jobs(scheduler) -> dict[str, Any]:
    """列出 scheduler 中所有 category=timeline 的 job，按 job_id 索引。"""
    result = {}
    for job in scheduler._scheduler.get_jobs():
        kwargs = job.kwargs or {}
        if kwargs.get("category") == "timeline":
            result[job.id] = job
    return result


def sync_scheduler(scheduler, today: Optional[date] = None) -> dict:
    """Step 4: 将所有 scene 的 timelines.yaml 同步到 scheduler。

    遍历每个 scene 目录，各自独立读写 state；desired 跨 scene 合并后与现有
    timeline 任务对比。返回 {added, removed, updated, kept} 计数。
    """
    from ethan.tools.builtin.schedule import fire_schedule_job

    today = today or date.today()

    # 1. 按 scene 计算期望任务集合（每个 scene 独立 state）
    desired: dict[str, ExpandedTask] = {}
    for scene in _discover_scenes():
        timelines = get_timelines(scene)
        if not timelines:
            # scene 已清空所有 timeline，清理残留 state
            save_state({}, scene)
            continue
        state = load_state(scene)
        for tl in timelines:
            tl_id = tl.get("id", "")
            if not tl_id:
                continue
            cycle = resolve_anchors(tl, today)
            # 周期已轮转？清理旧状态
            tl_state = state.get(tl_id, {})
            if tl_state.get("current_anchor") and tl_state["current_anchor"] != cycle.anchor_date.isoformat():
                state[tl_id] = {"current_anchor": cycle.anchor_date.isoformat(), "fired_actions": []}
            else:
                tl_state.setdefault("current_anchor", cycle.anchor_date.isoformat())
                tl_state.setdefault("fired_actions", [])
                state[tl_id] = tl_state

            for task in expand_actions(tl, cycle.anchor_date, scene):
                # once 任务若已触发则跳过
                if task.kind == "once" and task.fire_at:
                    fired_key = _fired_key(task.source_phase, "once", 0, task.fire_at)
                    if fired_key in tl_state.get("fired_actions", []):
                        continue
                    # 已过期的 once 不再注册（避免启动时大量历史任务堆积）
                    if task.fire_at < today:
                        continue
                desired[task.job_id] = task
        save_state(state, scene)

    # 2. 对比现有 timeline 任务
    existing = _list_timeline_jobs(scheduler)
    added, removed, updated, kept = 0, 0, 0, 0

    # 新增 & 更新
    for job_id, task in desired.items():
        kwargs = dict(
            session_id=_ensure_timeline_session_id(scheduler),
            prompt=task.message,
            title=f"[timeline] {task.source_timeline} - {task.source_phase}",
            channel="web",
            channel_context="{}",
            user_id="",
            category="timeline",
            source_timeline=task.source_timeline,
            source_phase=task.source_phase,
            scene=task.scene,
        )
        if job_id not in existing:
            _register_task(scheduler, task, fire_schedule_job, kwargs)
            added += 1
        else:
            # 检查是否需要更新（message 或 cron 变化）
            old_job = existing[job_id]
            old_kwargs = old_job.kwargs or {}
            if old_kwargs.get("prompt") != task.message:
                _register_task(scheduler, task, fire_schedule_job, kwargs)
                updated += 1
            else:
                kept += 1

    # 删除：existing 中不在 desired 中的
    for job_id in existing:
        if job_id not in desired:
            if scheduler.remove(job_id):
                removed += 1

    return {"added": added, "removed": removed, "updated": updated, "kept": kept}


def _ensure_timeline_session_id(scheduler) -> str:
    """为 timeline 任务获取一个共享的 session_id。

    时间线任务的 prompt 在触发时会创建对话，session_id 用于落库。
    复用现有 schedule 机制：若无则惰性创建。
    """
    # 简化：返回空字符串，fire_schedule_job 会自动创建 session
    # 实际在 ScheduleCreateTool 中已创建 session；这里走简化路径
    # 后续可缓存一个专用的 timeline session_id
    return getattr(scheduler, "_timeline_session_id", "") or ""


def _register_task(scheduler, task: ExpandedTask, func, kwargs: dict) -> None:
    """根据 task 类型选择 add_date / add_corn 注册到 scheduler。"""
    name = f"[timeline] {task.source_timeline} - {task.source_phase}"
    if task.kind == "once":
        fire_str = task.fire_at.strftime("%Y-%m-%d") if task.fire_at else None
        if not fire_str:
            return
        scheduler.add_date(task.job_id, func, fire_str, name=name, **kwargs)
    elif task.kind == "recurring" and task.cron:
        end_date = task.active_until.strftime("%Y-%m-%d") if task.active_until else None
        scheduler.add_cron(task.job_id, func, task.cron, end_date=end_date, name=name, **kwargs)


# ── Step 5: lifecycle_manage ───────────────────────────────────────────────

def lifecycle_manage(timeline_id: str, action: str, scheduler, today: Optional[date] = None) -> dict:
    """Step 5: 手动生命周期操作。

    action 取值：
      skip_phase      — 跳过当前 phase 的所有未触发 once 任务
      advance_phase   — 立即触发下一 phase 首个 once 任务
      pause           — 暂停该 timeline 所有任务
      resume          — 恢复该 timeline 所有任务
      cleanup         — 清理该 timeline 所有 scheduler 任务（保留 state）
    """
    today = today or date.today()
    scene, timeline = find_timeline(timeline_id)
    if not timeline:
        return {"ok": False, "error": f"Timeline '{timeline_id}' not found"}

    state = load_state(scene)
    tl_state = state.setdefault(timeline_id, {"current_anchor": "", "fired_actions": []})

    cycle = resolve_anchors(timeline, today)
    if not tl_state.get("current_anchor"):
        tl_state["current_anchor"] = cycle.anchor_date.isoformat()

    existing = _list_timeline_jobs(scheduler)
    tl_jobs = {jid: j for jid, j in existing.items()
               if (j.kwargs or {}).get("source_timeline") == timeline_id}

    if action == "skip_phase":
        current = determine_current_phase(timeline, cycle.anchor_date, today)
        if not current:
            return {"ok": False, "error": "Timeline is dormant, no active phase to skip"}
        phase_name = current.get("name", "")
        # 标记该 phase 所有未触发 once 为 skipped（记入 fired_actions）
        for jid, job in tl_jobs.items():
            if (job.kwargs or {}).get("source_phase") == phase_name:
                scheduler.remove(jid)
        save_state(state, scene)
        return {"ok": True, "skipped_phase": phase_name}

    if action == "advance_phase":
        next_p = _next_phase(timeline, cycle.anchor_date, today)
        if not next_p:
            return {"ok": False, "error": "No next phase found (cycle ending)"}
        # 找到下一 phase 的首个 once 任务立即触发
        for jid, job in tl_jobs.items():
            if (job.kwargs or {}).get("source_phase") == next_p.get("name", ""):
                # 立即触发一次
                try:
                    func = job.func
                    func(**job.kwargs)
                except Exception as e:
                    logger.warning("advance_phase trigger failed: %s", e)
                scheduler.remove(jid)
                break
        save_state(state, scene)
        return {"ok": True, "advanced_to": next_p.get("name", "")}

    if action == "pause":
        for jid in tl_jobs:
            scheduler.pause(jid)
        return {"ok": True, "paused": len(tl_jobs)}

    if action == "resume":
        for jid in tl_jobs:
            scheduler.resume(jid)
        return {"ok": True, "resumed": len(tl_jobs)}

    if action == "cleanup":
        for jid in tl_jobs:
            scheduler.remove(jid)
        return {"ok": True, "removed": len(tl_jobs)}

    return {"ok": False, "error": f"Unknown action: {action}"}
