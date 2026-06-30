"""委派镜像会话 —— 把 Ethan 委派给 Coding Agent 的每一次对话落成一条真正的 Ethan session。

动机：用户在 web 上让 Ethan「帮我开发 X」，Ethan 委派给 codex/claude/opencode 时，
希望在 Ethan 侧也有一条对应会话，能看到下发的 query、Coding Agent 的回复、以及中间
工具步骤——而不只是主对话里一行 delegate_coding 工具结果。

粒度：每次 delegate() 调用 = 一条镜像 session（source="delegate"）。
- user 消息 = 下发给 Coding Agent 的 query
- assistant 消息 = Coding Agent 的最终回复 + tool_steps（由 sub_steps 转来）

持久化走 per-user 的 SessionStore（user_sessions_db_path），与普通 web 会话同库，
因此 web 侧边栏天然能列出它（source 过滤可区分）。本模块只负责「写」，不依赖任何
HTTP/SSE——实时推送是上层 RunManager 的事，可后续叠加。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _title_for(agent: str, task: str) -> str:
    head = task.strip().replace("\n", " ")
    head = head[:30] + ("…" if len(head) > 30 else "")
    return f"[{agent}] {head}" if head else f"[{agent}] 委派任务"


class MirrorSession:
    """一次委派的镜像会话写入器。

    用法：
        mirror = await MirrorSession.start(agent="codex", task=prompt, cwd=cwd, user_id=uid)
        ...（delegate 跑完拿到 result）...
        await mirror.finish(result.output, result.sub_steps, is_error=not result.success)

    任何一步失败都吞掉异常（best-effort），绝不影响主委派流程。
    """

    def __init__(self, store, session_id: str):
        self._store = store
        self.session_id = session_id
        # 中间事件累积（步骤/文本），供实时推送或调试回看。
        self.events: list[tuple[str, object]] = []
        # 可选的实时发射器：上层（RunManager）注册后，每个中间事件实时转发给前端。
        self._emitter = None

    def bind_emitter(self, emitter) -> "MirrorSession":
        """注册实时发射器，签名 emitter(event_type:str, data) → 可同步或异步。

        不注册时 on_event 只把事件存进 self.events（结束时仍由 finish 落库）。
        """
        self._emitter = emitter
        return self

    async def on_event(self, event_type: str, data) -> None:
        """Coding Agent 跑动过程中每个中间事件的回调（step / text）。best-effort。"""
        self.events.append((event_type, data))
        if self._emitter is None:
            return
        try:
            import inspect
            r = self._emitter(event_type, data)
            if inspect.isawaitable(r):
                await r
        except Exception:
            logger.debug("MirrorSession emitter failed", exc_info=True)

    @classmethod
    async def start(
        cls,
        agent: str,
        task: str,
        cwd: str,
        user_id: str = "",
        model: str = "",
    ) -> Optional["MirrorSession"]:
        try:
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from ethan.providers.base import Message

            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            session = await store.create(model=model or agent, source="delegate")
            await store.update_title(session.id, _title_for(agent, task))
            # 下发的 query 作为 user 消息落库
            await store.save_message(session.id, Message(
                role="user", content=task, created_at=time.time(),
            ))
            await store.touch(session.id)
            return cls(store, session.id)
        except Exception:
            logger.debug("MirrorSession.start failed (agent=%s)", agent, exc_info=True)
            try:
                await store.close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return None

    async def finish(self, output: str, sub_steps: list | None, is_error: bool = False) -> None:
        """把 Coding Agent 的回复 + 工具步骤落成 assistant 消息，并关库。"""
        try:
            from ethan.providers.base import Message
            content = output or ("(委派失败，无输出)" if is_error else "(无输出)")
            await self._store.save_message(self.session_id, Message(
                role="assistant",
                content=content,
                created_at=time.time(),
                tool_steps=sub_steps or [],
            ))
            await self._store.touch(self.session_id)
        except Exception:
            logger.debug("MirrorSession.finish failed", exc_info=True)
        finally:
            try:
                await self._store.close()
            except Exception:
                pass
