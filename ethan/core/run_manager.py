"""对话「运行态」管理 —— 把一次 Agent 生成与 HTTP/SSE 连接解耦。

问题：原先 SSE 生成器边跑 `agent.stream_chat` 边 `yield`，生成逻辑绑死在连接上。
浏览器刷新 → 连接断开 → 生成任务被取消（抛 CancelledError，非 Exception，
保存逻辑兜不住）→ 整条回复既没生成完也没入库，刷新后只剩用户那句话。

方案：一次生成 = 一个 ChatRun。
- producer（后台 asyncio.Task）跑生成，把事件 `emit` 进缓冲，并扇出给所有订阅者。
- SSE 响应只是「一个订阅者」：先回放缓冲（断线重连能补齐），再实时读队列。
- 订阅者断开只是退订，**不影响 producer**——生成继续跑到底、正常入库。
- 重连时新建订阅者，回放完整缓冲 + 继续实时，体验类似 ChatGPT 刷新不丢。

并发安全：emit / subscribe 都是同步函数（中间无 await），asyncio 单线程下原子，
所以「快照缓冲 + 注册队列」之间不会有 emit 插队，重连不丢事件也不重复。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 生成结束后保留 run 的宽限期（秒）：让刚好在收尾瞬间刷新的客户端仍能重连回放。
_GRACE_SECONDS = 90

# 订阅队列收到此哨兵表示「流结束」，消费者据此关闭 SSE。
_SENTINEL = object()

# Watchdog 参数
_WATCHDOG_INTERVAL = 180   # 每次检查间隔（秒），3 分钟
_WATCHDOG_MAX_CHECKS = 2   # 最多检查次数（超过则放弃）
_WATCHDOG_STALL_SECS = 180 # 超过此时间无新事件视为卡住（秒）


@dataclass
class ChatRun:
    """一次 Agent 生成的运行态。"""

    session_id: str
    user_id: str = ""  # 会话归属用户。重连/查活跃时比对，防跨用户 attach（IDOR）
    events: list[dict] = field(default_factory=list)  # 回放缓冲：迄今所有 SSE 事件
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    done: bool = False
    task: asyncio.Task | None = None  # producer 任务引用
    consent: Any = None  # WebConsentProvider，收尾时 cancel_all
    stop_requested: bool = False  # 用户主动停止（区别于「新 run 替换旧 run」的取消）：前者保存已生成的部分内容
    start_time: float = field(default_factory=time.monotonic)
    last_event_time: float = field(default_factory=time.monotonic)
    watchdog_checks: int = 0  # 已执行的 watchdog 检查次数
    watchdog_task: asyncio.Task | None = None  # watchdog 强引用，finish() 时取消
    # 用户「运行中补充信息」收件箱：inject() 入队，agent loop 每轮开头 drain_injected() 取走。
    # asyncio 单线程下 list.append / clear 原子，无需 lock。
    injected_messages: list[str] = field(default_factory=list)

    def emit(self, event: dict) -> None:
        """记录一个事件并扇出给所有当前订阅者（同步，无 await）。"""
        self.events.append(event)
        self.last_event_time = time.monotonic()
        for q in self.subscribers:
            q.put_nowait(event)

    def inject(self, content: str) -> None:
        """外部异步注入补充信息：等下一轮调模型前由 agent loop 消费。

        同步操作，asyncio 单线程下与 drain_injected() 互不交错。
        """
        self.injected_messages.append(content)

    def drain_injected(self) -> list[str]:
        """agent loop 每轮开头调一次：取走并清空待消费的补充信息。无则返回空列表。"""
        if not self.injected_messages:
            return []
        msgs = self.injected_messages.copy()
        self.injected_messages.clear()
        return msgs

    def subscribe(self) -> tuple[asyncio.Queue, list[dict]]:
        """注册一个订阅者，返回 (队列, 当前缓冲快照)。

        同步执行，与 emit 互不交错：快照里的事件 = 注册前已 emit 的，
        注册后 emit 的事件会进队列。两者拼接 = 完整且不重复。
        """
        q: asyncio.Queue = asyncio.Queue()
        backlog = list(self.events)
        self.subscribers.add(q)
        return q, backlog

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def finish(self) -> None:
        """producer 结束时调用：标记完成并给所有订阅者推哨兵。"""
        self.done = True
        if self.watchdog_task is not None and not self.watchdog_task.done():
            self.watchdog_task.cancel()
        for q in self.subscribers:
            q.put_nowait(_SENTINEL)


async def _run_watchdog(run: ChatRun, manager: "RunManager") -> None:
    """轻量看门狗：任务启动后定期检查是否正常，最多检查 _WATCHDOG_MAX_CHECKS 次。

    检查逻辑：
    1. run.done → 任务已正常结束，直接退出
    2. run 被替换（manager 里已是新 run）→ 直接退出
    3. producer task 已结束但 run.done=False → 任务崩溃未 finish，补发 error 并 finish
    4. producer task 在跑但超过 _WATCHDOG_STALL_SECS 无新事件 → emit heartbeat 通知用户
    5. 检查次数超上限 → 放弃监控
    """
    try:
        await asyncio.sleep(_WATCHDOG_INTERVAL)
    except asyncio.CancelledError:
        return

    while True:
        # 是否还是同一个 run（没被新请求替换）
        current = manager._runs.get(run.session_id)
        if current is not run or run.done:
            return

        run.watchdog_checks += 1

        # producer task 已结束但没走到 finish()（崩溃路径遗漏）
        task = run.task
        if task is not None and task.done():
            exc = task.exception() if not task.cancelled() else None
            if not run.done:
                logger.warning(
                    "[Watchdog] producer for %s ended without finish() (exc=%s), patching",
                    run.session_id, exc,
                )
                err_msg = "任务意外终止（内部错误）。如需继续请重新发送消息。"
                if exc:
                    from ethan.interface.routers.helpers import _friendly_error
                    try:
                        err_msg = _friendly_error(exc, None)
                    except Exception:
                        err_msg = str(exc)[:200]
                run.emit({"error": err_msg})
                run.finish()
                manager.schedule_removal(run.session_id)
            return

        # task 仍在运行，检查是否卡住
        stall_secs = time.monotonic() - run.last_event_time
        if stall_secs >= _WATCHDOG_STALL_SECS:
            elapsed = int(time.monotonic() - run.start_time)
            run.emit({"heartbeat": True, "elapsed": elapsed})
            logger.info(
                "[Watchdog] %s stalled %.0fs, emitted heartbeat (check %d/%d)",
                run.session_id, stall_secs, run.watchdog_checks, _WATCHDOG_MAX_CHECKS,
            )

        if run.watchdog_checks >= _WATCHDOG_MAX_CHECKS:
            if run.task and not run.task.done():
                logger.warning("[Watchdog] %s reached max checks, cancelling stalled task", run.session_id)
                run.task.cancel()
                run.emit({"error": "任务超时：模型长时间无响应，已自动终止。请重试。"})
                run.finish()
                RunManager.instance().schedule_removal(run.session_id)
            else:
                logger.info("[Watchdog] %s reached max checks, task already done", run.session_id)
            return

        # 下一轮
        try:
            await asyncio.sleep(_WATCHDOG_INTERVAL)
        except asyncio.CancelledError:
            return


class RunManager:
    """全局 run 注册表（单例）：session_id → ChatRun。"""

    _instance: "RunManager | None" = None

    def __init__(self) -> None:
        self._runs: dict[str, ChatRun] = {}

    @classmethod
    def instance(cls) -> "RunManager":
        if cls._instance is None:
            cls._instance = RunManager()
        return cls._instance

    def get(self, session_id: str, user_id: str | None = None) -> ChatRun | None:
        """取 run。传 user_id 时校验归属——不匹配返回 None（防跨用户 attach，IDOR）。
        不传 user_id（None）仅供内部无归属语境使用，对外端点必须传。"""
        run = self._runs.get(session_id)
        if run is None:
            return None
        if user_id is not None and run.user_id != user_id:
            return None
        return run

    def has_active(self, session_id: str, user_id: str | None = None) -> bool:
        """是否存在「未完成」的 run（done 后的宽限期不算活跃，DB 已落库）。
        传 user_id 时校验归属，不匹配视为不存在。"""
        run = self.get(session_id, user_id)
        return run is not None and not run.done

    def stop(self, session_id: str, user_id: str | None = None) -> bool:
        """用户主动停止某 session 的进行中生成：标记 stop_requested 并取消 producer 任务。

        与 create() 里「新 run 取消旧 run」不同——那是丢弃，这里会保存已生成的部分内容
        （由 _run_generation 的 CancelledError 分支根据 stop_requested 决定）。
        传 user_id 时校验归属，不匹配返回 False（防跨用户停别人的任务）。
        返回是否真的停了一个进行中的 run。"""
        run = self.get(session_id, user_id)
        if run is None or run.done:
            return False
        run.stop_requested = True
        if run.task is not None:
            run.task.cancel()
        return True

    def create(self, session_id: str, consent: Any = None, user_id: str = "") -> ChatRun:
        """为 session 创建新 run。若已有未完成的 run，先取消它，避免两个 writer。"""
        old = self._runs.get(session_id)
        if old is not None and not old.done and old.task is not None:
            logger.warning("session %s 已有活跃 run，取消旧任务", session_id)
            old.task.cancel()
        run = ChatRun(session_id=session_id, user_id=user_id, consent=consent)
        self._runs[session_id] = run
        run.watchdog_task = asyncio.create_task(_run_watchdog(run, self))
        return run

    def schedule_removal(self, session_id: str) -> None:
        """生成结束后，宽限期到点把 run 从注册表移除。"""
        asyncio.create_task(self._delayed_remove(session_id))

    async def _delayed_remove(self, session_id: str) -> None:
        await asyncio.sleep(_GRACE_SECONDS)
        run = self._runs.get(session_id)
        # 仅当还是同一个已完成的 run 才移除（期间可能被新 run 替换）
        if run is not None and run.done:
            self._runs.pop(session_id, None)


SENTINEL = _SENTINEL

