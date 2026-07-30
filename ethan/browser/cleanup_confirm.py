"""浏览器 session 清理确认机制。

对话结束后，不自动关闭 tab group，而是弹卡片让用户确认。
后端 emit 一个 confirm 事件到 SSE 流，前端弹卡片，
用户点「关闭」或「保留」后调 POST /api/browser/cleanup/{request_id} 解析。
超时默认保留（更安全）。
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field

logger = logging.getLogger("ethan.browser")

# 超时后默认动作：保留 tab（只 unbind，不 close）
TIMEOUT_DEFAULT = "keep"
TIMEOUT_SECONDS = 120


@dataclass
class CleanupRequest:
    """一次清理确认请求。"""
    request_id: str
    ethan_session_id: str
    # 待清理的 browser session 列表，每项含 sessionId / title / tabCount
    sessions: list[dict]
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


# 全局注册表：request_id → CleanupRequest
_PENDING: dict[str, CleanupRequest] = {}


def create_confirm(ethan_session_id: str, sessions: list[dict]) -> CleanupRequest:
    """创建一个清理确认请求，返回 CleanupRequest（含 request_id 和 future）。"""
    request_id = secrets.token_hex(8)
    req = CleanupRequest(
        request_id=request_id,
        ethan_session_id=ethan_session_id,
        sessions=sessions,
    )
    _PENDING[request_id] = req
    return req


def resolve_confirm(request_id: str, action: str) -> bool:
    """用户响应后解析 Future。action: "close" | "keep"。"""
    req = _PENDING.pop(request_id, None)
    if req is None:
        return False
    if not req.future.done():
        req.future.set_result(action)
    return True


def cancel_confirm(request_id: str) -> None:
    """取消一个待确认请求（如会话被删除）。"""
    req = _PENDING.pop(request_id, None)
    if req is not None and not req.future.done():
        req.future.set_result(TIMEOUT_DEFAULT)


def cancel_for_session(ethan_session_id: str) -> None:
    """取消某 ethan 会话的所有待确认请求。"""
    to_remove = [rid for rid, r in _PENDING.items() if r.ethan_session_id == ethan_session_id]
    for rid in to_remove:
        cancel_confirm(rid)


async def await_confirm(req: CleanupRequest, timeout: float = TIMEOUT_SECONDS) -> str:
    """等待用户确认，超时返回默认动作（保留）。"""
    try:
        return await asyncio.wait_for(req.future, timeout=timeout)
    except asyncio.TimeoutError:
        logger.info("browser: cleanup confirm timeout for %s, defaulting to %s",
                     req.request_id, TIMEOUT_DEFAULT)
        _PENDING.pop(req.request_id, None)
        return TIMEOUT_DEFAULT
