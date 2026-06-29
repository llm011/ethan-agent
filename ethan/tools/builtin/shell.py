import asyncio
import os

from ethan.tools.base import BaseTool


class ShellTool(BaseTool):
    cacheable = False  # shell 命令有副作用，结果不可缓存
    side_effect = True
    no_compress = True  # 脚本输出（如 query_devices 设备列表）需逐字给模型，压成摘要会丢 entity_id
    name = "shell"
    description = "Execute a shell command and return its output."

    def consent_check(self, command: str = "", **kwargs) -> str | None:
        # shell 可执行任意副作用操作，执行前一律请求授权（同一会话授权过不再弹，见 consent 的 session 记忆）
        return "执行 shell 命令"
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
            # 把 .secrets/*.env 的 KEY=value 注入子进程环境，脚本里可直接用 $KEY，
            # 模型上下文里从不出现明文。注入失败不影响命令执行。
            env = dict(os.environ)
            try:
                from ethan.core.secrets_store import load_secret_env
                env.update(load_secret_env())
            except Exception:
                pass
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace").strip()
            # 截断过长输出
            if len(output) > 8000:
                output = output[:8000] + "\n...(truncated)"
            return output or "(no output)"
        except asyncio.TimeoutError:
            return f"Command timed out after {timeout}s"
