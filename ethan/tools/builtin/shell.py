import asyncio
import os
import re

from ethan.tools.base import BaseTool

# 高危命令模式：命中则每次都重新询问授权，且不计入会话放行（即使本会话已授权过 shell）。
# 目标是拦住「一次授权 = 整个会话任意高危命令」最坏情况，日常命令仍走会话记忆免问。
_DANGEROUS_PATTERNS = [
    r'\brm\s+(?:-\w*\s+)*-\w*[rf]',          # rm -rf / rm -r -f / rm -fr 等
    r'\b(?:sudo|doas)\b',                      # 提权
    r'\bmkfs\b|\bfdisk\b|\bparted\b',          # 格式化/分区
    r'\bdd\b\s+.*\bof=',                       # dd 写盘
    r'>\s*/dev/|>\s*/etc/|>\s*/sys/|>\s*/boot/',  # 覆写系统/设备文件
    r'\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b',  # 下载管道执行
    r'\beval\b|\bsource\s+/dev/stdin',          # eval / 执行 stdin
    r'\bchmod\s+(?:-\w+\s+)*0?777\b|\bchown\s+-\w*R',  # 危险权限/递归改属主
    r':\(\)\s*\{.*\|.*&.*\}',                   # fork bomb
    r'\bgit\b.*\b(?:reset\s+--hard|clean\s+-\w*[fd]|push\s+.*--force|push\s+.*-f)\b',  # 破坏性 git
]
_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS))


class ShellTool(BaseTool):
    cacheable = False  # shell 命令有副作用，结果不可缓存
    side_effect = True
    no_compress = True  # 脚本输出（如 query_devices 设备列表）需逐字给模型，压成摘要会丢 entity_id
    name = "shell"
    description = "Execute a shell command and return its output."

    def consent_check(self, command: str = "", **kwargs) -> str | None:
        # shell 可执行任意副作用操作，执行前请求授权。
        if _DANGEROUS_RE.search(command or ""):
            # 高危命令：文案标红提示，且每次都问（见 consent_always）
            return f"⚠️ 高危 shell 命令，请确认：{command[:200]}"
        # 普通命令：文案显式告知 scope 是会话级，避免用户以为只授了卡片上那一条
        return "执行 shell 命令（授权后本会话内的所有 shell 命令都不再询问）"

    def consent_always(self, command: str = "", **kwargs) -> bool:
        # 高危命令始终重新询问，即使本会话已授权过 shell，也不计入会话放行
        return bool(_DANGEROUS_RE.search(command or ""))
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
            # 不截断，让模型自己判断哪些有用（shell 有 no_compress=True，不会被压缩）
            return output or "(no output)"
        except asyncio.TimeoutError:
            return f"Command timed out after {timeout}s"
