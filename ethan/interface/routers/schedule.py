"""schedule 路由：定时任务 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import verify_token

router = APIRouter(prefix="/schedule")

_scheduler = None

def get_scheduler():
    global _scheduler
    if _scheduler is None:
        from ethan.scheduler.cron import Scheduler
        _scheduler = Scheduler()
        _scheduler.start()
    return _scheduler


@router.get("", dependencies=[Depends(verify_token)])
async def get_schedules():
    scheduler = get_scheduler()
    jobs = scheduler._scheduler.get_jobs()
    result = []
    for job in jobs:
        kwargs = job.kwargs or {}
        result.append({
            "id": job.id,
            "name": job.name or job.id,
            "trigger": str(job.trigger),
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "status": "paused" if job.next_run_time is None else "active",
            "prompt": kwargs.get("prompt", ""),
            "session_id": kwargs.get("session_id", ""),
            "channel": kwargs.get("channel", "web"),
        })
    return {"jobs": result}


class ScheduleCreateRequest(BaseModel):
    job_id: str
    prompt: str
    cron: str = ""
    interval_minutes: int = 0
    session_id: str
    channel: str = "web"
    channel_context: str = "{}"
    user_id: str = ""


@router.post("")
async def create_schedule(req: ScheduleCreateRequest, user_id: str = Depends(verify_token)):
    scheduler = get_scheduler()
    from ethan.tools.builtin.schedule import fire_schedule_job
    # 优先用请求里带的 user_id（来自 ScheduleCreateTool），否则用当前登录用户
    job_user_id = req.user_id or user_id
    kwargs = dict(
        session_id=req.session_id,
        prompt=req.prompt,
        channel=req.channel,
        channel_context=req.channel_context,
        user_id=job_user_id,
    )
    if req.cron:
        scheduler.add_cron(req.job_id, fire_schedule_job, req.cron, **kwargs)
    elif req.interval_minutes > 0:
        scheduler.add_interval(req.job_id, fire_schedule_job, minutes=req.interval_minutes, **kwargs)
    else:
        raise HTTPException(400, "Need cron or interval_minutes")
    return {"ok": True}


@router.delete("/{job_id}", dependencies=[Depends(verify_token)])
async def delete_schedule(job_id: str):
    scheduler = get_scheduler()
    if not scheduler.remove(job_id):
        raise HTTPException(404, "Job not found or could not be removed")
    return {"ok": True}


class SchedulePatchRequest(BaseModel):
    state: str | None = None
    name: str | None = None


@router.patch("/{job_id}", dependencies=[Depends(verify_token)])
async def patch_schedule(job_id: str, req: SchedulePatchRequest):
    scheduler = get_scheduler()
    if req.state is not None:
        if req.state == "paused":
            success = scheduler.pause(job_id)
        elif req.state == "active":
            success = scheduler.resume(job_id)
        else:
            raise HTTPException(400, "Invalid state. Use 'paused' or 'active'")
        if not success:
            raise HTTPException(404, "Job not found or could not be updated")
    if req.name is not None:
        new_name = req.name.strip()
        if not new_name:
            raise HTTPException(400, "Name must not be empty")
        if not scheduler.modify_name(job_id, new_name):
            raise HTTPException(404, "Job not found or could not be renamed")
    return {"ok": True}
