"""ACP OpenCode agent: JSON event stream, multi-turn session support."""
import asyncio
import json
import shutil
from pathlib import Path
from typing import Optional

from .models import ACPResult
from .session import clear_session, set_session
from .utils import _preview, _summarize_args, _terminate_proc


async def _run_opencode(
    prompt: str,
    cwd: Optional[str] = None,
    timeout: int = 180,
    resume_session_id: Optional[str] = None,
    user_id: str = "",
    on_event: Optional[callable] = None,
) -> ACPResult:
    """Run OpenCode with `--format json`，解析事件流，支持多轮续接。

    首轮：opencode run --format json <prompt> → 从事件里拿 sessionID。
    续轮：opencode run -s <sessionID> --format json <prompt>。
    session 按 (opencode, cwd) 持久化，与 claude/codex 路径并存互不覆盖。

    on_event 可选：回调函数，每有中间事件调用一次，传 (event_type, data)。
    """
    opencode_bin = shutil.which("opencode")
    if not opencode_bin:
        return ACPResult(success=False, output="opencode command not found.", agent="opencode")

    work_dir = cwd or str(Path.cwd())
    base = [opencode_bin, "run", "--format", "json", "--dangerously-skip-permissions"]
    if resume_session_id:
        base += ["-s", resume_session_id]
    cmd = base + [prompt]

    sub_steps: list[dict] = []
    session_id = resume_session_id or ""
    text_parts: list[str] = []
    is_error = False

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=work_dir,
        )
        assert proc.stdout is not None

        async def _consume():
            nonlocal session_id, is_error
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                sid = evt.get("sessionID") or (evt.get("part") or {}).get("sessionID")
                if sid:
                    session_id = sid
                etype = evt.get("type") or ""
                part = evt.get("part") or {}
                ptype = part.get("type") or ""
                if etype == "text" or ptype == "text":
                    t = part.get("text") or evt.get("text") or ""
                    if t:
                        text_parts.append(t)
                        if on_event:
                            await on_event("text", t)
                elif etype == "tool" or ptype == "tool" or ptype.startswith("tool"):
                    state = part.get("state") or {}
                    status = state.get("status") if isinstance(state, dict) else ""
                    name = part.get("tool") or part.get("name") or "tool"
                    inp = (state.get("input") if isinstance(state, dict) else None) or part.get("input") or {}
                    out = (state.get("output") if isinstance(state, dict) else None) or part.get("output") or ""
                    step = {
                        "tool": name,
                        "args": _summarize_args(inp if isinstance(inp, dict) else {"input": inp}),
                        "state": "error" if status == "error" else "done",
                        "duration_ms": None,
                        "result_preview": _preview(str(out)),
                    }
                    sub_steps.append(step)
                    if on_event:
                        await on_event("step", step)
                elif etype == "error" or ptype == "error":
                    is_error = True
                    msg = evt.get("message") or part.get("error") or ""
                    if msg:
                        step = {"tool": "error", "args": _preview(str(msg), 80),
                                "state": "error", "duration_ms": None, "result_preview": ""}
                        sub_steps.append(step)
                        if on_event:
                            await on_event("step", step)

        await asyncio.wait_for(_consume(), timeout=timeout)
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        await _terminate_proc(proc)
        # 同 codex：超时可能让 opencode session 卡在进行中，清掉以免下次续接到坏会话。
        if session_id:
            clear_session(work_dir, user_id=user_id, agent="opencode")
        return ACPResult(success=False, output=f"Timed out after {timeout}s",
                         agent="opencode", session_id=session_id, sub_steps=sub_steps)
    except Exception as e:
        return ACPResult(success=False, output=f"Error: {e}",
                         agent="opencode", session_id=session_id, sub_steps=sub_steps)

    final_result = "".join(text_parts).strip()
    if not final_result and sub_steps:
        final_result = "(OpenCode 未返回最终文本结果，可展开查看各步骤)"
    if len(final_result) > 12000:
        final_result = final_result[:12000] + "\n...(truncated)"

    if session_id:
        set_session(work_dir, session_id, user_id=user_id, agent="opencode")

    return ACPResult(
        success=not is_error and bool(final_result),
        output=final_result or "(no output)",
        agent="opencode",
        session_id=session_id,
        sub_steps=sub_steps,
    )
