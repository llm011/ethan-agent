"""agenda 路由：日程 CRUD + Agent 日程工具开关。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agenda")


def _agenda_enabled() -> bool:
    from ethan.core.config import get_config
    return get_config().tools.agenda.enabled


@router.get("", dependencies=[Depends(verify_token)])
async def list_agenda():
    from ethan.scheduler.agenda import get_agenda_store, next_run_of
    events = get_agenda_store().list_events()
    for ev in events:
        ev["next_run_time"] = next_run_of(ev["id"]) if ev["status"] == "pending" else None
    return {"enabled": _agenda_enabled(), "events": events}


class AgendaCreateRequest(BaseModel):
    title: str
    when: str  # 'YYYY-MM-DD HH:MM'（本地时区）；repeat=daily/weekly 时取其时分，日期为起始日
    repeat: str = "none"  # none / daily / weekly
    weekdays: list[int] = []  # ISO：1=周一 … 7=周日（仅 weekly）
    note: str = ""


@router.post("", dependencies=[Depends(verify_token)])
async def create_agenda(req: AgendaCreateRequest):
    from ethan.scheduler.agenda import AgendaError, create_event
    try:
        ev = create_event(req.title, req.when, req.repeat, req.weekdays, req.note)
    except AgendaError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "event": ev}


class AgendaPatchRequest(BaseModel):
    title: str | None = None
    when: str | None = None
    repeat: str | None = None
    weekdays: list[int] | None = None
    note: str | None = None


@router.patch("/{event_id}", dependencies=[Depends(verify_token)])
async def patch_agenda(event_id: str, req: AgendaPatchRequest):
    from ethan.scheduler.agenda import AgendaError, update_event
    try:
        ev = update_event(event_id, req.title, req.when, req.repeat, req.weekdays, req.note)
    except AgendaError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "event": ev}


@router.post("/{event_id}/complete", dependencies=[Depends(verify_token)])
async def complete_agenda(event_id: str):
    from ethan.scheduler.agenda import complete_event
    ev = complete_event(event_id)
    if not ev:
        raise HTTPException(404, "Agenda event not found")
    return {"ok": True, "event": ev}


@router.delete("/{event_id}", dependencies=[Depends(verify_token)])
async def delete_agenda(event_id: str):
    from ethan.scheduler.agenda import remove_event
    if not remove_event(event_id):
        raise HTTPException(404, "Agenda event not found")
    return {"ok": True}


class AgendaEnabledRequest(BaseModel):
    enabled: bool


@router.put("/enabled", dependencies=[Depends(verify_token)])
async def set_agenda_enabled(req: AgendaEnabledRequest):
    """Agent 日程工具开关（特殊插件：开启后 agenda_* 工具注册进提示词）。"""
    from ethan.core.config import get_config, reload_config, save_config
    config = get_config()
    config.tools.agenda.enabled = req.enabled
    save_config(config)
    reload_config()
    return {"ok": True, "enabled": req.enabled}
