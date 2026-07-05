"""ACP utility functions: process termination, argument summarization, text preview."""
import asyncio


async def _terminate_proc(proc, grace: float = 8.0) -> None:
    """优雅终止子进程：先 SIGTERM 给收尾机会，超过 grace 秒仍活着再 SIGKILL。

    动机：codex/opencode 把「turn 是否进行中」记在自己的 session 文件里。直接 kill()
    会让该 thread 停在 'turn in progress'，导致之后手动 `codex exec resume` /
    交互式 `/resume` 被拒（'/resume is disabled while a task is in progress'）。
    SIGTERM 给 CLI 一个把 turn 标记为中断、干净落盘的机会，降低污染概率。
    """
    if proc.returncode is not None:
        return
    try:
        proc.terminate()  # SIGTERM
    except Exception:
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
        return
    except (asyncio.TimeoutError, Exception):
        pass
    try:
        proc.kill()  # SIGKILL 兜底
        await asyncio.wait_for(proc.wait(), timeout=3)
    except Exception:
        pass


def _summarize_args(tool_input: dict) -> str:
    """把 Coding Agent 的工具输入压成短摘要，用于 Web UI 时间轴。"""
    if not isinstance(tool_input, dict) or not tool_input:
        return ""
    parts = []
    for k, v in list(tool_input.items())[:2]:
        s = str(v).replace("\n", " ")
        if len(s) > 40:
            s = s[:40] + "…"
        parts.append(f"{k}={s}")
    return ", ".join(parts)


def _preview(text: str, limit: int = 120) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text[:limit] + "…" if len(text) > limit else text
