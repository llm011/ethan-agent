"""时间线引擎 — 将声明式 timelines.yaml 编译为具体的定时任务。

5 步流程（对应 references/timeline-engine.md 的 SOP）：
  1. resolve_anchors          — 计算本周期的锚点日期
  2. determine_current_phase  — 判断今天处于哪个阶段
  3. expand_actions           — 展开动作为 scheduler 任务描述
  4. sync_scheduler           — 同步到 APScheduler（增/删/改）
  5. lifecycle_manage         — 周期轮转 & 手动操作

设计原则：配置（timelines.yaml）描述规则；状态（.timeline_state.json）
记录已发生的事实；两者分离，配置永远有效，状态可重置可迁移。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from ethan.core.config import CONFIG_DIR

logger = logging.getLogger(__name__)

WORK_DIR = CONFIG_DIR / "work"
TIMELINES_FILE = WORK_DIR / "timelines.yaml"
STATE_FILE = WORK_DIR / ".timeline_state.json"
EXPORTS_DIR = WORK_DIR / "exports"

# once 类型任务默认触发时间（HH:MM）
DEFAULT_FIRE_TIME = "10:00"

# ── offset 解析 ────────────────────────────────────────────────────────────

_OFFSET_RE = re.compile(r"^([+-]?)(\d+)([dwm])$")


def parse_offset(offset: str) -> timedelta:
    """解析 '-5m' / '+2w' / '-3d' / '0d' 为 timedelta。

    月按 30 天近似。需要精确月份加减时用 add_months。
    """
    offset = offset.strip()
    if offset == "0d":
        return timedelta(0)
    m = _OFFSET_RE.match(offset)
    if not m:
        raise ValueError(f"Invalid offset format: {offset!r} (expected like -5m / +2w / -3d)")
    sign_str, n_str, unit = m.groups()
    n = int(n_str) * (-1 if sign_str == "-" else 1)
    if unit == "d":
        return timedelta(days=n)
    if unit == "w":
        return timedelta(weeks=n)
    if unit == "m":
        return timedelta(days=n * 30)  # 近似；精确处理走 add_months
    raise ValueError(f"Unknown offset unit: {unit}")


def add_months(d: date, months: int) -> date:
    """月份加减，自动 clamp 到月末。"""
    y, m = d.year, d.month + months
    # 归一化月份
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    # clamp day
    import calendar
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def apply_offset(anchor: date, offset: str) -> date:
    """对锚点应用 offset。月单位走 add_months 保证精度，其余走 timedelta。"""
    offset = offset.strip()
    if offset == "0d":
        return anchor
    m = _OFFSET_RE.match(offset)
    if not m:
        raise ValueError(f"Invalid offset: {offset!r}")
    sign_str, n_str, unit = m.groups()
    n = int(n_str) * (-1 if sign_str == "-" else 1)
    if unit == "m":
        return add_months(anchor, n)
    return anchor + parse_offset(offset)


# ── 数据模型 ────────────────────────────────────────────────────────────────

@dataclass
class ResolvedCycle:
    """一个时间线在某一周期的解析结果。"""
    timeline_id: str
    anchor_date: date
    cycle_label: str           # 如 "2026-H2"
    next_anchor: date          # 下一个周期的锚点


@dataclass
class ExpandedTask:
    """展开后的 scheduler 任务描述。"""
    job_id: str
    kind: str                   # "once" | "recurring"
    fire_at: Optional[date]     # once: 触发日期；recurring: None
    cron: Optional[str]         # recurring: cron 表达式；once: None
    active_from: Optional[date] # recurring 的生效起始
    active_until: Optional[date]# recurring 的生效结束
    message: str
    target: str
    source_timeline: str
    source_phase: str
    scene: str = "work"


@dataclass
class TimelineStatus:
    """时间线当前状态（用于 UI 展示）。"""
    id: str
    name: str
    scene: str
    anchor_date: str
    current_phase: Optional[str]   # None = 休眠中
    phase_start: Optional[str]
    phase_end: Optional[str]
    next_phase: Optional[str]
    next_anchor: str
    tasks: list[dict] = field(default_factory=list)


# ── Step 1: resolve_anchors ────────────────────────────────────────────────

def _resolve_anchor_date(schedule: dict, today: date) -> date:
    """从 schedule.anchor 计算本周期的锚点日期。

    支持单锚点（"07-01"）和多锚点（["01-01", "04-01", "07-01", "10-01"]）。
    选择距 today 最近且后续 phases 尚未完全过去的那个。
    """
    anchor = schedule.get("anchor", "")
    if isinstance(anchor, list):
        candidates = anchor
    else:
        candidates = [anchor]

    # 对每个 MM-DD，构造本年的日期，若已过则用下一年的
    resolved = []
    for mmdd in candidates:
        m, d = mmdd.split("-")
        this_year = date(today.year, int(m), int(d))
        if this_year < today:
            next_year = date(today.year + 1, int(m), int(d))
            resolved.append(next_year)
        else:
            resolved.append(this_year)
    # 取最近的未来锚点
    return min(resolved, key=lambda x: abs((x - today).days))


def _cycle_label(timeline_id: str, anchor: date, recurrence: str) -> str:
    """生成本周期的展示标签。"""
    if recurrence == "yearly":
        return f"{anchor.year}"
    if recurrence == "semi_annual":
        h = "H1" if anchor.month <= 6 else "H2"
        return f"{anchor.year}-{h}"
    if recurrence == "quarterly":
        q = (anchor.month - 1) // 3 + 1
        return f"{anchor.year}-Q{q}"
    if recurrence == "monthly":
        return f"{anchor.year}-{anchor.month:02d}"
    return f"{anchor.year}"


def _next_anchor_date(schedule: dict, current: date) -> date:
    """计算下一个周期的锚点日期。"""
    recurrence = schedule.get("recurrence", "yearly")
    if recurrence == "yearly":
        return date(current.year + 1, current.month, current.day)
    if recurrence == "semi_annual":
        return add_months(current, 6)
    if recurrence == "quarterly":
        return add_months(current, 3)
    if recurrence == "monthly":
        return add_months(current, 1)
    return date(current.year + 1, current.month, current.day)


def resolve_anchors(timeline: dict, today: date) -> ResolvedCycle:
    """Step 1: 解析本周期的锚点。"""
    schedule = timeline.get("schedule", {})
    anchor_date = _resolve_anchor_date(schedule, today)
    recurrence = schedule.get("recurrence", "yearly")
    next_anchor = _next_anchor_date(schedule, anchor_date)
    label = _cycle_label(timeline.get("id", ""), anchor_date, recurrence)
    return ResolvedCycle(
        timeline_id=timeline.get("id", ""),
        anchor_date=anchor_date,
        cycle_label=label,
        next_anchor=next_anchor,
    )


# ── Step 2: determine_current_phase ────────────────────────────────────────

def determine_current_phase(timeline: dict, anchor_date: date, today: date) -> Optional[dict]:
    """Step 2: 判断 today 处于哪个 phase。None = 休眠中。"""
    phases = timeline.get("phases", [])
    for phase in phases:
        start = apply_offset(anchor_date, phase.get("offset_start", "0d"))
        end = apply_offset(anchor_date, phase.get("offset_end", "0d"))
        if start <= today <= end:
            return phase
    return None


def _next_phase(timeline: dict, anchor_date: date, today: date) -> Optional[dict]:
    """返回 today 之后的下一个 phase。"""
    phases = timeline.get("phases", [])
    for phase in phases:
        start = apply_offset(anchor_date, phase.get("offset_start", "0d"))
        if start > today:
            return phase
    return None


# ── Step 3: expand_actions ─────────────────────────────────────────────────

def _action_job_id(timeline_id: str, phase_name: str, action_type: str, idx: int, anchor: date) -> str:
    """生成 scheduler job 唯一 ID。

    格式: timeline_{timeline_id}_{phase_name}_{action_type}_{idx}_{anchor}
    """
    safe_phase = re.sub(r"[^\w\u4e00-\u9fff]+", "_", phase_name).strip("_")
    return f"timeline_{timeline_id}_{safe_phase}_{action_type}_{idx}_{anchor.isoformat()}"


def expand_actions(timeline: dict, anchor_date: date) -> list[ExpandedTask]:
    """Step 3: 展开所有 phase 的 actions 为具体任务描述。"""
    tasks: list[ExpandedTask] = []
    timeline_id = timeline.get("id", "")
    scene = timeline.get("scene", "work")

    for phase in timeline.get("phases", []):
        phase_name = phase.get("name", "")
        phase_start = apply_offset(anchor_date, phase.get("offset_start", "0d"))
        phase_end = apply_offset(anchor_date, phase.get("offset_end", "0d"))

        for idx, action in enumerate(phase.get("actions", []), start=1):
            action_type = action.get("type", "once")
            message = action.get("message", "")
            target = action.get("target", "self")
            job_id = _action_job_id(timeline_id, phase_name, action_type, idx, anchor_date)

            if action_type == "once":
                offset = action.get("offset", "0d")
                fire_at = apply_offset(anchor_date, offset)
                tasks.append(ExpandedTask(
                    job_id=job_id,
                    kind="once",
                    fire_at=fire_at,
                    cron=None,
                    active_from=None,
                    active_until=None,
                    message=message,
                    target=target,
                    source_timeline=timeline_id,
                    source_phase=phase_name,
                    scene=scene,
                ))
            elif action_type == "recurring":
                cron = action.get("cron", "")
                tasks.append(ExpandedTask(
                    job_id=job_id,
                    kind="recurring",
                    fire_at=None,
                    cron=cron,
                    active_from=phase_start,
                    active_until=phase_end,
                    message=message,
                    target=target,
                    source_timeline=timeline_id,
                    source_phase=phase_name,
                    scene=scene,
                ))
    return tasks


# ── State persistence ──────────────────────────────────────────────────────

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _fired_key(phase_name: str, action_type: str, idx: int, fire_at: date) -> str:
    return f"{phase_name}_{action_type}_{idx}_{fire_at.isoformat()}"


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
    """Step 4: 将 timelines.yaml 同步到 scheduler。

    返回 {added, removed, updated, kept} 计数。
    """
    from ethan.tools.builtin.schedule import fire_schedule_job

    today = today or date.today()
    timelines = get_timelines()
    state = load_state()

    # 1. 计算期望的任务集合
    desired: dict[str, ExpandedTask] = {}
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

        for task in expand_actions(tl, cycle.anchor_date):
            # once 任务若已触发则跳过
            if task.kind == "once" and task.fire_at:
                fired_key = _fired_key(task.source_phase, "once", 0, task.fire_at)
                # 通过 job_id 也能查；这里以 state 为准
                if fired_key in tl_state.get("fired_actions", []):
                    continue
                # 已过期的 once 不再注册（避免启动时大量历史任务堆积）
                if task.fire_at < today:
                    continue
            desired[task.job_id] = task

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

    save_state(state)
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
    timelines = get_timelines()
    timeline = next((t for t in timelines if t.get("id") == timeline_id), None)
    if not timeline:
        return {"ok": False, "error": f"Timeline '{timeline_id}' not found"}

    state = load_state()
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
        save_state(state)
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
        save_state(state)
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


# ── Public API ─────────────────────────────────────────────────────────────

def get_timelines() -> list[dict]:
    """读取 timelines.yaml 中的 timelines 列表。"""
    if not TIMELINES_FILE.exists():
        return []
    try:
        data = yaml.safe_load(TIMELINES_FILE.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return data.get("timelines", []) or []


def save_timelines(timelines: list[dict]) -> None:
    """写回 timelines.yaml。保留 task_categories 等其他字段。"""
    data = {}
    if TIMELINES_FILE.exists():
        try:
            data = yaml.safe_load(TIMELINES_FILE.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
    data["timelines"] = timelines
    TIMELINES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMELINES_FILE.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def get_timeline_status(today: Optional[date] = None) -> list[TimelineStatus]:
    """返回所有时间线的当前状态（用于 UI 展示）。"""
    today = today or date.today()
    statuses: list[TimelineStatus] = []
    for tl in get_timelines():
        cycle = resolve_anchors(tl, today)
        current = determine_current_phase(tl, cycle.anchor_date, today)
        next_p = _next_phase(tl, cycle.anchor_date, today)

        tasks: list[dict] = []
        for task in expand_actions(tl, cycle.anchor_date):
            tasks.append({
                "job_id": task.job_id,
                "kind": task.kind,
                "fire_at": task.fire_at.isoformat() if task.fire_at else None,
                "cron": task.cron,
                "active_from": task.active_from.isoformat() if task.active_from else None,
                "active_until": task.active_until.isoformat() if task.active_until else None,
                "message": task.message,
                "source_phase": task.source_phase,
                "passed": (task.fire_at < today) if task.fire_at else None,
            })

        statuses.append(TimelineStatus(
            id=tl.get("id", ""),
            name=tl.get("name", ""),
            scene=tl.get("scene", "work"),
            anchor_date=cycle.anchor_date.isoformat(),
            current_phase=current.get("name") if current else None,
            phase_start=apply_offset(cycle.anchor_date, current.get("offset_start", "0d")).isoformat() if current else None,
            phase_end=apply_offset(cycle.anchor_date, current.get("offset_end", "0d")).isoformat() if current else None,
            next_phase=next_p.get("name") if next_p else None,
            next_anchor=cycle.next_anchor.isoformat(),
            tasks=tasks,
        ))
    return statuses


def find_timeline(timeline_id: str) -> Optional[dict]:
    for tl in get_timelines():
        if tl.get("id") == timeline_id:
            return tl
    return None


def upsert_timeline(timeline: dict) -> None:
    """新增或更新（按 id 匹配）一条时间线，并写回。"""
    timelines = get_timelines()
    tl_id = timeline.get("id", "")
    found = False
    for i, t in enumerate(timelines):
        if t.get("id") == tl_id:
            timelines[i] = timeline
            found = True
            break
    if not found:
        timelines.append(timeline)
    save_timelines(timelines)


def remove_timeline(timeline_id: str) -> bool:
    timelines = get_timelines()
    new_list = [t for t in timelines if t.get("id") != timeline_id]
    if len(new_list) == len(timelines):
        return False
    save_timelines(new_list)
    # 同时清理 state
    state = load_state()
    state.pop(timeline_id, None)
    save_state(state)
    return True


# ── 导出 & 导入 ────────────────────────────────────────────────────────────

def export_timelines(format: str = "yaml", dest: Optional[Path] = None) -> Path:
    """导出 timelines.yaml + .timeline_state.json 为单一文件。

    默认写到 ~/.ethan/work/exports/timelines-{YYYY-MM-DD}.{ext}
    """
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today_str = date.today().isoformat()
    ext = "yaml" if format == "yaml" else "json"
    dest = dest or EXPORTS_DIR / f"timelines-{today_str}.{ext}"

    config_data = {}
    if TIMELINES_FILE.exists():
        config_data = yaml.safe_load(TIMELINES_FILE.read_text(encoding="utf-8")) or {}

    state_data = load_state()
    package = {
        "version": "1.0",
        "exported_at": datetime.now().astimezone().isoformat(),
        "config": config_data,
        "state": state_data,
    }

    if format == "yaml":
        dest.write_text(
            yaml.safe_dump(package, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    else:
        dest.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest


def import_timelines(
    path: Path,
    restore_state: bool = False,
    dry_run: bool = False,
    mode: str = "overwrite",
    sync_after: bool = False,
) -> dict:
    """从导出文件恢复时间线配置。

    校验流程：
      1. 解析文件格式（YAML / JSON）
      2. 校验 version 兼容性
      3. 调用 validate_timelines_file 校验 config 内容
      4. 校验失败 → 直接返回，不修改任何文件

    写入模式：
      - overwrite（默认）：用导入的 config 完全覆盖 timelines.yaml
      - merge：按 id 合并；导入文件中的 id 覆盖现有同名条目，其他保留

    参数：
      - restore_state：是否同时恢复 .timeline_state.json
      - dry_run：True 时只返回"会发生什么"，不写入任何文件
      - mode：overwrite / merge
      - sync_after：写入后是否调用 sync_scheduler（需要 scheduler 已启动）

    返回 {
      ok, error?, validation,
      timelines_count, state_restored, backup_path,
      mode, dry_run, merged_from_existing?,
    }
    """
    if not path.exists():
        return {"ok": False, "error": f"File not found: {path}"}

    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() in (".yaml", ".yml"):
            package = yaml.safe_load(text) or {}
        else:
            package = json.loads(text)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"Parse error: {e}"}

    if not isinstance(package, dict):
        return {"ok": False, "error": "Import file must be a mapping at top level"}

    version = str(package.get("version", ""))
    if not version.startswith("1."):
        return {"ok": False, "error": f"Unsupported version: {version} (require 1.x)"}

    config_data = package.get("config", {}) or {}
    state_data = package.get("state", {}) or {}

    # 临时写入临时文件做校验（避免污染现有配置）
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tf:
        yaml.safe_dump(config_data, tf, allow_unicode=True, sort_keys=False, default_flow_style=False)
        tmp_path = Path(tf.name)
    try:
        validation = validate_timelines_file(tmp_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    if not validation["ok"]:
        return {
            "ok": False,
            "error": "Validation failed",
            "validation": validation,
        }

    # 计算合并结果
    new_timelines = config_data.get("timelines", []) or []
    existing_timelines = []
    if mode == "merge" and TIMELINES_FILE.exists():
        try:
            existing_data = yaml.safe_load(TIMELINES_FILE.read_text(encoding="utf-8")) or {}
            existing_timelines = existing_data.get("timelines", []) or []
        except yaml.YAMLError:
            existing_timelines = []

    if mode == "merge":
        # 按 id 合并：new 覆盖 existing 同 id 的条目
        new_ids = {t.get("id") for t in new_timelines if isinstance(t, dict)}
        merged = [t for t in existing_timelines if t.get("id") not in new_ids]
        merged.extend(new_timelines)
        final_timelines = merged
        merged_from_existing = len(merged) - len(new_timelines)
    else:
        final_timelines = new_timelines
        merged_from_existing = 0

    timelines_count = len(final_timelines)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "validation": validation,
            "mode": mode,
            "timelines_count": timelines_count,
            "merged_from_existing": merged_from_existing,
            "state_restored": restore_state,
        }

    # 备份当前配置（带时间戳，避免多次导入互相覆盖）
    backup_path: Optional[Path] = None
    if TIMELINES_FILE.exists():
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        backup_path = TIMELINES_FILE.with_name(f"timelines.yaml.bak.{ts}")
        backup_path.write_bytes(TIMELINES_FILE.read_bytes())

    TIMELINES_FILE.parent.mkdir(parents=True, exist_ok=True)
    final_data = dict(config_data)
    final_data["timelines"] = final_timelines
    TIMELINES_FILE.write_text(
        yaml.safe_dump(final_data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    state_restored = False
    if restore_state:
        save_state(state_data)
        state_restored = True
    elif mode == "merge":
        # merge 模式：保留现有 state，只重置新导入条目的 current_anchor 以便重新编译
        existing_state = load_state()
        for tl in new_timelines:
            tl_id = tl.get("id", "") if isinstance(tl, dict) else ""
            if tl_id and tl_id in existing_state:
                existing_state[tl_id]["current_anchor"] = ""
        save_state(existing_state)
    else:
        # overwrite 模式：清空 state 重新开始（仅保留导入文件中的 state）
        if state_data:
            save_state(state_data)
            state_restored = True
        else:
            save_state({})

    # 可选：同步到 scheduler
    sync_result = None
    if sync_after:
        try:
            from ethan.interface.routers.schedule import get_scheduler
            scheduler = get_scheduler()
            sync_result = sync_scheduler(scheduler)
        except Exception as e:
            logger.warning("sync_after failed: %s", e, exc_info=True)
            sync_result = {"error": str(e)}

    return {
        "ok": True,
        "validation": validation,
        "mode": mode,
        "timelines_count": timelines_count,
        "merged_from_existing": merged_from_existing,
        "state_restored": state_restored,
        "backup_path": str(backup_path) if backup_path else None,
        "sync_result": sync_result,
    }


def validate_timelines_file(path: Path) -> dict:
    """校验一个 timelines.yaml 是否符合规范。返回 {ok, errors, warnings, timelines_count}。

    校验项：
    - 顶层结构：必须有 timelines 数组
    - timeline.id：必填、唯一、合法字符
    - timeline.schedule.anchor：必填、MM-DD 格式、日期合法（如 02-31 报错）
    - timeline.schedule.recurrence：必须为 yearly/semi_annual/quarterly/monthly
    - timeline.phases：不能为空
    - phase.name：必填
    - phase.offset_start/offset_end：必填、合法 offset 格式、start <= end
    - phase.actions：可选，但若存在则校验每个 action
    - action.type：必须为 once / recurring
    - action.message：必填
    - once 类型：必须有 offset
    - recurring 类型：必须有 cron
    """
    if not path.exists():
        return {"ok": False, "errors": ["File not found"], "warnings": [], "timelines_count": 0}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return {"ok": False, "errors": [f"YAML parse error: {e}"], "warnings": [], "timelines_count": 0}

    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return {"ok": False, "errors": ["Top-level must be a mapping"], "warnings": [], "timelines_count": 0}

    timelines = data.get("timelines", [])
    if timelines is None:
        warnings.append("'timelines' is empty or missing")
        timelines = []
    if not isinstance(timelines, list):
        return {"ok": False, "errors": ["'timelines' must be a list"], "warnings": [], "timelines_count": 0}

    import calendar

    valid_recurrences = {"yearly", "semi_annual", "quarterly", "monthly"}
    valid_action_types = {"once", "recurring"}
    seen_ids: set[str] = set()

    def _validate_mmdd(mmdd: str, context: str) -> None:
        if not re.match(r"^\d{2}-\d{2}$", mmdd):
            errors.append(f"{context}: anchor '{mmdd}' must be MM-DD format")
            return
        m_str, d_str = mmdd.split("-")
        m, d = int(m_str), int(d_str)
        if m < 1 or m > 12:
            errors.append(f"{context}: anchor '{mmdd}' has invalid month")
            return
        last_day = calendar.monthrange(2000, m)[1]  # 闰年不影响月份最大天数判断
        if d < 1 or d > last_day:
            errors.append(f"{context}: anchor '{mmdd}' has invalid day for month {m:02d}")

    def _validate_offset(val: Any, context: str, allow_empty: bool = False) -> bool:
        if not val:
            if allow_empty:
                return True
            errors.append(f"{context}: missing offset")
            return False
        if val == "0d":
            return True
        if not isinstance(val, str) or not _OFFSET_RE.match(val):
            errors.append(f"{context}: invalid offset '{val}' (expected like -5m / +2w / -3d / 0d)")
            return False
        return True

    for i, tl in enumerate(timelines):
        if not isinstance(tl, dict):
            errors.append(f"timelines[{i}]: must be a mapping")
            continue
        prefix = f"timelines[{i}]"
        tl_id = tl.get("id", "")
        if not tl_id:
            errors.append(f"{prefix}: missing 'id'")
        elif not isinstance(tl_id, str) or not re.match(r"^[a-zA-Z0-9_-]+$", tl_id):
            errors.append(f"{prefix}: id '{tl_id}' contains invalid characters (allowed: A-Z a-z 0-9 _ -)")
        elif tl_id in seen_ids:
            errors.append(f"{prefix}: duplicate id '{tl_id}'")
        else:
            seen_ids.add(tl_id)

        # schedule
        schedule = tl.get("schedule", {})
        if not isinstance(schedule, dict):
            errors.append(f"{prefix} ({tl_id}): schedule must be a mapping")
            schedule = {}

        anchor = schedule.get("anchor")
        if not anchor:
            errors.append(f"{prefix} ({tl_id}): schedule.anchor is required")
        elif isinstance(anchor, str):
            _validate_mmdd(anchor, f"{prefix} ({tl_id})")
        elif isinstance(anchor, list):
            if len(anchor) == 0:
                errors.append(f"{prefix} ({tl_id}): schedule.anchor list is empty")
            for a in anchor:
                if not isinstance(a, str):
                    errors.append(f"{prefix} ({tl_id}): anchor item must be string, got {a!r}")
                else:
                    _validate_mmdd(a, f"{prefix} ({tl_id})")
        else:
            errors.append(f"{prefix} ({tl_id}): schedule.anchor must be string or list")

        recurrence = schedule.get("recurrence", "yearly")
        if recurrence not in valid_recurrences:
            errors.append(f"{prefix} ({tl_id}): schedule.recurrence '{recurrence}' invalid (allowed: {sorted(valid_recurrences)})")

        # name（仅警告）
        if not tl.get("name"):
            warnings.append(f"{prefix} ({tl_id}): missing 'name' (used for UI display)")

        # scene（仅警告）
        scene = tl.get("scene", "work")
        if scene not in {"work", "life", "health", "study", "finance", "social"}:
            warnings.append(f"{prefix} ({tl_id}): scene '{scene}' is not a standard value")

        # phases
        phases = tl.get("phases", []) or []
        if not isinstance(phases, list):
            errors.append(f"{prefix} ({tl_id}): phases must be a list")
            phases = []
        if len(phases) == 0:
            errors.append(f"{prefix} ({tl_id}): phases is empty (at least one phase required)")

        for j, phase in enumerate(phases):
            if not isinstance(phase, dict):
                errors.append(f"{prefix} ({tl_id}).phases[{j}]: must be a mapping")
                continue
            p_prefix = f"{prefix} ({tl_id}).phases[{j}]"
            p_name = phase.get("name", "")
            if not p_name:
                errors.append(f"{p_prefix}: missing 'name'")

            offset_start = phase.get("offset_start", "")
            offset_end = phase.get("offset_end", "")
            ok_start = _validate_offset(offset_start, f"{p_prefix}.offset_start")
            ok_end = _validate_offset(offset_end, f"{p_prefix}.offset_end")

            # 校验 offset_start <= offset_end
            if ok_start and ok_end and offset_start and offset_end:
                try:
                    # 用一个固定锚点（2000-01-01）测试 offset 排序
                    base = date(2000, 1, 1)
                    s = apply_offset(base, offset_start)
                    e = apply_offset(base, offset_end)
                    if s > e:
                        errors.append(f"{p_prefix}: offset_start ({offset_start}) > offset_end ({offset_end})")
                except ValueError as e:
                    errors.append(f"{p_prefix}: offset comparison failed: {e}")

            # actions
            actions = phase.get("actions", []) or []
            if not isinstance(actions, list):
                errors.append(f"{p_prefix}.actions: must be a list")
                actions = []
            for k, action in enumerate(actions):
                if not isinstance(action, dict):
                    errors.append(f"{p_prefix}.actions[{k}]: must be a mapping")
                    continue
                a_prefix = f"{p_prefix}.actions[{k}]"
                a_type = action.get("type", "")
                if a_type not in valid_action_types:
                    errors.append(f"{a_prefix}: invalid type '{a_type}' (allowed: {sorted(valid_action_types)})")
                    continue
                if not action.get("message"):
                    errors.append(f"{a_prefix}: missing 'message'")
                if a_type == "once":
                    if not action.get("offset"):
                        errors.append(f"{a_prefix}: once action requires 'offset'")
                    else:
                        _validate_offset(action.get("offset"), f"{a_prefix}.offset")
                elif a_type == "recurring":
                    if not action.get("cron"):
                        errors.append(f"{a_prefix}: recurring action requires 'cron'")
                    else:
                        # 简单校验 cron 字段数
                        cron_str = action.get("cron", "")
                        if isinstance(cron_str, str) and len(cron_str.split()) != 5:
                            errors.append(f"{a_prefix}: cron '{cron_str}' must have 5 fields (min hour day month weekday)")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "timelines_count": len(timelines),
    }


# ── 飞书可视化（可选）──────────────────────────────────────────────────────

def _lark_cli(args: list[str], timeout: int = 15) -> dict:
    """同步调用 lark-cli 子命令，返回解析后的 JSON 字典。

    失败时抛出 RuntimeError；调用方应 try/except 捕获。
    """
    import asyncio
    proc = asyncio.run(asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    ))
    stdout, stderr = asyncio.wait_for(proc.communicate(), timeout=timeout)
    out_text = stdout.decode(errors="replace").strip()
    err_text = stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"lark-cli exit {proc.returncode}: {err_text or out_text}")
    if not out_text:
        return {}
    try:
        return json.loads(out_text)
    except json.JSONDecodeError:
        return {"raw": out_text}


def _lark_event_id_from_response(resp: dict) -> str:
    """从 lark-cli calendar +create 的响应中提取 event_id。"""
    # 响应格式：{"code":0,"data":{"event":{"event_id":"..."}}
    data = resp.get("data", {}) or {}
    event = data.get("event", {}) or {}
    return event.get("event_id", "") or data.get("event_id", "")


def sync_to_lark(timeline_id: str, today: Optional[date] = None) -> dict:
    """将某条时间线同步到飞书日历（每个 phase 一个全天事件）。

    要求 timeline 配置中 `sync_to_lark: true`。
    已同步过且锚点未变时跳过；锚点变化时先清理旧事件再重建。

    返回 {
      ok, skipped, created_events: [event_id...], cleaned_events: [event_id...],
      error?,
    }
    """
    today = today or date.today()
    tl = find_timeline(timeline_id)
    if not tl:
        return {"ok": False, "error": f"Timeline not found: {timeline_id}"}

    if not tl.get("sync_to_lark", False):
        return {"ok": False, "error": f"Timeline '{timeline_id}' has sync_to_lark=false (or missing)"}

    cycle = resolve_anchors(tl, today)
    state = load_state()
    tl_state = state.get(timeline_id, {}) or {}

    # 检查是否已同步到当前锚点
    synced = tl_state.get("lark_sync", {}) or {}
    if synced.get("anchor") == cycle.anchor_date.isoformat() and synced.get("event_ids"):
        return {
            "ok": True,
            "skipped": True,
            "created_events": [],
            "cleaned_events": [],
            "anchor": cycle.anchor_date.isoformat(),
        }

    # 锚点变化 → 先清理旧事件
    cleaned_events: list[str] = []
    old_event_ids = synced.get("event_ids", []) or []
    for eid in old_event_ids:
        try:
            _lark_cli([
                "lark-cli", "calendar", "events", "delete",
                "--as", "user",
                "--params", json.dumps({"event_id": eid}),
            ])
            cleaned_events.append(eid)
        except Exception as e:
            logger.warning("Failed to delete old lark event %s: %s", eid, e)

    # 为每个 phase 创建全天日历事件
    timeline_name = tl.get("name", timeline_id)
    created_events: list[str] = []
    errors: list[str] = []

    for phase in tl.get("phases", []) or []:
        phase_name = phase.get("name", "")
        offset_start = phase.get("offset_start", "0d")
        offset_end = phase.get("offset_end", "0d")
        try:
            p_start = apply_offset(cycle.anchor_date, offset_start)
            p_end = apply_offset(cycle.anchor_date, offset_end)
        except ValueError as e:
            errors.append(f"phase '{phase_name}' offset invalid: {e}")
            continue

        # 全天事件：start 用日期 00:00，end 用 p_end + 1 天（飞书 end 是 exclusive）
        from datetime import datetime
        from datetime import timedelta as _td
        start_iso = datetime.combine(p_start, datetime.min.time()).isoformat()
        end_date = p_end + _td(days=1)
        end_iso = datetime.combine(end_date, datetime.min.time()).isoformat()

        # 描述：列出该 phase 的 actions 概述
        actions = phase.get("actions", []) or []
        if actions:
            action_lines = []
            for i, a in enumerate(actions, 1):
                a_type = a.get("type", "once")
                a_msg = a.get("message", "")
                if a_type == "once":
                    a_off = a.get("offset", "0d")
                    action_lines.append(f"  {i}. [once @ {a_off}] {a_msg}")
                else:
                    a_cron = a.get("cron", "")
                    action_lines.append(f"  {i}. [recurring {a_cron}] {a_msg}")
            desc = f"阶段 {phase_name} 的动作：\n" + "\n".join(action_lines)
        else:
            desc = f"阶段 {phase_name}（无具体动作）"

        summary = f"📅 [{timeline_name}] {phase_name}"

        try:
            resp = _lark_cli([
                "lark-cli", "calendar", "+create",
                "--as", "user",
                "--summary", summary,
                "--start", start_iso,
                "--end", end_iso,
                "--description", desc,
            ])
            event_id = _lark_event_id_from_response(resp)
            if event_id:
                created_events.append(event_id)
            else:
                errors.append(f"phase '{phase_name}': no event_id in response: {resp}")
        except Exception as e:
            errors.append(f"phase '{phase_name}' create failed: {e}")

    # 更新 state
    tl_state["lark_sync"] = {
        "anchor": cycle.anchor_date.isoformat(),
        "event_ids": created_events,
        "synced_at": datetime.now().astimezone().isoformat(),
    }
    state[timeline_id] = tl_state
    save_state(state)

    return {
        "ok": len(errors) == 0,
        "skipped": False,
        "created_events": created_events,
        "cleaned_events": cleaned_events,
        "anchor": cycle.anchor_date.isoformat(),
        "errors": errors,
    }


def cleanup_lark_resources(timeline_id: str) -> dict:
    """删除某条时间线在飞书日历上的所有已同步事件。

    用于：用户关闭 sync_to_lark、或手动请求清理。

    返回 {ok, cleaned_events, errors}。
    """
    state = load_state()
    tl_state = state.get(timeline_id, {}) or {}
    synced = tl_state.get("lark_sync", {}) or {}
    event_ids = synced.get("event_ids", []) or []

    cleaned: list[str] = []
    errors: list[str] = []
    for eid in event_ids:
        try:
            _lark_cli([
                "lark-cli", "calendar", "events", "delete",
                "--as", "user",
                "--params", json.dumps({"event_id": eid}),
            ])
            cleaned.append(eid)
        except Exception as e:
            errors.append(f"event {eid}: {e}")

    # 清空 state 中的 lark_sync 记录
    if "lark_sync" in tl_state:
        del tl_state["lark_sync"]
        state[timeline_id] = tl_state
        save_state(state)

    return {
        "ok": len(errors) == 0,
        "cleaned_events": cleaned,
        "errors": errors,
    }
