"""SSE consumer: converts a ChatRun event stream into Server-Sent Events."""
from __future__ import annotations

import json
from typing import AsyncGenerator


async def _sse_from_run(run) -> AsyncGenerator[str, None]:
    """Consumer：把一个 ChatRun 的事件流转成 SSE。

    先回放缓冲（断线重连补齐已生成内容），再实时读队列直到收到结束哨兵。
    本生成器被取消（客户端断开）只退订，不影响 producer。
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
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        # 缓冲已含结束事件且 producer 已完成：无需再等队列
        if run.done:
            return
        while True:
            item = await q.get()
            if item is SENTINEL:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    finally:
        run.unsubscribe(q)
