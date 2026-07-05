"""ACP Claude Code agent: stream-json multi-turn + sub-step parsing."""
import asyncio
import json
import shutil
from pathlib import Path
from typing import Optional

from .models import ACPResult
from .session import clear_session, set_session
from .utils import _preview, _summarize_args, _terminate_proc


def _extract_tool_result_text(content) -> str:
    """tool_result 的 content 可能是 str 或 list[{type:text,text:...}]。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                texts.append(c.get("text", ""))
            elif isinstance(c, str):
                texts.append(c)
        return " ".join(texts)
    return str(content)


async def _run_claude_code(
    prompt: str,
    cwd: Optional[str] = None,
    timeout: int = 180,
    resume_session_id: Optional[str] = None,
    user_id: str = "",
    on_event: Optional[callable] = None,
) -> ACPResult:
    """Run Claude Code with stream-json output, parse sub-steps and final result.

    on_event 可选：回调函数，每有中间事件调用一次，传 (event_type, data)。
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return ACPResult(
            success=False,
            output="claude command not found. Install Claude Code: https://claude.ai/code",
            agent="claude",
        )

    work_dir = cwd or str(Path.cwd())
    cmd = [
        claude_bin, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
    ]
    if resume_session_id:
        cmd += ["--resume", resume_session_id]
    # 非交互场景跳过权限询问
    cmd.append("--dangerously-skip-permissions")

    sub_steps: list[dict] = []
    pending: dict[str, dict] = {}  # tool_use_id → step dict（等待对应 tool_result）
    start_times: dict[str, float] = {}
    session_id = resume_session_id or ""
    final_result = ""
    is_error = False

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=work_dir,
        )
        assert proc.stdout is not None

        async def _consume():
            nonlocal session_id, final_result, is_error
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

                t = evt.get("type")
                if t == "system" and evt.get("subtype") == "init":
                    sid = evt.get("session_id")
                    if sid:
                        session_id = sid
                elif t == "assistant":
                    for c in evt.get("message", {}).get("content", []):
                        if c.get("type") == "tool_use":
                            tool_name = c.get("name", "tool")
                            tool_use_id = c.get("id", "")
                            step = {
                                "tool": tool_name,
                                "args": _summarize_args(c.get("input", {})),
                                "state": "running",
                                "duration_ms": None,
                                "result_preview": "",
                            }
                            sub_steps.append(step)
                            if tool_use_id:
                                pending[tool_use_id] = step
                                start_times[tool_use_id] = asyncio.get_event_loop().time()
                            if on_event:
                                await on_event("step", step)
                        elif c.get("type") == "text" and c.get("text") and on_event:
                            await on_event("text", c.get("text"))
                elif t == "user":
                    for c in evt.get("message", {}).get("content", []):
                        if c.get("type") == "tool_result":
                            tool_use_id = c.get("tool_use_id", "")
                            step = pending.get(tool_use_id)
                            if step:
                                elapsed = asyncio.get_event_loop().time() - start_times.get(tool_use_id, 0)
                                step["duration_ms"] = int(elapsed * 1000)
                                step["result_preview"] = _preview(_extract_tool_result_text(c.get("content", "")))
                                step["state"] = "error" if c.get("is_error") else "done"
                                if on_event:
                                    await on_event("step", step)
                elif t == "result":
                    final_result = evt.get("result", "") or ""
                    sid = evt.get("session_id")
                    if sid:
                        session_id = sid
                    is_error = bool(evt.get("is_error"))
                    # subtype=success/max_tokens/error 等

        await asyncio.wait_for(_consume(), timeout=timeout)
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        await _terminate_proc(proc)
        # 超时可能让 claude session 卡在进行中，清掉以免下次续接到坏会话。
        if session_id:
            clear_session(work_dir, user_id=user_id, agent="claude")
        return ACPResult(
            success=False,
            output=f"Timed out after {timeout}s",
            agent="claude",
            session_id=session_id,
            sub_steps=sub_steps,
        )
    except Exception as e:
        return ACPResult(success=False, output=f"Error: {e}", agent="claude", session_id=session_id, sub_steps=sub_steps)

    # 未拿到 result 事件时兜底
    if not final_result and sub_steps:
        final_result = "(Coding Agent 未返回最终文本结果，可展开查看各工具调用步骤)"

    if len(final_result) > 12000:
        final_result = final_result[:12000] + "\n...(truncated)"

    # 持久化 session_id 供下次续接
    if session_id:
        set_session(work_dir, session_id, user_id=user_id, agent="claude")

    return ACPResult(
        success=not is_error and bool(final_result),
        output=final_result or "(no output)",
        agent="claude",
        session_id=session_id,
        sub_steps=sub_steps,
    )
