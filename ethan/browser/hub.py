"""BrowserHub — 进程内单例,管理与多个 Chrome 扩展的 WebSocket 连接。

职责:
  - 持有多个扩展 WS 连接,按客户端名称索引(name→conn)。
  - 同名连接 last-wins:新连接顶掉同名旧连接。
  - 发起 JSON-RPC 请求并按 id 配对响应,带 30s 超时。
  - per-session 锁:同一 browser session 的 pages.* 操作串行,不同 session 并行。
  - 断连时把所有 pending 请求 fail 成可重试错误。
  - per-ethan-session 活跃客户端:每个对话绑定一个当前操作的浏览器端。

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

    def __init__(self, ws: Any, name: str):
        self.ws = ws
        self.name = name
        self.pending: dict[int, asyncio.Future] = {}
        self.closed = False

    def fail_all(self, exc: Exception) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self.pending.clear()


class BrowserHub:
    def __init__(self) -> None:
        self._conns: dict[str, _Connection] = {}  # name → connection
        self._id_gen = itertools.count(1)
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._conn_lock = asyncio.Lock()  # 保护 _conns 切换
        # ethan_session_id → 活跃客户端名称
        self._session_clients: dict[str, str] = {}

    # ── 连接管理 ───────────────────────────────────────────────
    @property
    def connected(self) -> bool:
        """是否有任意一条扩展连接存活。"""
        return any(not c.closed for c in self._conns.values())

    async def attach(self, ws: Any, name: str) -> _Connection:
        """注册新扩展连接。同名连接 last-wins:顶掉旧连接并 fail 其 pending 请求。"""
        async with self._conn_lock:
            old = self._conns.get(name)
            if old is not None and not old.closed:
                logger.info("browser: client '%s' reconnecting, evicting previous", name)
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
            conn = _Connection(ws, name)
            self._conns[name] = conn
            logger.info("browser: client '%s' connected (%d total)", name, len(self._conns))
            return conn

    async def detach(self, conn: _Connection) -> None:
        """连接断开:若仍是当前连接则移除,并 fail 所有 pending。"""
        async with self._conn_lock:
            conn.closed = True
            conn.fail_all(BrowserError(
                "浏览器断连,请重新 snapshot 后重试",
                code=ERROR_CODE["extension_not_connected"],
                retryable=True,
            ))
            # 只在字典里的 conn 确实是这个断开的 conn 时才移除
            # (防止 detach 一个已被同名新连接顶替的旧 conn 时误删新连接)
            current = self._conns.get(conn.name)
            if current is conn:
                del self._conns[conn.name]
                logger.info("browser: client '%s' disconnected (%d remaining)", conn.name, len(self._conns))
            # 清理引用了此客户端的活跃会话映射
            stale = [sid for sid, cname in self._session_clients.items() if cname == conn.name]
            for sid in stale:
                del self._session_clients[sid]

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

    async def broadcast_notification(self, method: str, params: dict | None = None) -> int:
        """向所有在线扩展客户端发送一条单向 JSON-RPC 通知（无 id），不等待响应。

        用于广播无需回执的事件（如授权 consent 请求、系统通知等）。
        返回成功发送的连接数。"""
        sent = 0
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}})
        # snapshot conns 避免持有锁期间 send_text 可能阻塞/抛错
        async with self._conn_lock:
            conns = list(self._conns.values())
        for conn in conns:
            if conn.closed:
                continue
            try:
                await conn.ws.send_text(payload)
                sent += 1
            except Exception as e:
                logger.info("browser: notify client '%s' failed: %s", conn.name, e)
        return sent

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

    # ── 客户端管理 ─────────────────────────────────────────────
    def list_clients(self) -> list[dict]:
        """返回所有已连接的客户端信息。"""
        return [
            {"name": name, "connected": not conn.closed}
            for name, conn in self._conns.items()
            if not conn.closed
        ]

    def get_active_client(self, ethan_session_id: str) -> str | None:
        """返回某 ethan 会话的活跃客户端名称。"""
        if not ethan_session_id:
            return None
        return self._session_clients.get(ethan_session_id)

    def set_active_client(self, ethan_session_id: str, client_name: str) -> bool:
        """设置某 ethan 会话的活跃客户端。返回是否成功(客户端需在线)。"""
        if not ethan_session_id:
            return False
        conn = self._conns.get(client_name)
        if conn is None or conn.closed:
            return False
        self._session_clients[ethan_session_id] = client_name
        return True

    def resolve_client(self, ethan_session_id: str) -> str | None:
        """解析某 ethan 会话应使用的客户端名称。

        优先级:
          1. 会话已设的活跃客户端(且仍在线)
          2. 只有一个客户端在线 → 自动选中
          3. 多个客户端且未设活跃 → 返回 None(由调用方提示 agent 询问用户)
        """
        # 1. 已设活跃客户端
        active = self._session_clients.get(ethan_session_id)
        if active:
            conn = self._conns.get(active)
            if conn and not conn.closed:
                return active
            # 活跃客户端已断连,清理
            self._session_clients.pop(ethan_session_id, None)

        # 2. 在线客户端列表
        online = [name for name, conn in self._conns.items() if not conn.closed]
        if len(online) == 1:
            # 只有一个,自动选中
            self._session_clients[ethan_session_id] = online[0]
            return online[0]

        # 3. 0 个或多个,无法自动决策
        return None

    # ── 请求 ───────────────────────────────────────────────────
    async def call(
        self,
        method: str,
        params: dict | None = None,
        *,
        client_name: str | None = None,
        browser_session_id: str | None = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> Any:
        """向指定客户端的扩展发起一次 JSON-RPC 请求,等待响应或超时。"""
        lock = self._lock_for(method, browser_session_id)
        if lock is not None:
            async with lock:
                return await self._call_unlocked(method, params, client_name, timeout)
        return await self._call_unlocked(method, params, client_name, timeout)

    async def _call_unlocked(self, method: str, params: dict | None, client_name: str | None, timeout: float) -> Any:
        if client_name is None:
            raise BrowserError(
                "未指定浏览器客户端,请先用 browser_client(action='list') 查看已连接的客户端,"
                "再用 browser_client(action='use', name=...) 选择一个",
                code=ERROR_CODE["extension_not_connected"],
                retryable=False,
            )
        conn = self._conns.get(client_name)
        if conn is None or conn.closed:
            raise BrowserError(
                f"浏览器客户端 '{client_name}' 未连接",
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
