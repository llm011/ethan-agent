"""consent 路由 —— 前端对授权请求做出 允许/拒绝 响应。

流程：
  1. Agent 在工具执行前需要授权 → SSE 流注入 {"consent_request": true, "request_id": ...}
  2. 前端弹窗，用户点击允许/拒绝
  3. 前端 POST /api/consent/{request_id} {"allowed": true/false}
  4. 本路由解析对应的 Future，Agent 的 await 返回，流继续
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .deps import verify_token

router = APIRouter()


class ConsentResponse(BaseModel):
    allowed: bool
    message: str = ""  # 用户在授权弹窗中补充的信息（可选）


@router.post("/consent/{request_id}")
async def respond_consent(request_id: str, body: ConsentResponse, user_id: str = Depends(verify_token)):
    from ethan.core.consent import resolve_consent
    ok = resolve_consent(request_id, body.allowed, body.message)
    return {"ok": ok}
