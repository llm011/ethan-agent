"""DesktopHub — 进程内单例，管理与桌面端的 WebSocket 长连接。

职责:
  - 持有桌面端 WS 连接（通常只有一条）。
  - 向桌面端推送 JSON-RPC 通知（notification、countdown 指令等）。
  - 支持 request/response 模式（带 id 的 JSON-RPC 请求）。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

logger = logging.getLogger("ethan.desktop")


class DesktopError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class _Connection:
    def __init__(self, ws: Any, name: str):
        self.ws = ws
        self.name = name
        self.pending: dict[int, asyncio.Future] = {}
        self.closed = False
        self.evicted = asyncio.Event()

    def fail_all(self, exc: Exception) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self.pending.clear()


class DesktopHub:
    def __init__(self) -> None:
        self._conns: dict[str, _Connection] = {}
        self._id_gen = itertools.count(1)
        self._conn_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return any(not c.closed for c in self._conns.values())

    async def attach(self, ws: Any, name: str) -> _Connection:
        async with self._conn_lock:
            old = self._conns.get(name)
            if old is not None and not old.closed:
                logger.info("desktop: client '%s' reconnecting, evicting previous", name)
                old.closed = True
                old.evicted.set()
                old.fail_all(DesktopError("桌面端连接被新连接顶替", retryable=True))
                try:
                    await old.ws.close()
                except Exception:
                    pass
            conn = _Connection(ws, name)
            self._conns[name] = conn
            logger.info("desktop: client '%s' connected (%d total)", name, len(self._conns))
            return conn

    async def detach(self, conn: _Connection) -> None:
        async with self._conn_lock:
            conn.closed = True
            conn.fail_all(DesktopError("桌面端断连", retryable=True))
            current = self._conns.get(conn.name)
            if current is conn:
                del self._conns[conn.name]
                logger.info("desktop: client '%s' disconnected (%d remaining)", conn.name, len(self._conns))

    def on_message(self, conn: _Connection, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        msg_id = msg.get("id")
        if msg_id is None:
            return
        fut = conn.pending.pop(msg_id, None)
        if fut is None or fut.done():
            return
        if "error" in msg and msg["error"]:
            fut.set_exception(DesktopError(msg["error"].get("message", "desktop operation failed")))
        else:
            fut.set_result(msg.get("result"))

    async def notify(self, method: str, params: dict | None = None) -> int:
        """向所有在线桌面端发送通知（无 id，不等回复）。返回成功发送数。"""
        sent = 0
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}})
        async with self._conn_lock:
            conns = list(self._conns.values())
        for conn in conns:
            if conn.closed:
                continue
            try:
                await conn.ws.send_text(payload)
                sent += 1
            except Exception as e:
                logger.info("desktop: notify client '%s' failed: %s", conn.name, e)
        return sent

    async def call(self, method: str, params: dict | None = None, *, timeout: float = 10.0) -> Any:
        """向桌面端发起 JSON-RPC 请求并等待响应。"""
        async with self._conn_lock:
            conns = [c for c in self._conns.values() if not c.closed]
        if not conns:
            raise DesktopError("桌面端未连接", retryable=False)
        conn = conns[0]
        req_id = next(self._id_gen)
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        conn.pending[req_id] = fut
        try:
            await conn.ws.send_text(json.dumps(payload))
        except Exception as e:
            conn.pending.pop(req_id, None)
            raise DesktopError(f"发送桌面端指令失败: {e}", retryable=True) from e
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            conn.pending.pop(req_id, None)
            raise DesktopError(f"桌面端指令超时({timeout}s)", retryable=True) from e


_hub: DesktopHub | None = None


def get_desktop_hub() -> DesktopHub:
    global _hub
    if _hub is None:
        _hub = DesktopHub()
    return _hub
