"""ACP Client — 委托复杂编码任务给本地 Coding Agent（Claude Code / OpenCode 等）。

使用 subprocess 调用本地 CLI，收集输出返回给 Ethan。
"""
import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ACPResult:
    success: bool
    output: str
    agent: str


_CODING_COMPLEXITY_SIGNALS = [
    "implement", "refactor", "create", "write a", "build",
    "debug", "fix the bug", "add feature", "重构", "实现", "开发",
    "写一个", "创建", "修复", "新增功能", "优化代码",
]

_SIMPLE_SIGNALS = [
    "explain", "what is", "how does", "describe", "summarize",
    "解释", "什么是", "怎么", "描述", "总结",
]


def is_complex_coding_task(prompt: str) -> bool:
    """Heuristic: decide if this is a complex coding task worth delegating."""
    text = prompt.lower()

    # Simple questions → handle locally
    for sig in _SIMPLE_SIGNALS:
        if sig in text:
            return False

    # Complexity signals
    has_complexity = any(sig in text for sig in _CODING_COMPLEXITY_SIGNALS)
    if not has_complexity:
        return False

    # Code-related keywords (broad)
    has_code_keyword = any(kw in text for kw in [
        "python", "code", "function", "class", "script", "file", "api", "app",
        "test", "module", "database", "server", "client", "代码", "函数", "类",
        "脚本", "接口", "应用", "模块", "数据库",
    ])

    # Medium-length prompts with complexity + code = complex
    if has_complexity and has_code_keyword:
        return True

    # Long prompts with complexity signals are likely complex
    if has_complexity and len(prompt) > 80:
        return True

    return False


async def _run_claude_code(prompt: str, cwd: Optional[str] = None, timeout: int = 120) -> ACPResult:
    """Run Claude Code CLI and capture output."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return ACPResult(success=False, output="claude command not found. Install Claude Code: https://claude.ai/code", agent="claude")

    cmd = [claude_bin, "-p", prompt, "--output-format", "text"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd or str(Path.cwd()),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace").strip()
        if len(output) > 12000:
            output = output[:12000] + "\n...(truncated)"
        return ACPResult(success=proc.returncode == 0, output=output, agent="claude")
    except asyncio.TimeoutError:
        return ACPResult(success=False, output=f"Timed out after {timeout}s", agent="claude")
    except Exception as e:
        return ACPResult(success=False, output=f"Error: {e}", agent="claude")


async def _run_opencode(prompt: str, cwd: Optional[str] = None, timeout: int = 120) -> ACPResult:
    """Run OpenCode CLI and capture output."""
    opencode_bin = shutil.which("opencode")
    if not opencode_bin:
        return ACPResult(success=False, output="opencode command not found.", agent="opencode")

    cmd = [opencode_bin, "run", "--prompt", prompt]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd or str(Path.cwd()),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace").strip()
        return ACPResult(success=proc.returncode == 0, output=output, agent="opencode")
    except asyncio.TimeoutError:
        return ACPResult(success=False, output=f"Timed out after {timeout}s", agent="opencode")
    except Exception as e:
        return ACPResult(success=False, output=f"Error: {e}", agent="opencode")


async def delegate(prompt: str, cwd: Optional[str] = None, prefer: str = "auto", timeout: int = 120) -> ACPResult:
    """Delegate a task to the best available local coding agent."""
    if prefer == "opencode":
        return await _run_opencode(prompt, cwd=cwd, timeout=timeout)

    # Try Claude Code first (default), fall back to opencode
    if shutil.which("claude"):
        return await _run_claude_code(prompt, cwd=cwd, timeout=timeout)
    elif shutil.which("opencode"):
        return await _run_opencode(prompt, cwd=cwd, timeout=timeout)
    else:
        return ACPResult(
            success=False,
            output="No coding agent found. Install Claude Code (https://claude.ai/code) or OpenCode.",
            agent="none",
        )
