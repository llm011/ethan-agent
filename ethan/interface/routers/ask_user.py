"""ask_user 路由 —— 前端回传用户的选择。

流程：
  1. Agent 调用 ask_user 工具 → SSE 流注入 {"ask_user_request": true, ...}
  2. 前端显示选择卡片，用户点击
  3. 前端 POST /api/ask-user/{request_id} {"value": "chosen_value"}
  4. 本路由解析对应的 Future，Agent 的 await 返回，流继续
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .deps import verify_token

router = APIRouter()


class AskUserResponse(BaseModel):
    value: str


@router.post("/ask-user/{request_id}")
async def respond_ask_user(request_id: str, body: AskUserResponse, user_id: str = Depends(verify_token)):
    # TODO(输入校验): 目前接受 body.value 任意字符串。应该把 create() 时的 options 存到 _REGISTRY，
    #   然后在这里校验 value 必须在 options.value 集合中；否则返回 400。
    #   有 token 保护风险很低，但仍是一个可以被滥用的入口。
    from ethan.core.ask_user import resolve_ask_user
    ok = resolve_ask_user(request_id, body.value)
    return {"ok": ok}
