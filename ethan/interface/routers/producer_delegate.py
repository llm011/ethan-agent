"""producer delegate responsibilities; imported via producers facade."""
from __future__ import annotations

import asyncio
import logging

from ethan.memory.session import SessionStore
from ethan.providers.base import Message

from .helpers import _friendly_error
from .producer_helpers import _RunManager_schedule_removal

logger = logging.getLogger(__name__)

async def _run_delegate_generation(
    run,
    prompt: str,
    agent_name: str,
    cwd: str,
    store: SessionStore,
    session_id: str,
    user_id: str = "",
) -> None:
    """Producer：在镜像会话里直接发消息时，把消息当新 prompt 续接对应 coding agent。

    走 acp.delegate(prefer=agent, resume=True)，过程中的 step/text 经 on_event 实时
    emit 进这条会话的 ChatRun；结束后把回复+步骤落成 assistant 消息。
    mirror=False：避免 delegate 内部再为同一 session 注册一个 ChatRun（双 writer）。
    """
    import os as _os

    from ethan.acp import delegate

    emitted_text = False

    def _emit(etype, data):
        nonlocal emitted_text
        if etype == "text":
            emitted_text = True
            run.emit({"content": data})
        elif etype == "step" and isinstance(data, dict):
            run.emit(
                {
                    "tool": data.get("tool", ""),
                    "args": data.get("args", ""),
                    "state": data.get("state", "done"),
                    "id": f"mirror-{id(data)}",
                    "duration_ms": data.get("duration_ms"),
                    "result_preview": data.get("result_preview", ""),
                }
            )

    # cwd 可能已被删除（临时目录、项目移动等）。提前给出清晰提示，
    # 避免 codex/claude 子进程抛出晦涩的 "[Errno 2] No such file or directory"。
    if not cwd or not _os.path.isdir(cwd):
        msg = f"该会话对应的工作目录已不存在：{cwd or '(空)'}\n无法继续在此目录续接 {agent_name}。"
        run.emit({"content": msg})
        try:
            await store.save_message(session_id, Message(role="assistant", content=msg))
            await store.touch(session_id, mark_read=bool(run.subscribers))
        except Exception:
            pass
        run.emit({"done": True, "usage": {}})
        run.finish()
        _RunManager_schedule_removal(run.session_id)
        return

    result = None
    try:
        result = await delegate(
            prompt=prompt,
            cwd=cwd,
            prefer=agent_name,
            timeout=240,
            resume=True,
            user_id=user_id,
            mirror=False,
            on_event=_emit,
        )
    except asyncio.CancelledError:
        run.emit({"stopped": True, "usage": {}})
        run.finish()
        _RunManager_schedule_removal(run.session_id)
        raise
    except Exception as e:
        err_text = _friendly_error(e, None)
        if err_text:
            run.emit({"error": err_text})
        else:
            logger.warning("Suppressed transient error in delegate: %s", e)

    try:
        if result is not None:
            content = result.output or ("(委派失败，无输出)" if not result.success else "(无输出)")
            # 子进程层失败时 on_event 不会触发，没有任何 text 推过；
            # 把最终结果作为 content 补推一次，避免 live 流空返回（刷新才看到）。
            if not emitted_text:
                run.emit({"content": content})
            await store.save_message(
                session_id,
                Message(
                    role="assistant",
                    content=content,
                    tool_steps=result.sub_steps or [],
                ),
            )
            await store.touch(session_id, mark_read=bool(run.subscribers))
    except Exception:
        logger.exception("保存委派续接结果失败 session=%s", session_id)

    run.emit({"done": True, "usage": {}})
    run.finish()
    _RunManager_schedule_removal(run.session_id)
