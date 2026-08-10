"""FastAPI WebSocket 路由 /ws/desktop — 桌面端连接入口。

协议与 /ws/browser 一致:
  - 首帧鉴权: {"type":"auth","token":"<ethan token>","name":"<optional>"}
  - 鉴权通过: {"type":"auth_ok","version":1,"name":"<name>"}
  - 后续帧: JSON-RPC response / ping-pong
"""
from __future__ import annotations

import itertools
import json
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from ethan.desktop.hub import get_desktop_hub

logger = logging.getLogger("ethan.desktop")

router = APIRouter()

_name_gen = itertools.count(1)


@router.get("/api/desktop/status")
async def desktop_status(request: Request) -> dict:
    """诊断接口：返回桌面端 WS 连接状态。供桌面端 / curl 排查连接问题。"""
    # 复用 WS 鉴权：query param token 校验，防止未授权探测连接名/状态
    token = request.query_params.get("token", "")
    if _authenticate(token) is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="unauthorized")
    hub = get_desktop_hub()
    conns = []
    async with hub._conn_lock:
        for name, conn in hub._conns.items():
            conns.append({"name": name, "closed": conn.closed})
    return {
        "connected": hub.connected,
        "connection_count": len(conns),
        "connections": conns,
    }


def _authenticate(token: str) -> str | None:
    if not token:
        return None
    from ethan.core.users import get_user_store
    return get_user_store().resolve_web_token(token.strip())


def _normalize_name(raw: str | None) -> str:
    if raw:
        name = raw.strip()[:64]
        if name:
            return name
    return f"desktop-{next(_name_gen)}"


@router.websocket("/ws/desktop")
async def desktop_ws(ws: WebSocket) -> None:
    await ws.accept()

    try:
        raw = await ws.receive_text()
        hello = json.loads(raw)
    except (WebSocketDisconnect, ValueError, TypeError):
        await ws.close(code=4001)
        return

    if hello.get("type") != "auth" or _authenticate(hello.get("token", "")) is None:
        logger.warning("desktop ws: auth failed")
        await ws.close(code=4001)
        return

    client_name = _normalize_name(hello.get("name"))
    await ws.send_text(json.dumps({"type": "auth_ok", "version": 1, "name": client_name}))

    hub = get_desktop_hub()
    conn = await hub.attach(ws, client_name)
    logger.info("desktop ws: client '%s' connected", client_name)

    try:
        while True:
            raw = await ws.receive_text()
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
        logger.exception("desktop ws: unexpected error")
    finally:
        await hub.detach(conn)
