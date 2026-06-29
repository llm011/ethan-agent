"""FastAPI WebSocket 路由 /ws/browser —— Chrome 扩展连接入口。

扩展是 WS client,ethan 是 server(浏览器内无法当 server)。
首帧必须发 {"type":"auth","token":"<ethan token>"};校验失败直接 close。
鉴权通过后把连接交给 BrowserHub(last-wins),循环转发后续消息。
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ethan.browser.hub import get_hub
from ethan.browser.protocol import RPC_VERSION

logger = logging.getLogger("ethan.browser")

router = APIRouter()


def _authenticate(token: str) -> str | None:
    """复用 ethan 的 web token → user_id 解析。失败返回 None。"""
    if not token:
        return None
    from ethan.core.users import get_user_store
    return get_user_store().resolve_web_token(token.strip())


@router.websocket("/ws/browser")
async def browser_ws(ws: WebSocket) -> None:
    await ws.accept()

    # ── 首帧鉴权 ──
    try:
        raw = await ws.receive_text()
        hello = json.loads(raw)
    except (WebSocketDisconnect, ValueError, TypeError):
        await ws.close(code=4001)
        return

    if hello.get("type") != "auth" or _authenticate(hello.get("token", "")) is None:
        logger.warning("browser ws: auth failed")
        await ws.close(code=4001)
        return

    await ws.send_text(json.dumps({"type": "auth_ok", "version": RPC_VERSION}))

    hub = get_hub()
    conn = await hub.attach(ws)
    logger.info("browser ws: extension connected")

    try:
        while True:
            raw = await ws.receive_text()
            # ping/pong 保活帧不进 RPC 配对
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue
            hub.on_message(conn, raw)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("browser ws: unexpected error")
    finally:
        await hub.detach(conn)
