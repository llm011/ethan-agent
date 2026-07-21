"""schedule 路由：定时任务 CRUD + 时间线管理。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ethan.core.config import CONFIG_DIR

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


def _validate_path_in_config(path_str: str) -> Path:
    """校验路径在 CONFIG_DIR 内（防止任意路径读取/写入）。

    允许：CONFIG_DIR 及其子目录下的文件。
    拒绝：绝对路径穿越、CONFIG_DIR 之外的路径。
    """
    if not path_str:
        raise HTTPException(400, "Missing path")
    target = Path(path_str).expanduser().resolve()
    config_root = CONFIG_DIR.resolve()
    try:
        target.relative_to(config_root)
    except ValueError:
        raise HTTPException(403, f"Path must be inside {config_root}, got {target}")
    if not target.exists():
        raise HTTPException(404, f"File not found: {target}")
    return target


def _infer_category(job) -> str:
    """从 job kwargs 或 trigger 类型推断分类。

    优先取 kwargs.category；否则 DateTrigger→one_off，其他→recurring。
    """
    kwargs = job.kwargs or {}
    cat = kwargs.get("category")
    if cat:
        return cat
    # 兜底：按 trigger 类型推断（旧任务无 category 字段）
    try:
        from apscheduler.triggers.date import DateTrigger
        if isinstance(job.trigger, DateTrigger):
            return "one_off"
    except Exception:
        pass
    return "recurring"


@router.get("", dependencies=[Depends(verify_token)])
async def get_schedules():
    scheduler = get_scheduler()
    jobs = scheduler._scheduler.get_jobs()
    result = []
    for job in jobs:
        kwargs = job.kwargs or {}
        result.append({
            "id": job.id,
            "title": kwargs.get("title", "") or job.name or job.id,
            "trigger": str(job.trigger),
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "status": "paused" if job.next_run_time is None else "active",
            "prompt": kwargs.get("prompt", ""),
            "session_id": kwargs.get("session_id", ""),
            "channel": kwargs.get("channel", "web"),
            "channel_context": kwargs.get("channel_context", "{}"),
            "category": _infer_category(job),
            "source_timeline": kwargs.get("source_timeline", ""),
            "source_phase": kwargs.get("source_phase", ""),
            "scene": kwargs.get("scene", "work"),
        })
    return {"jobs": result}


class ScheduleCreateRequest(BaseModel):
    job_id: str
    title: str = ""
    prompt: str
    cron: str = ""
    interval_minutes: int = 0
    end_date: str = ""  # YYYY-MM-DD or YYYY-MM-DD HH:MM; job auto-removed after this date
    session_id: str
    channel: str = "web"
    channel_context: str = "{}"
    user_id: str = ""
    category: str = ""  # one_off / recurring / timeline；空则按 trigger 推断


@router.post("")
async def create_schedule(req: ScheduleCreateRequest, user_id: str = Depends(verify_token)):
    scheduler = get_scheduler()
    from ethan.tools.builtin.schedule import fire_schedule_job
    # 优先用请求里带的 user_id（来自 ScheduleCreateTool），否则用当前登录用户
    job_user_id = req.user_id or user_id
    # category 兜底
    category = req.category or ("recurring" if req.cron or req.interval_minutes > 0 else "one_off")
    kwargs = dict(
        session_id=req.session_id,
        prompt=req.prompt,
        title=req.title,
        channel=req.channel,
        channel_context=req.channel_context,
        user_id=job_user_id,
        category=category,
    )
    if req.cron:
        scheduler.add_cron(req.job_id, fire_schedule_job, req.cron, end_date=req.end_date or None, name=req.title or req.job_id, **kwargs)
    elif req.interval_minutes > 0:
        scheduler.add_interval(req.job_id, fire_schedule_job, minutes=req.interval_minutes, end_date=req.end_date or None, name=req.title or req.job_id, **kwargs)
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
    title: str | None = None
    prompt: str | None = None


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
    if req.title is not None:
        new_title = req.title.strip()
        if not new_title:
            raise HTTPException(400, "Title must not be empty")
        if not scheduler.modify_name(job_id, new_title):
            raise HTTPException(404, "Job not found or could not be renamed")
        # 同步更新 kwargs 中的 title，确保 fire 时拿到最新标题
        scheduler.modify_kwargs(job_id, title=new_title)
    if req.prompt is not None:
        new_prompt = req.prompt.strip()
        if not new_prompt:
            raise HTTPException(400, "Prompt must not be empty")
        if not scheduler.modify_kwargs(job_id, prompt=new_prompt):
            raise HTTPException(404, "Job not found or could not update prompt")
    return {"ok": True}


# ── Timeline 端点 ──────────────────────────────────────────────────────────

@router.get("/timeline-status", dependencies=[Depends(verify_token)])
async def get_timeline_status():
    """返回所有时间线当前状态，用于 UI 展示。"""
    from dataclasses import asdict

    from ethan.scheduler.timeline import get_timeline_status as _get_status
    statuses = _get_status()
    return {"timelines": [asdict(s) for s in statuses]}


@router.post("/sync-timelines", dependencies=[Depends(verify_token)])
async def sync_timelines():
    """手动触发 timelines.yaml → scheduler 的同步。"""
    from ethan.scheduler.timeline import sync_scheduler as _sync
    scheduler = get_scheduler()
    result = _sync(scheduler)
    return {"ok": True, **result}


@router.post("/timeline/{timeline_id}/{action}", dependencies=[Depends(verify_token)])
async def timeline_lifecycle(timeline_id: str, action: str):
    """时间线生命周期操作：skip_phase / advance_phase / pause / resume / cleanup。"""
    from ethan.scheduler.timeline import lifecycle_manage
    scheduler = get_scheduler()
    result = lifecycle_manage(timeline_id, action, scheduler)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Unknown error"))
    return result


class TimelineExportRequest(BaseModel):
    format: str = "yaml"  # yaml / json


@router.post("/timeline-export", dependencies=[Depends(verify_token)])
async def export_timelines(req: TimelineExportRequest):
    """导出 timelines.yaml + state 为单一文件。"""
    from ethan.scheduler.timeline import export_timelines as _export
    path = _export(format=req.format)
    return {"ok": True, "path": str(path)}


class TimelineImportRequest(BaseModel):
    path: str                       # 导出文件的绝对路径（服务端可访问）
    restore_state: bool = False     # 是否同时恢复 .timeline_state.json
    dry_run: bool = False           # True 时只返回校验结果和预览，不写入
    mode: str = "overwrite"         # overwrite / merge
    sync_after: bool = False        # 写入后是否自动同步 scheduler


@router.post("/timeline-import", dependencies=[Depends(verify_token)])
async def import_timelines(req: TimelineImportRequest):
    """导入时间线配置文件，支持校验、dry-run 和 merge 模式。"""
    from ethan.scheduler.timeline import import_timelines as _import
    safe_path = _validate_path_in_config(req.path)
    result = _import(
        safe_path,
        restore_state=req.restore_state,
        dry_run=req.dry_run,
        mode=req.mode,
        sync_after=req.sync_after,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Import failed"), detail=result)
    return result


@router.post("/timeline-validate", dependencies=[Depends(verify_token)])
async def validate_timelines(payload: dict):
    """校验一个 timelines.yaml 文件是否符合规范（不修改任何文件）。

    body: {"path": "/abs/path/to/file.yaml"}
    路径必须在 CONFIG_DIR 内。
    """
    from ethan.scheduler.timeline import validate_timelines_file
    path_str = payload.get("path", "")
    safe_path = _validate_path_in_config(path_str)
    result = validate_timelines_file(safe_path)
    if not result["ok"]:
        raise HTTPException(400, "Validation failed", detail=result)
    return result


@router.post("/timeline/{timeline_id}/sync-lark", dependencies=[Depends(verify_token)])
async def sync_timeline_to_lark(timeline_id: str):
    """将指定时间线同步到飞书日历（每个 phase 创建一个全天事件）。

    要求 timeline 配置中 `sync_to_lark: true`。
    """
    from ethan.scheduler.timeline import sync_to_lark
    result = sync_to_lark(timeline_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Sync failed"), detail=result)
    return result


@router.post("/timeline/{timeline_id}/cleanup-lark", dependencies=[Depends(verify_token)])
async def cleanup_timeline_lark(timeline_id: str):
    """清理某条时间线在飞书日历上已同步的所有事件。"""
    from ethan.scheduler.timeline import cleanup_lark_resources
    result = cleanup_lark_resources(timeline_id)
    if not result.get("ok"):
        raise HTTPException(400, "Cleanup failed", detail=result)
    return result
