"""ACPConsentProvider —— 把 ethan 的 consent 流程桥接到 ACP request_permission。

复用关系：仿 `ethan/core/consent.py` 的 WebConsentProvider（streamed=True，
create() 返回 (ConsentEvent, Future)），ethan agent loop 侧的流式内联 consent
路径（agent.py `_request_consent` / stream_chat consent 分支）完全不变。

ACP 侧差异：Web 是「SSE 注入事件 → 前端 POST /api/consent/{id} 解析 Future」，
ACP 是「后台 task 调 conn.request_permission() → daemon 返回 outcome 解析 Future」。

Multica daemon 的自动应答契约（无人值守）：优先 allow_session → allow_once →
reject_once，绝不自动 allow_always。所以我们的 options 顺序把 reject 放最后、
approve_session 放最前，配合 option kind 让 daemon 选到最持久的许可。

outcome 映射（ACP RequestPermissionOutcome，SDK 实测）：
- AllowedOutcome(outcome="selected", optionId="approve_once"/"approve_session") → allowed
- AllowedOutcome(outcome="selected", optionId=其他/未知) → denied（保守）
- DeniedOutcome(outcome="cancelled") → denied
"""
from __future__ import annotations

import asyncio
import logging
import secrets as _secrets

from acp.schema import (
    AllowedOutcome,
    DeniedOutcome,
    PermissionOption,
    RequestPermissionResponse,
    ToolCallUpdate,
)

from ethan.acp_server.mapping import tool_kind
from ethan.core.consent import ConsentEvent, ConsentProvider

logger = logging.getLogger(__name__)

# ACP PermissionOption.kind: "allow_once" | "allow_always" | "reject_once" | "reject_always"
_OPTION_APPROVE_ONCE = PermissionOption(
    optionId="approve_once", name="允许一次", kind="allow_once"
)
_OPTION_APPROVE_SESSION = PermissionOption(
    optionId="approve_session", name="本会话内允许", kind="allow_always"
)
_OPTION_REJECT = PermissionOption(optionId="reject", name="拒绝", kind="reject_once")

_PERMISSION_OPTIONS = [_OPTION_APPROVE_SESSION, _OPTION_APPROVE_ONCE, _OPTION_REJECT]

_APPROVE_OPTION_IDS = {"approve_once", "approve_session"}


class ACPConsentProvider(ConsentProvider):
    """streamed=True：agent loop yield ConsentEvent 后 await Future；
    本 provider 在 create() 时同时发起 ACP request_permission 请求。"""

    streamed = True

    def __init__(self, conn, acp_session_id: str, session_id: str = ""):
        # conn: acp.agent.connection.AgentSideConnection
        self._conn = conn
        self._acp_session_id = acp_session_id  # ACP 协议层的 session id
        self.session_id = session_id  # ethan sessions.db 的 session id（授权记忆用）
        self._pending: dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()

    def create(
        self, description: str, tool: str = "", detail: str = "", always: bool = False
    ) -> tuple[ConsentEvent, asyncio.Future]:
        req_id = _secrets.token_hex(8)
        # 必须用 get_running_loop：create() 只会在 agent loop 的 stream_chat
        # 里被调（running loop 内）；get_event_loop() 在无 running loop 的线程
        # 上会报错/返回陈旧 loop（与 WebConsentProvider 同款场景，但那里历史原因用了旧 API）
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut

        # 高危（always=True）：不给「本会话内允许」选项，逼 daemon 只能逐次放行或拒绝
        options = _PERMISSION_OPTIONS if not always else [_OPTION_APPROVE_ONCE, _OPTION_REJECT]

        task = loop.create_task(self._request_permission(req_id, description, tool, detail, options))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        event = ConsentEvent(request_id=req_id, description=description, tool=tool, detail=detail, always=always)
        return event, fut

    async def _request_permission(
        self,
        req_id: str,
        description: str,
        tool: str,
        detail: str,
        options: list[PermissionOption],
    ) -> None:
        """发起 ACP request_permission 并把 outcome 写回 Future。

        请求异常（client 不支持该方法等）按拒绝处理——与 Web 端 300s 超时语义一致。
        """
        fut = self._pending.get(req_id)
        if fut is None or fut.done():
            return
        tool_call = ToolCallUpdate(toolCallId=req_id, title=description[:200], kind=tool_kind(tool))
        try:
            resp: RequestPermissionResponse = await self._conn.request_permission(
                session_id=self._acp_session_id, tool_call=tool_call, options=options
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ACP request_permission 失败，按拒绝处理 req=%s tool=%s", req_id, tool)
            self._resolve(req_id, allowed=False)
            return
        outcome = getattr(resp, "outcome", None)
        if isinstance(outcome, AllowedOutcome):
            allowed = outcome.option_id in _APPROVE_OPTION_IDS
        elif isinstance(outcome, DeniedOutcome):
            allowed = False
        else:
            allowed = False
        self._resolve(req_id, allowed=allowed)

    def _resolve(self, req_id: str, allowed: bool) -> None:
        fut = self._pending.pop(req_id, None)
        if fut is not None and not fut.done():
            fut.set_result(allowed)

    def cancel_all(self) -> None:
        """请求结束/中断时取消未决 Future 与后台 request_permission task。"""
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        for task in list(self._tasks):
            task.cancel()
