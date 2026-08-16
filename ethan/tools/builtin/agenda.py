"""Agenda Tools — 让 agent 通过 tool call 管理日程（到点桌面通知，区别于定时任务）。

仅在 config tools.agenda.enabled=true 时注册（见 agent_factory），默认不启用，
由日程页面的开关控制——类似插件机制，但属于内置的特殊插件。
同进程直接操作 AgendaStore，不走 HTTP。
"""
from __future__ import annotations

from typing import Any

from ethan.tools.base import BaseTool

_WHEN_DESC = (
    "Trigger time in local timezone, format 'YYYY-MM-DD HH:MM'. "
    "Resolve relative expressions (e.g. '明天下午3点' / 'tomorrow 9am') to this format yourself."
)
_REPEAT_DESC = (
    "'none' (one-time, default), 'daily' (every day at the given HH:MM), "
    "'weekly' (on selected weekdays, requires weekdays param)."
)
_WEEKDAYS_DESC = "ISO weekdays 1=Monday … 7=Sunday. Required when repeat='weekly'."


def _fmt(ev: dict) -> str:
    line = f"- {ev['id']}: {ev['title']} · {ev['when']}"
    if ev["repeat"] == "daily":
        line += " (每天)"
    elif ev["repeat"] == "weekly":
        names = ["一", "二", "三", "四", "五", "六", "日"]
        days = ",".join(names[d - 1] for d in ev.get("weekdays", []))
        line += f" (每周{days})"
    line += f" [{ev['status']}]"
    if ev.get("note"):
        line += f" — {ev['note']}"
    return line


class AgendaAddTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "agenda_add"
    description = (
        "Add an agenda event: a lightweight day-schedule reminder that fires a desktop "
        "notification at the given time (NOT a scheduled agent task — no LLM runs). "
        "Use for '几点做什么' style reminders. For tasks that need the agent to actually "
        "do something on schedule, use schedule_create instead."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short event title, e.g. '和 PM 对齐排期'."},
            "when": {"type": "string", "description": _WHEN_DESC},
            "repeat": {"type": "string", "description": _REPEAT_DESC},
            "weekdays": {"type": "array", "items": {"type": "integer"}, "description": _WEEKDAYS_DESC},
            "note": {"type": "string", "description": "Optional note shown in the agenda UI."},
        },
        "required": ["title", "when"],
    }

    async def run(self, **kwargs) -> str:
        from ethan.scheduler.agenda import AgendaError, create_event
        try:
            ev = create_event(
                kwargs.get("title", ""),
                kwargs.get("when", ""),
                kwargs.get("repeat", "none") or "none",
                kwargs.get("weekdays") or [],
                kwargs.get("note", ""),
            )
        except AgendaError as e:
            return f"Error: {e}"
        return f"日程已添加：{_fmt(ev)}"


class AgendaUpdateTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "agenda_update"
    description = (
        "Update an existing agenda event (title/time/repeat/note). "
        "Changing time or repeat re-arms the reminder; a finished/missed event "
        "becomes pending again when its time changes."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "Event id from agenda_list (e.g. 'agenda:1a2b3c4d')."},
            "title": {"type": "string", "description": "New title (optional)."},
            "when": {"type": "string", "description": _WHEN_DESC},
            "repeat": {"type": "string", "description": _REPEAT_DESC},
            "weekdays": {"type": "array", "items": {"type": "integer"}, "description": _WEEKDAYS_DESC},
            "note": {"type": "string", "description": "New note (optional)."},
        },
        "required": ["event_id"],
    }

    async def run(self, **kwargs) -> str:
        from ethan.scheduler.agenda import AgendaError, update_event
        try:
            ev = update_event(
                kwargs.get("event_id", ""),
                kwargs.get("title"),
                kwargs.get("when"),
                kwargs.get("repeat"),
                kwargs.get("weekdays"),
                kwargs.get("note"),
            )
        except AgendaError as e:
            return f"Error: {e}"
        return f"日程已更新：{_fmt(ev)}"


class AgendaRemoveTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "agenda_remove"
    description = "Remove an agenda event by id (deletes it and cancels future reminders)."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "Event id from agenda_list."},
        },
        "required": ["event_id"],
    }

    async def run(self, **kwargs) -> str:
        from ethan.scheduler.agenda import remove_event
        if not remove_event(kwargs.get("event_id", "")):
            return "Error: agenda event not found"
        return "日程已删除"


class AgendaListTool(BaseTool):
    fast_path = False
    name = "agenda_list"
    description = (
        "List agenda events (day-schedule reminders). Default: pending events from today "
        "onwards. Set include_completed=true to also show fired/missed/done ones."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "include_completed": {"type": "boolean", "description": "Also include fired/missed/done events."},
        },
        "required": [],
    }

    async def run(self, **kwargs) -> str:
        from datetime import date

        from ethan.scheduler.agenda import get_agenda_store
        events = get_agenda_store().list_events()
        include_completed = bool(kwargs.get("include_completed"))
        today = date.today().isoformat()
        visible = []
        for ev in sorted(events, key=lambda e: e["when"]):
            if ev["status"] == "pending" or include_completed:
                visible.append(ev)
            elif ev["status"] in ("fired", "missed", "done") and ev["when"] >= today:
                visible.append(ev)  # 今天已结束的也展示，方便回顾
        if not visible:
            return "当前没有日程。"
        return "\n".join(_fmt(ev) for ev in visible)
