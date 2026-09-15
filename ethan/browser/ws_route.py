"""FastAPI WebSocket 路由 /ws/browser —— Chrome 扩展连接入口。

扩展是 WS client,ethan 是 server(浏览器内无法当 server)。
首帧必须发 {"type":"auth","token":"<ethan token>","name":"<客户端名称>",
"instanceId":"<浏览器实例标识>"};校验失败直接 close。
name 缺省时从 instanceId 派生稳定默认名(SW 回收重连 instanceId 不变,名字跟着
稳定,session 绑定的 client_name 不失效);instanceId 也缺省时退回 "browser-<序号>"。
同名连接:instanceId 相同(同一浏览器重连)→ last-wins 顶掉旧连接;instanceId
不同(两台浏览器撞名)→ 拒绝新连接并只回 auth_error + close(先 attach 后
auth_ok,冲突方不会收到 auth_ok),避免两台机器互相顶替。
鉴权通过后把连接交给 BrowserHub,循环转发后续消息。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ethan.browser.hub import BrowserClientNameConflictError, get_hub
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


def _normalize_name(raw: str | None, instance_id: str = "") -> str:
    """归一化客户端名称:去空白、限长、缺省时从 instanceId 派生稳定名。"""
    if raw:
        name = raw.strip()[:64]
        if name:
            return name
    # 缺省名从 instanceId 取前 8 位字母数字派生:同一浏览器怎么重连名字都不变,
    # session 绑的 client_name 就不会因改名失效。instanceId 异常(清洗后为空)时
    # 退回自增序号——名字会变,但至少能用,存活会话靠探针回填兜底。
    tail = re.sub(r"[^0-9a-zA-Z]", "", instance_id or "")[:8]
    if tail:
        return f"browser-{tail}"
    return f"browser-{next(_name_gen)}"


def _normalize_instance_id(raw: object) -> str:
    """归一化浏览器实例标识:仅允许出现在首帧里的一个短字符串。"""
    if isinstance(raw, str):
        instance_id = raw.strip()[:128]
        if instance_id:
            return instance_id
    return ""


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

    instance_id = _normalize_instance_id(hello.get("instanceId"))
    client_name = _normalize_name(hello.get("name"), instance_id)

    hub = get_hub()
    try:
        conn = await hub.attach(ws, client_name, instance_id=instance_id)
    except BrowserClientNameConflictError as e:
        # 撞名但不是同一台浏览器:拒绝新连接,保住正在服务的旧连接。
        # auth_ok 必须等 attach 成功后再发——否则冲突方会收到 auth_ok → auth_error
        # → close 三连,与协议文档的握手时序对不上,照文档实现的客户端会踩坑。
        logger.warning("browser ws: name conflict for '%s', rejecting new connection", client_name)
        try:
            await ws.send_text(json.dumps({"type": "auth_error", "error": str(e)}))
        except Exception:
            pass
        await ws.close(code=4001, reason="client name in use by another browser")
        return
    logger.info("browser ws: extension '%s' connected", client_name)
    await ws.send_text(json.dumps({"type": "auth_ok", "version": RPC_VERSION, "name": client_name}))

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
