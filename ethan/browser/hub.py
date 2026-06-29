"""BrowserHub — 进程内单例,管理与 Chrome 扩展的单条 WebSocket 连接。

职责:
  - 持有当前扩展 WS 连接(last-wins:新连接顶掉旧的)。
  - 发起 JSON-RPC 请求并按 id 配对响应,带 30s 超时。
  - per-session 锁:同一 browser session 的 pages.* 操作串行,不同 session 并行。
  - 断连时把所有 pending 请求 fail 成可重试错误。

不保存 session/tab/page 状态镜像(扩展才是 source of truth);
ethan_session_id ↔ browser_session_id 的映射在 session_map.py。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any

from ethan.browser.protocol import (
    DEFAULT_REQUEST_TIMEOUT,
    ERROR_CODE,
    SESSION_SCOPED_PREFIX,
)

logger = logging.getLogger("ethan.browser")


class BrowserError(Exception):
    """browser RPC 失败。retryable=True 表示 agent 可重新 snapshot 后重试。"""

    def __init__(self, message: str, *, code: int = ERROR_CODE["operation_failed"], retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class _Connection:
    """一条扩展 WS 连接的运行态。"""

    def __init__(self, ws: Any):
        self.ws = ws
        self.pending: dict[int, asyncio.Future] = {}
        self.closed = False

    def fail_all(self, exc: Exception) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self.pending.clear()


class BrowserHub:
    def __init__(self) -> None:
        self._conn: _Connection | None = None
        self._id_gen = itertools.count(1)
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._conn_lock = asyncio.Lock()  # 保护 _conn 切换(last-wins)

    # ── 连接管理 ───────────────────────────────────────────────
    @property
    def connected(self) -> bool:
        return self._conn is not None and not self._conn.closed

    async def attach(self, ws: Any) -> _Connection:
        """注册新扩展连接,last-wins:顶掉旧连接并 fail 其 pending 请求。"""
        async with self._conn_lock:
            if self._conn is not None and not self._conn.closed:
                logger.info("browser: new extension connection, evicting previous (last-wins)")
                old = self._conn
                old.closed = True
                old.fail_all(BrowserError(
                    "浏览器连接被新连接顶替",
                    code=ERROR_CODE["extension_not_connected"],
                    retryable=True,
                ))
                try:
                    await old.ws.close()
                except Exception:
                    pass
            conn = _Connection(ws)
            self._conn = conn
            return conn

    async def detach(self, conn: _Connection) -> None:
        """连接断开:若仍是当前连接则清空,并 fail 所有 pending。"""
        async with self._conn_lock:
            conn.closed = True
            conn.fail_all(BrowserError(
                "浏览器断连,请重新 snapshot 后重试",
                code=ERROR_CODE["extension_not_connected"],
                retryable=True,
            ))
            if self._conn is conn:
                self._conn = None
                logger.info("browser: extension disconnected")

    def on_message(self, conn: _Connection, raw: str) -> None:
        """扩展回传的一条消息:解析为 JSON-RPC 响应并 resolve 对应 Future。"""
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("browser: received non-JSON message, ignored")
            return
        msg_id = msg.get("id")
        if msg_id is None:
            return  # 通知类消息,本阶段不处理
        fut = conn.pending.pop(msg_id, None)
        if fut is None or fut.done():
            return
        if "error" in msg and msg["error"]:
            err = msg["error"]
            fut.set_exception(BrowserError(
                err.get("message", "browser operation failed"),
                code=err.get("code", ERROR_CODE["operation_failed"]),
            ))
        else:
            fut.set_result(msg.get("result"))

    # ── 锁 ────────────────────────────────────────────────────
    def _lock_for(self, method: str, browser_session_id: str | None) -> asyncio.Lock | None:
        """page 操作按 browser_session_id 取串行锁;其余操作不加锁。"""
        if not method.startswith(SESSION_SCOPED_PREFIX) or not browser_session_id:
            return None
        lock = self._session_locks.get(browser_session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[browser_session_id] = lock
        return lock

    # ── 请求 ───────────────────────────────────────────────────
    async def call(
        self,
        method: str,
        params: dict | None = None,
        *,
        browser_session_id: str | None = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> Any:
        """向扩展发起一次 JSON-RPC 请求,等待响应或超时。"""
        lock = self._lock_for(method, browser_session_id)
        if lock is not None:
            async with lock:
                return await self._call_unlocked(method, params, timeout)
        return await self._call_unlocked(method, params, timeout)

    async def _call_unlocked(self, method: str, params: dict | None, timeout: float) -> Any:
        conn = self._conn
        if conn is None or conn.closed:
            raise BrowserError(
                "浏览器扩展未连接,请确认已安装并启用扩展",
                code=ERROR_CODE["extension_not_connected"],
                retryable=False,
            )
        req_id = next(self._id_gen)
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        conn.pending[req_id] = fut
        try:
            await conn.ws.send_text(json.dumps(payload))
        except Exception as e:
            conn.pending.pop(req_id, None)
            raise BrowserError(
                f"发送浏览器指令失败: {e}",
                code=ERROR_CODE["extension_not_connected"],
                retryable=True,
            ) from e
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            conn.pending.pop(req_id, None)
            raise BrowserError(
                f"浏览器指令超时({timeout}s),请重新 snapshot 后重试",
                code=ERROR_CODE["operation_failed"],
                retryable=True,
            ) from e


_hub: BrowserHub | None = None


def get_hub() -> BrowserHub:
    """进程内单例。单进程 uvicorn 下安全(见方案 Q2)。"""
    global _hub
    if _hub is None:
        _hub = BrowserHub()
    return _hub
