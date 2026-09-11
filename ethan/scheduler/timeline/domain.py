"""时间线领域计算 — 纯函数与数据模型，零 I/O。

包含 offset 解析、锚点/阶段计算、动作展开，以及三个数据模型
（ResolvedCycle / ExpandedTask / TimelineStatus）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

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
    """计算下一个周期的锚点日期。

    使用 add_months 统一处理月末 clamp，避免闰年 2 月 29 日 +1 年
    构造 date(year+1, 2, 29) 引发 ValueError。
    """
    recurrence = schedule.get("recurrence", "yearly")
    if recurrence == "yearly":
        return add_months(current, 12)
    if recurrence == "semi_annual":
        return add_months(current, 6)
    if recurrence == "quarterly":
        return add_months(current, 3)
    if recurrence == "monthly":
        return add_months(current, 1)
    return add_months(current, 12)


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

def _action_job_id(timeline_id: str, phase_name: str, action_type: str, idx: int, anchor: date, scene: str = "") -> str:
    """生成 scheduler job 唯一 ID。

    格式: timeline_{scene}_{timeline_id}_{phase_name}_{action_type}_{idx}_{anchor}
    """
    safe_phase = re.sub(r"[^\w\u4e00-\u9fff]+", "_", phase_name).strip("_")
    prefix = f"timeline_{scene}_" if scene else "timeline_"
    return f"{prefix}{timeline_id}_{safe_phase}_{action_type}_{idx}_{anchor.isoformat()}"


def expand_actions(timeline: dict, anchor_date: date, scene: str = "") -> list[ExpandedTask]:
    """Step 3: 展开所有 phase 的 actions 为具体任务描述。

    scene 参数优先（以文件所属目录为准）；为空时回退到 timeline 内的 scene 字段。
    """
    tasks: list[ExpandedTask] = []
    timeline_id = timeline.get("id", "")
    tl_scene = scene or timeline.get("scene", "work")

    for phase in timeline.get("phases", []):
        phase_name = phase.get("name", "")
        phase_start = apply_offset(anchor_date, phase.get("offset_start", "0d"))
        phase_end = apply_offset(anchor_date, phase.get("offset_end", "0d"))

        for idx, action in enumerate(phase.get("actions", []), start=1):
            action_type = action.get("type", "once")
            message = action.get("message", "")
            target = action.get("target", "self")
            job_id = _action_job_id(timeline_id, phase_name, action_type, idx, anchor_date, tl_scene)

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
                    scene=tl_scene,
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
                    scene=tl_scene,
                ))
    return tasks
