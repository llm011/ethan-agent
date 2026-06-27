import asyncio

from ethan.tools.base import BaseTool


class ShellTool(BaseTool):
    cacheable = False  # shell 命令有副作用，结果不可缓存
    side_effect = True
    no_compress = True  # 脚本输出（如 query_devices 设备列表）需逐字给模型，压成摘要会丢 entity_id
    name = "shell"
    description = "Execute a shell command and return its output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 30).",
                "default": 30,
            },
        },
        "required": ["command"],
    }

    async def run(self, command: str, timeout: int = 30) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace").strip()
            # 截断过长输出
            if len(output) > 8000:
                output = output[:8000] + "\n...(truncated)"
            return output or "(no output)"
        except asyncio.TimeoutError:
            return f"Command timed out after {timeout}s"
