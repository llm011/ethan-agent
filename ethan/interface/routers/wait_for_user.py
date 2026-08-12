"""wait_for_user 路由 —— 前端回传用户的确认/输入。

流程：
  1. Agent 调用 wait_for_user 工具 → SSE 流注入 {"wait_for_user_request": true, ...}
  2. 前端显示等待卡片，用户点击确认/取消或提交文本
  3. 前端 POST /api/wait-for-user/{request_id} {"value": "done"|"cancel"|"<text>"}
  4. 本路由解析对应的 Future，Agent 的 await 返回，流继续
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .deps import verify_token

router = APIRouter()


class WaitForUserResponse(BaseModel):
    value: str


@router.post("/wait-for-user/{request_id}")
async def respond_wait_for_user(request_id: str, body: WaitForUserResponse, user_id: str = Depends(verify_token)):
    from ethan.core.wait_for_user import resolve_wait_for_user

    ok = resolve_wait_for_user(request_id, body.value)
    if not ok:
        raise HTTPException(status_code=404, detail="request not found or already resolved")
    return {"ok": ok}
