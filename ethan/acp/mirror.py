"""委派镜像会话 —— 把 Ethan 委派给 Coding Agent 的每一次对话落成一条真正的 Ethan session。

动机：用户在 web 上让 Ethan「帮我开发 X」，Ethan 委派给 codex/claude/opencode 时，
希望在 Ethan 侧也有一条对应会话，能看到下发的 query、Coding Agent 的回复、以及中间
工具步骤——而不只是主对话里一行 delegate_coding 工具结果。

粒度：同一 (agent, cwd) 的连续多轮委派累加到同一条 Ethan 镜像 session（多轮对话）；
切换任务（reset_session）时新建一条。source 用真实 coding agent 名（codex/claude/
opencode），web 侧边栏渠道徽标据此显示是哪个工具。
- user 消息 = 每一轮下发给 Coding Agent 的 query
- assistant 消息 = 每一轮 Coding Agent 的最终回复 + tool_steps（由 sub_steps 转来）

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
    # source 徽标已显示是哪个 coding agent，标题不再重复前缀，直接用任务摘要。
    head = task.strip().replace("\n", " ")
    head = head[:36] + ("…" if len(head) > 36 else "")
    return head or f"{agent} 委派任务"


class MirrorSession:
    """一次委派的镜像会话写入器。

    用法：
        mirror = await MirrorSession.start(agent="codex", task=prompt, cwd=cwd, user_id=uid)
        ...（delegate 跑完拿到 result）...
        await mirror.finish(result.output, result.sub_steps, is_error=not result.success)

    任何一步失败都吞掉异常（best-effort），绝不影响主委派流程。
    """

    def __init__(self, store, session_id: str, run=None):
        self._store = store
        self.session_id = session_id
        # 中间事件累积（步骤/文本），供实时推送或调试回看。
        self.events: list[tuple[str, object]] = []
        # 可选的实时发射器：上层（RunManager）注册后，每个中间事件实时转发给前端。
        self._emitter = None
        # 关联的 ChatRun（注册到 RunManager 后，web 可经 /chat/{id}/stream attach）。
        self._run = run
        if run is not None:
            self._emitter = self._emit_to_run

    def _emit_to_run(self, event_type: str, data) -> None:
        """默认发射器：把中间事件按 chat SSE 的事件词表 emit 进关联的 ChatRun。

        - text → {"content": ...}
        - step → 工具事件（用 id(step) 作稳定 id：claude 同一 step 对象 running→done
          会配对，codex/opencode 各 step 是独立对象天然不串）。
        """
        if self._run is None:
            return
        if event_type == "text":
            self._run.emit({"content": data})
        elif event_type == "step" and isinstance(data, dict):
            self._run.emit({
                "tool": data.get("tool", ""),
                "args": data.get("args", ""),
                "state": data.get("state", "done"),
                "id": f"mirror-{id(data)}",
                "duration_ms": data.get("duration_ms"),
                "result_preview": data.get("result_preview", ""),
            })

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
        register_run: bool = True,
        reuse: bool = True,
    ) -> Optional["MirrorSession"]:
        """创建/续接镜像 session。

        source 用真实的 coding agent 名（codex/claude/opencode），让 web 侧边栏
        的渠道徽标直接显示是哪个工具，而不是笼统的 "delegate"。

        reuse=True（默认）：同一 (agent, cwd) 的连续委派累加到同一条 Ethan 会话
        （多轮对话）；只在该会话仍存在于库中时复用，否则新建。reuse=False（对应
        reset_session）：强制新建一条，并刷新映射。

        register_run=True 时同时在 RunManager 注册一个 ChatRun，使委派过程可经 web
        `/chat/{session_id}/stream` 实时 attach（query 已落库，assistant 文本/步骤
        经 on_event 实时 emit）。
        """
        store = None
        try:
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from ethan.providers.base import Message
            from ethan.acp import get_mirror_session, set_mirror_session, set_mirror_info

            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()

            session_id = None
            if reuse:
                prev = get_mirror_session(cwd, user_id=user_id, agent=agent)
                if prev and await store.load(prev) is not None:
                    session_id = prev  # 续接已有镜像会话（多轮）

            if session_id is None:
                # session.model 必须是一个「实在的、可用于 chat 的模型」。
                # 不能用 agent 名（codex/claude/opencode）——那不是 ethan 的注册模型，
                # 用户在镜像会话里直接发消息时会被当成 chat 模型，导致
                # "unknown provider for model codex" 502。渠道归类已由 source=agent 表达。
                real_model = model
                if not real_model:
                    try:
                        from ethan.core.config import get_config
                        real_model = get_config().defaults.model
                    except Exception:
                        real_model = ""
                session = await store.create(model=real_model, source=agent)
                session_id = session.id
                await store.update_title(session_id, _title_for(agent, task))
                set_mirror_session(cwd, session_id, user_id=user_id, agent=agent)

            # 反向映射：让用户直接在这条镜像会话里发消息时，能查出续接哪个 agent/cwd
            set_mirror_info(session_id, agent=agent, cwd=cwd, user_id=user_id)

            # 下发的 query 作为 user 消息落库（每一轮都追加）
            await store.save_message(session_id, Message(
                role="user", content=task, created_at=time.time(),
            ))
            await store.touch(session_id)

            run = None
            if register_run:
                try:
                    from ethan.core.run_manager import RunManager
                    run = RunManager.instance().create(session_id, user_id=user_id)
                except Exception:
                    logger.debug("MirrorSession run register failed", exc_info=True)
            return cls(store, session_id, run=run)
        except Exception:
            logger.debug("MirrorSession.start failed (agent=%s)", agent, exc_info=True)
            if store is not None:
                try:
                    await store.close()
                except Exception:
                    pass
            return None

    async def finish(self, output: str, sub_steps: list | None, is_error: bool = False) -> None:
        """把 Coding Agent 的回复 + 工具步骤落成 assistant 消息，关库，并收尾实时流。"""
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
            # 收尾实时流：通知订阅者结束并安排清理（宽限期内仍可重连回放）。
            if self._run is not None:
                try:
                    self._run.emit({"done": True, "usage": {}})
                    self._run.finish()
                    from ethan.core.run_manager import RunManager
                    RunManager.instance().schedule_removal(self.session_id)
                except Exception:
                    logger.debug("MirrorSession run finish failed", exc_info=True)

