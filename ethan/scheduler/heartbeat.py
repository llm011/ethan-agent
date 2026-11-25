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
        self._checks: dict[Callable, Callable] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def register(self, callback: Callable, change_check: Callable | None = None) -> None:
        """Optional cheap local predicate; existing callbacks remain periodic."""
        self._callbacks.append(callback)
        if change_check is not None:
            self._checks[callback] = change_check

    async def _tick(self) -> None:
        for cb in self._callbacks:
            check = self._checks.get(cb)
            if check is not None:
                try:
                    # Checks must be local/non-LLM. Offload sync I/O from the event loop.
                    changed = await check() if asyncio.iscoroutinefunction(check) else await asyncio.to_thread(check)
                    if not changed:
                        logger.info("Heartbeat unchanged; callback skipped")
                        continue
                except Exception:
                    logger.warning("Heartbeat change check failed; callback fallback", exc_info=True)
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
            except Exception:
                logger.warning("Heartbeat callback error", exc_info=True)

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
            await self._tick()
