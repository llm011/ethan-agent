"""ACP Client — 委托复杂编码任务给本地 Coding Agent（Claude Code / OpenCode / Codex）。

通过 subprocess 调用本地 CLI，收集输出返回给 Ethan。

多轮对话：Claude Code 支持 `--resume <session_id>` 续接上次会话。Ethan 按
「用户 × 工作目录」持久化 session_id，连续的 delegate_coding 调用会自动续接同一会话。

结构化输出：Claude Code 用 `--output-format stream-json` 输出 NDJSON 事件流，
解析出每次工具调用（sub_steps）和最终结果，便于 Web UI 折叠展示。
"""
import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ethan.core.paths import user_data_dir


@dataclass
class ACPResult:
    success: bool
    output: str
    agent: str
    session_id: str = ""
    sub_steps: list = field(default_factory=list)


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


# ── 会话持久化 ────────────────────────────────────────────────────────

def _sessions_path(user_id: str = "") -> Path:
    return user_data_dir(user_id) / "acp_sessions.json"


def _load_sessions(user_id: str = "") -> dict:
    p = _sessions_path(user_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_sessions(sessions: dict, user_id: str = "") -> None:
    p = _sessions_path(user_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_session(cwd: str, user_id: str = "") -> Optional[str]:
    """返回该 cwd 上次 Coding Agent 会话的 session_id（用于 --resume）。"""
    return _load_sessions(user_id).get(os.path.abspath(cwd))


def set_session(cwd: str, session_id: str, user_id: str = "") -> None:
    sessions = _load_sessions(user_id)
    sessions[os.path.abspath(cwd)] = session_id
    _save_sessions(sessions, user_id)


def clear_session(cwd: str, user_id: str = "") -> None:
    sessions = _load_sessions(user_id)
    sessions.pop(os.path.abspath(cwd), None)
    _save_sessions(sessions, user_id)


# ── 参数摘要 ──────────────────────────────────────────────────────────

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


# ── Claude Code（stream-json 多轮 + 子步骤解析）────────────────────────

async def _run_claude_code(
    prompt: str,
    cwd: Optional[str] = None,
    timeout: int = 180,
    resume_session_id: Optional[str] = None,
    user_id: str = "",
) -> ACPResult:
    """Run Claude Code with stream-json output, parse sub-steps and final result."""
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

        async def _read_lines():
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line

        async for line in _read_lines():
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
            elif t == "result":
                final_result = evt.get("result", "") or ""
                sid = evt.get("session_id")
                if sid:
                    session_id = sid
                is_error = bool(evt.get("is_error"))
                # subtype=success/max_tokens/error 等

        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
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
        set_session(work_dir, session_id, user_id=user_id)

    return ACPResult(
        success=not is_error and bool(final_result),
        output=final_result or "(no output)",
        agent="claude",
        session_id=session_id,
        sub_steps=sub_steps,
    )


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


# ── OpenCode / Codex（轻量文本输出，无子步骤）─────────────────────────

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


async def _run_codex(prompt: str, cwd: Optional[str] = None, timeout: int = 120) -> ACPResult:
    """Run Codex CLI and capture output."""
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return ACPResult(success=False, output="codex command not found.", agent="codex")

    cmd = [codex_bin, "exec", prompt]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd or str(Path.cwd()),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace").strip()
        return ACPResult(success=proc.returncode == 0, output=output, agent="codex")
    except asyncio.TimeoutError:
        return ACPResult(success=False, output=f"Timed out after {timeout}s", agent="codex")
    except Exception as e:
        return ACPResult(success=False, output=f"Error: {e}", agent="codex")


# ── 主入口 ────────────────────────────────────────────────────────────

async def delegate(
    prompt: str,
    cwd: Optional[str] = None,
    prefer: str = "auto",
    timeout: int = 180,
    resume: bool = True,
    reset_session: bool = False,
    user_id: str = "",
) -> ACPResult:
    """Delegate a task to the best available local coding agent.

    Args:
        resume: 是否续接该 cwd 上次的 Claude Code 会话（多轮）。
        reset_session: 清除该 cwd 的会话记忆，从新会话开始。
    """
    work_dir = cwd or str(Path.cwd())

    if prefer == "opencode":
        return await _run_opencode(prompt, cwd=work_dir, timeout=timeout)
    if prefer == "codex":
        return await _run_codex(prompt, cwd=work_dir, timeout=timeout)

    # 默认优先 Claude Code（支持多轮 + 子步骤）
    if shutil.which("claude"):
        resume_sid = None
        if reset_session:
            clear_session(work_dir, user_id=user_id)
        elif resume:
            resume_sid = get_session(work_dir, user_id=user_id)
        return await _run_claude_code(
            prompt, cwd=work_dir, timeout=timeout,
            resume_session_id=resume_sid, user_id=user_id,
        )
    elif shutil.which("opencode"):
        return await _run_opencode(prompt, cwd=work_dir, timeout=timeout)
    elif shutil.which("codex"):
        return await _run_codex(prompt, cwd=work_dir, timeout=timeout)
    else:
        return ACPResult(
            success=False,
            output="No coding agent found. Install Claude Code (https://claude.ai/code), OpenCode, or Codex.",
            agent="none",
        )
