"""时间线 → 飞书日历可视化同步（可选功能）。

sync_to_lark 把每个 phase 映射成一个飞书全天日历事件；
cleanup_lark_resources 清理已同步的事件。均通过 lark-cli 子进程完成。
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from .domain import apply_offset, resolve_anchors
from .repository import find_timeline, load_state, save_state

logger = logging.getLogger(__name__)


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
    scene, tl = find_timeline(timeline_id)
    if not tl:
        return {"ok": False, "error": f"Timeline not found: {timeline_id}"}

    if not tl.get("sync_to_lark", False):
        return {"ok": False, "error": f"Timeline '{timeline_id}' has sync_to_lark=false (or missing)"}

    cycle = resolve_anchors(tl, today)
    state = load_state(scene)
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
    save_state(state, scene)

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
    scene, _ = find_timeline(timeline_id)
    if not scene:
        return {"ok": False, "error": f"Timeline not found: {timeline_id}"}
    state = load_state(scene)
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
        save_state(state, scene)

    return {
        "ok": len(errors) == 0,
        "cleaned_events": cleaned,
        "errors": errors,
    }
