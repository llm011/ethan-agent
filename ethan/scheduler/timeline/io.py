"""时间线导入/导出/校验，以及 UI 状态聚合。

get_timeline_status 供 UI 展示；export/import/validate 处理配置的持久化搬运
与规范校验。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from .domain import (
    _OFFSET_RE,
    TimelineStatus,
    _next_phase,
    apply_offset,
    determine_current_phase,
    expand_actions,
    resolve_anchors,
)
from .repository import (
    _discover_scenes,
    _exports_dir,
    _timelines_file,
    get_timelines,
    load_state,
    save_state,
)
from .service import sync_scheduler

logger = logging.getLogger(__name__)


def get_timeline_status(today: Optional[date] = None) -> list[TimelineStatus]:
    """返回所有 scene 的时间线当前状态（用于 UI 展示）。"""
    today = today or date.today()
    statuses: list[TimelineStatus] = []
    for scene in _discover_scenes():
        for tl in get_timelines(scene):
            cycle = resolve_anchors(tl, today)
            current = determine_current_phase(tl, cycle.anchor_date, today)
            next_p = _next_phase(tl, cycle.anchor_date, today)

            tasks: list[dict] = []
            for task in expand_actions(tl, cycle.anchor_date, scene):
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
                scene=scene,
                anchor_date=cycle.anchor_date.isoformat(),
                current_phase=current.get("name") if current else None,
                phase_start=apply_offset(cycle.anchor_date, current.get("offset_start", "0d")).isoformat() if current else None,
                phase_end=apply_offset(cycle.anchor_date, current.get("offset_end", "0d")).isoformat() if current else None,
                next_phase=next_p.get("name") if next_p else None,
                next_anchor=cycle.next_anchor.isoformat(),
                tasks=tasks,
            ))
    return statuses


# ── 导出 & 导入 ────────────────────────────────────────────────────────────

def export_timelines(format: str = "yaml", dest: Optional[Path] = None, scene: str = "work") -> Path:
    """导出某 scene 的 timelines.yaml + .timeline_state.json 为单一文件。

    默认写到 ~/.ethan/{scene}/exports/timelines-{YYYY-MM-DD}.{ext}
    """
    exports = _exports_dir(scene)
    exports.mkdir(parents=True, exist_ok=True)
    today_str = date.today().isoformat()
    ext = "yaml" if format == "yaml" else "json"
    dest = dest or exports / f"timelines-{today_str}.{ext}"

    config_data = {}
    tf = _timelines_file(scene)
    if tf.exists():
        config_data = yaml.safe_load(tf.read_text(encoding="utf-8")) or {}

    state_data = load_state(scene)
    package = {
        "version": "1.0",
        "scene": scene,
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
    scene: Optional[str] = None,
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
      - scene：目标 scene；为 None 时取导出文件中的 scene 字段，缺省 "work"

    返回 {
      ok, error?, validation,
      timelines_count, state_restored, backup_path,
      mode, dry_run, scene, merged_from_existing?,
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

    # scene 优先级：参数 > 导出文件内 scene 字段 > "work"
    target_scene = scene or package.get("scene") or "work"
    timelines_file = _timelines_file(target_scene)

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
    if mode == "merge" and timelines_file.exists():
        try:
            existing_data = yaml.safe_load(timelines_file.read_text(encoding="utf-8")) or {}
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
            "scene": target_scene,
            "timelines_count": timelines_count,
            "merged_from_existing": merged_from_existing,
            "state_restored": restore_state,
        }

    # 备份当前配置（带时间戳，避免多次导入互相覆盖）
    backup_path: Optional[Path] = None
    if timelines_file.exists():
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        backup_path = timelines_file.with_name(f"timelines.yaml.bak.{ts}")
        backup_path.write_bytes(timelines_file.read_bytes())

    timelines_file.parent.mkdir(parents=True, exist_ok=True)
    final_data = dict(config_data)
    final_data["timelines"] = final_timelines
    timelines_file.write_text(
        yaml.safe_dump(final_data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    state_restored = False
    if restore_state:
        save_state(state_data, target_scene)
        state_restored = True
    elif mode == "merge":
        # merge 模式：保留现有 state，只重置新导入条目的 current_anchor 以便重新编译
        existing_state = load_state(target_scene)
        for tl in new_timelines:
            tl_id = tl.get("id", "") if isinstance(tl, dict) else ""
            if tl_id and tl_id in existing_state:
                existing_state[tl_id]["current_anchor"] = ""
        save_state(existing_state, target_scene)
    else:
        # overwrite 模式：清空 state 重新开始（仅保留导入文件中的 state）
        if state_data:
            save_state(state_data, target_scene)
            state_restored = True
        else:
            save_state({}, target_scene)

    # 可选：同步到 scheduler
    sync_result = None
    if sync_after:
        try:
            from ethan.scheduler.cron import get_scheduler
            scheduler = get_scheduler()
            sync_result = sync_scheduler(scheduler)
        except Exception as e:
            logger.warning("sync_after failed: %s", e, exc_info=True)
            sync_result = {"error": str(e)}

    return {
        "ok": True,
        "validation": validation,
        "mode": mode,
        "scene": target_scene,
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
