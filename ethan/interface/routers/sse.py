"""SSE consumer: converts a ChatRun event stream into Server-Sent Events."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

# SSE 心跳间隔：每 15 秒发一个注释行，防止 WebKit/WebView2 空闲断连
_SSE_HEARTBEAT_INTERVAL = 15.0


async def _sse_from_run(run) -> AsyncGenerator[str, None]:
    """Consumer：把一个 ChatRun 的事件流转成 SSE。

    先回放缓冲（断线重连补齐已生成内容），再实时读队列直到收到结束哨兵。
    本生成器被取消（客户端断开）只退订，不影响 producer。

    心跳：队列空闲时每 15 秒发 `: keepalive\\n\\n`（SSE 注释，前端忽略但连接保活），
    防止 WebKit/WebView2 的空闲超时静默断连导致桌面端输出停住。
    """
    from ethan.core.run_manager import SENTINEL

    q, backlog = run.subscribe()
    try:
        for evt in backlog:
            # 跳过已解决的 consent 事件：刷新重连时不要再弹已回应过的授权弹窗
            if evt.get("consent_request") and run.consent is not None:
                req_id = evt.get("request_id", "")
                # 仍在 pending 中说明还没回应，需要重新展示
                if req_id and req_id not in getattr(run.consent, "_pending", {}):
                    continue
            # 跳过已解决的浏览器清理确认事件
            if evt.get("confirm_browser_cleanup"):
                req_id = evt.get("request_id", "")
                if req_id:
                    from ethan.browser.cleanup_confirm import _PENDING
                    if req_id not in _PENDING:
                        continue
            # 跳过已解决的 wait_for_user 事件
            if evt.get("wait_for_user_request"):
                req_id = evt.get("request_id", "")
                if req_id:
                    from ethan.core.wait_for_user import _REGISTRY as _WFU_REGISTRY
                    if req_id not in _WFU_REGISTRY:
                        continue
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        # 缓冲已含结束事件且 producer 已完成：无需再等队列
        if run.done:
            return
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=_SSE_HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # 空闲超时：发 SSE 注释心跳保活，前端会忽略
                yield ": keepalive\n\n"
                continue
            if item is SENTINEL:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    finally:
        run.unsubscribe(q)
