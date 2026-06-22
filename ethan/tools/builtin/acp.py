"""ACP Tool — 让 agent 在需要时委托复杂编码任务给本地 Coding Agent。"""
from ethan.tools.base import BaseTool, ToolResult


class DelegateCodingTool(BaseTool):
    name = "delegate_coding"
    # 委派给外部 Coding Agent，有副作用（写文件、改代码），不可缓存
    cacheable = False
    # 复杂编码任务通常需要全量工具上下文，不在 fast path 加载
    fast_path = False
    description = (
        "Delegate a complex coding task to a local coding agent (Claude Code / OpenCode / Codex). "
        "Use this when asked to implement, create, refactor, or debug substantial code in a project. "
        "Do NOT use for simple code questions or short snippets you can answer directly. "
        "Consecutive calls in the same working_dir automatically resume the same coding session (multi-turn). "
        "Set reset_session=true to start a fresh session instead of resuming."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The full coding task description to delegate.",
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for the task (default: current directory). Use the relevant project root so the coding agent has full context.",
                "default": "",
            },
            "reset_session": {
                "type": "boolean",
                "description": "If true, do not resume the previous coding session in this directory; start fresh. Use this when switching to an unrelated task.",
                "default": False,
            },
        },
        "required": ["task"],
    }

    def __init__(self, user_id: str = "") -> None:
        self._user_id = user_id

    async def run(self, task: str, working_dir: str = "", reset_session: bool = False) -> ToolResult:
        from ethan.acp import delegate
        result = await delegate(
            prompt=task,
            cwd=working_dir or None,
            timeout=180,
            reset_session=reset_session,
            user_id=self._user_id,
        )
        prefix = f"[{result.agent}]"
        if result.session_id:
            prefix += f"(session={result.session_id[:8]})"
        content = f"{prefix} {result.output}" if result.success else f"{prefix} Failed: {result.output}"
        return ToolResult(
            tool_call_id="",
            content=content,
            is_error=not result.success,
            sub_steps=result.sub_steps,
        )
