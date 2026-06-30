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
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 生成结束后保留 run 的宽限期（秒）：让刚好在收尾瞬间刷新的客户端仍能重连回放。
_GRACE_SECONDS = 90

# 订阅队列收到此哨兵表示「流结束」，消费者据此关闭 SSE。
_SENTINEL = object()


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

    def emit(self, event: dict) -> None:
        """记录一个事件并扇出给所有当前订阅者（同步，无 await）。"""
        self.events.append(event)
        for q in self.subscribers:
            q.put_nowait(event)

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
        for q in self.subscribers:
            q.put_nowait(_SENTINEL)


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
