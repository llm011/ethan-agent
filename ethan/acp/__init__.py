"""ACP Client — 委托复杂编码任务给本地 Coding Agent（Claude Code / OpenCode / Codex）。

通过 subprocess 调用本地 CLI，收集输出返回给 Ethan。

多轮对话：Claude Code 支持 `--resume <session_id>` 续接上次会话。Ethan 按
「用户 × 工作目录」持久化 session_id，连续的 delegate_coding 调用会自动续接同一会话。

结构化输出：Claude Code 用 `--output-format stream-json` 输出 NDJSON 事件流，
解析出每次工具调用（sub_steps）和最终结果，便于 Web UI 折叠展示。
"""
import shutil
from pathlib import Path
from typing import Optional

from .agent_claude import _run_claude_code
from .agent_codex import _run_codex
from .agent_opencode import _run_opencode
from .classify import is_complex_coding_task
from .models import ACPResult
from .session import (
    clear_mirror_session,
    clear_session,
    get_mirror_info,
    get_mirror_session,
    get_session,
    set_mirror_info,
    set_mirror_session,
    set_session,
)

__all__ = [
    "ACPResult",
    "is_complex_coding_task",
    "get_session",
    "set_session",
    "clear_session",
    "get_mirror_session",
    "set_mirror_session",
    "clear_mirror_session",
    "set_mirror_info",
    "get_mirror_info",
    "delegate",
]


async def delegate(
    prompt: str,
    cwd: Optional[str] = None,
    prefer: str = "auto",
    timeout: int = 180,
    resume: bool = True,
    reset_session: bool = False,
    user_id: str = "",
    mirror: bool = True,
    on_event: Optional[callable] = None,
) -> ACPResult:
    """Delegate a task to the best available local coding agent.

    Args:
        resume: 是否续接该 cwd 上次的 Coding Agent 会话（多轮）。
        reset_session: 清除该 cwd 的会话记忆，从新会话开始。
        mirror: 是否把本次委派落成一条 Ethan 镜像 session（query+回复+步骤可在 web 回看）。
        on_event: 可选的额外事件回调（step/text）。镜像会话里「直接发消息续接」时，
                  路由传入它把过程实时推进那条会话的 ChatRun。
    """
    work_dir = cwd or str(Path.cwd())

    # 解析本次实际使用的 agent 名（供镜像会话标题/归类），不改变下面的分派逻辑。
    if prefer in ("opencode", "codex"):
        agent_name = prefer
    elif shutil.which("claude"):
        agent_name = "claude"
    elif shutil.which("opencode"):
        agent_name = "opencode"
    elif shutil.which("codex"):
        agent_name = "codex"
    else:
        agent_name = "none"

    mirror_session = None
    if mirror and agent_name != "none":
        from .mirror import MirrorSession
        # reset_session 同样作用于镜像会话：新建一条，而不是续接到上一条多轮里。
        mirror_session = await MirrorSession.start(
            agent=agent_name, task=prompt, cwd=work_dir, user_id=user_id,
            reuse=not reset_session,
        )

    # 事件回调：镜像会话自己的 + 调用方传入的（如「在镜像会话里直接发消息」走 chat 路由
    # 时，由路由传入 on_event 把过程实时推进那条会话的 ChatRun）。两者都触发。
    async def _combined_on_event(etype, data):
        if mirror_session is not None:
            await mirror_session.on_event(etype, data)
        if on_event is not None:
            r = on_event(etype, data)
            if hasattr(r, "__await__"):
                await r

    dispatch_on_event = _combined_on_event if (mirror_session is not None or on_event is not None) else None
    result = await _dispatch(
        prompt, work_dir, prefer, timeout, resume, reset_session, user_id, agent_name,
        on_event=dispatch_on_event,
    )

    if mirror_session is not None:
        await mirror_session.finish(
            result.output, result.sub_steps, is_error=not result.success,
        )
    return result


async def _dispatch(
    prompt: str,
    work_dir: str,
    prefer: str,
    timeout: int,
    resume: bool,
    reset_session: bool,
    user_id: str,
    agent_name: str,
    on_event: Optional[callable] = None,
) -> ACPResult:
    """实际分派到具体 Coding Agent。镜像会话由 delegate() 在外层包裹。"""
    if prefer == "opencode":
        resume_sid = None
        if reset_session:
            clear_session(work_dir, user_id=user_id, agent="opencode")
        elif resume:
            resume_sid = get_session(work_dir, user_id=user_id, agent="opencode")
        return await _run_opencode(
            prompt, cwd=work_dir, timeout=timeout,
            resume_session_id=resume_sid, user_id=user_id, on_event=on_event,
        )
    if prefer == "codex":
        resume_sid = None
        if reset_session:
            clear_session(work_dir, user_id=user_id, agent="codex")
        elif resume:
            resume_sid = get_session(work_dir, user_id=user_id, agent="codex")
        return await _run_codex(
            prompt, cwd=work_dir, timeout=timeout,
            resume_session_id=resume_sid, user_id=user_id, on_event=on_event,
        )

    # 默认优先 Claude Code（支持多轮 + 子步骤）
    if agent_name == "claude":
        resume_sid = None
        if reset_session:
            clear_session(work_dir, user_id=user_id, agent="claude")
        elif resume:
            resume_sid = get_session(work_dir, user_id=user_id, agent="claude")
        return await _run_claude_code(
            prompt, cwd=work_dir, timeout=timeout,
            resume_session_id=resume_sid, user_id=user_id, on_event=on_event,
        )
    elif agent_name == "opencode":
        return await _run_opencode(prompt, cwd=work_dir, timeout=timeout, user_id=user_id, on_event=on_event)
    elif agent_name == "codex":
        return await _run_codex(prompt, cwd=work_dir, timeout=timeout, user_id=user_id, on_event=on_event)
    else:
        return ACPResult(
            success=False,
            output="No coding agent found. Install Claude Code (https://claude.ai/code), OpenCode, or Codex.",
            agent="none",
        )
