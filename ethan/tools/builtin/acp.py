"""ACP Tool — 让 agent 在需要时委托复杂编码任务给本地 Coding Agent。"""
from ethan.tools.base import BaseTool


class DelegateCodingTool(BaseTool):
    name = "delegate_coding"
    description = (
        "Delegate a complex coding task to a local coding agent (Claude Code or OpenCode). "
        "Use this when asked to implement, create, refactor, or debug substantial code. "
        "Do NOT use for simple code questions or short snippets you can answer directly."
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
                "description": "Working directory for the task (default: current directory).",
                "default": "",
            },
        },
        "required": ["task"],
    }

    async def run(self, task: str, working_dir: str = "") -> str:
        from ethan.acp import delegate
        result = await delegate(
            prompt=task,
            cwd=working_dir or None,
            timeout=180,
        )
        if result.success:
            return f"[{result.agent}] {result.output}"
        return f"[{result.agent}] Failed: {result.output}"
