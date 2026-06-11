"""心跳调度器 — 定期触发 agent 回顾待办事项。"""
import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class Heartbeat:
    """每隔固定时间触发一次 callback，让 agent 做定期检查。"""

    def __init__(self, interval_minutes: int = 60):
        self._interval = interval_minutes * 60
        self._callbacks: list[Callable] = []
        self._running = False
        self._task: asyncio.Task | None = None

    def register(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._interval)
            for cb in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb()
                    else:
                        cb()
                except Exception as e:
                    logger.warning(f"Heartbeat callback error: {e}")
