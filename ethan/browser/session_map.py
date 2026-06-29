"""ethan 会话 ↔ browser session 映射 + idle 生命周期。

会话模型(方案 Q1=绑对话):
  每个 ethan 会话(ethan_session_id)维护自己的一组 browser session,
  互相隔离,避免飞书不同用户 / Web 不同标签踩同一组 tab。

清理(方案 Q8):
  browser session 闲置超过 idle_ttl 后 release(放掉控制权、保留用户 tab),
  不是 close(不杀 tab,避免破坏用户正在看的页面)。
  真正 close 只在 agent/用户显式调用时发生。
"""
from __future__ import annotations

import asyncio
import logging
import time

from ethan.browser.hub import BrowserError, get_hub
from ethan.browser.protocol import METHODS

logger = logging.getLogger("ethan.browser")

IDLE_TTL_SECONDS = 30 * 60  # 闲置 30min 后 release
_SWEEP_INTERVAL = 5 * 60  # 每 5min 扫一次


class _Entry:
    __slots__ = ("ethan_session_id", "last_active")

    def __init__(self, ethan_session_id: str):
        self.ethan_session_id = ethan_session_id
        self.last_active = time.monotonic()


class SessionMap:
    """browser_session_id → 归属 ethan 会话 + 最后活跃时间。"""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def bind(self, browser_session_id: str, ethan_session_id: str) -> None:
        self._entries[browser_session_id] = _Entry(ethan_session_id)

    def touch(self, browser_session_id: str) -> None:
        """每次对该 session 的操作刷新活跃时间。"""
        entry = self._entries.get(browser_session_id)
        if entry is not None:
            entry.last_active = time.monotonic()

    def unbind(self, browser_session_id: str) -> None:
        self._entries.pop(browser_session_id, None)

    def list_for(self, ethan_session_id: str) -> list[str]:
        return [
            bsid for bsid, e in self._entries.items()
            if e.ethan_session_id == ethan_session_id
        ]

    def idle_sessions(self, ttl: float) -> list[str]:
        now = time.monotonic()
        return [
            bsid for bsid, e in self._entries.items()
            if now - e.last_active > ttl
        ]


_map: SessionMap | None = None


def get_session_map() -> SessionMap:
    global _map
    if _map is None:
        _map = SessionMap()
    return _map


# ── idle release 扫描 ───────────────────────────────────────────
_sweep_task: asyncio.Task | None = None


async def _sweep_once() -> None:
    smap = get_session_map()
    hub = get_hub()
    # 截图清理与扩展是否连接无关,总是执行
    try:
        from ethan.browser.screenshot import cleanup_shots
        cleanup_shots()
    except Exception:
        logger.exception("browser: screenshot cleanup error")
    if not hub.connected:
        return  # 扩展没连,跳过(断连时 session 状态已无意义)
    for bsid in smap.idle_sessions(IDLE_TTL_SECONDS):
        try:
            await hub.call(METHODS["session_release"], {"sessionId": bsid}, browser_session_id=bsid)
            logger.info("browser: released idle session %s", bsid)
        except BrowserError as e:
            logger.warning("browser: idle release failed for %s: %s", bsid, e)
        finally:
            smap.unbind(bsid)


async def _sweep_loop() -> None:
    await asyncio.sleep(_SWEEP_INTERVAL)
    while True:
        try:
            await _sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("browser: idle sweep error")
        await asyncio.sleep(_SWEEP_INTERVAL)


def start_idle_sweep() -> None:
    global _sweep_task
    if _sweep_task and not _sweep_task.done():
        return
    _sweep_task = asyncio.create_task(_sweep_loop())
    logger.info("browser: idle sweep started (ttl=%ds)", IDLE_TTL_SECONDS)


def stop_idle_sweep() -> None:
    global _sweep_task
    if _sweep_task and not _sweep_task.done():
        _sweep_task.cancel()
