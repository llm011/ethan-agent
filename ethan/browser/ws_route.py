"""FastAPI WebSocket 路由 /ws/browser —— Chrome 扩展连接入口。

扩展是 WS client,ethan 是 server(浏览器内无法当 server)。
首帧必须发 {"type":"auth","token":"<ethan token>","name":"<客户端名称>"};校验失败直接 close。
name 缺省时自动分配 "default"。同名连接 last-wins(同一浏览器的扩展重连)。
鉴权通过后把连接交给 BrowserHub,循环转发后续消息。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ethan.browser.hub import get_hub
from ethan.browser.protocol import RPC_VERSION

logger = logging.getLogger("ethan.browser")

router = APIRouter()

# name 缺省时的自增序号
_name_gen = itertools.count(1)


def _authenticate(token: str) -> str | None:
    """复用 ethan 的 web token → user_id 解析。失败返回 None。"""
    if not token:
        return None
    from ethan.core.users import get_user_store
    return get_user_store().resolve_web_token(token.strip())


def _normalize_name(raw: str | None) -> str:
    """归一化客户端名称:去空白、限长、缺省时自动分配。"""
    if raw:
        name = raw.strip()[:64]
        if name:
            return name
    return f"browser-{next(_name_gen)}"


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

    client_name = _normalize_name(hello.get("name"))

    await ws.send_text(json.dumps({"type": "auth_ok", "version": RPC_VERSION, "name": client_name}))

    hub = get_hub()
    conn = await hub.attach(ws, client_name)
    logger.info("browser ws: extension '%s' connected", client_name)

    try:
        evict_waiter = asyncio.ensure_future(conn.evicted.wait())
        while True:
            recv_task = asyncio.ensure_future(ws.receive_text())
            done, _ = await asyncio.wait(
                {recv_task, evict_waiter}, return_when=asyncio.FIRST_COMPLETED
            )
            if evict_waiter in done:
                recv_task.cancel()
                break
            raw = recv_task.result()
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
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("browser ws: unexpected error")
    finally:
        evict_waiter.cancel()
        await hub.detach(conn)
