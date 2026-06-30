"""background_tasks 路由：后台任务中心读取 + 终止。

仅暴露读取（list）与终止（stop）——任务发起走工具（background_task），不开放 HTTP 直接发起，
避免绕过 agent 上下文。任务状态在 server 进程内存（ethan.tools.builtin.background_task._REGISTRY），
任务中心轮询本接口刷新。
"""
from fastapi import APIRouter, Depends, HTTPException

from .deps import verify_token

router = APIRouter(prefix="/background-tasks")


@router.get("", dependencies=[Depends(verify_token)])
async def get_background_tasks():
    from ethan.tools.builtin.background_task import list_tasks
    return {"tasks": list_tasks()}


@router.post("/{task_id}/stop")
async def stop_background_task(task_id: str, user_id: str = Depends(verify_token)):
    from ethan.tools.builtin.background_task import stop_task
    ok, msg = stop_task(task_id, user_id=user_id)
    if not ok:
        raise HTTPException(404, msg)
    return {"ok": True, "message": msg}
