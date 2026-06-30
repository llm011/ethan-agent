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
    # user_data_dir() 已按当前 profile 解析目录，user_id 仅保留接口兼容。
    return user_data_dir() / "acp_sessions.json"


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


def _session_key(cwd: str, agent: str) -> str:
    """会话键：按 agent + cwd 隔离，避免 claude/codex 在同一目录互相覆盖 session_id
    （两者 id 格式不同，混用会导致 resume 失败）。"""
    return f"{agent}::{os.path.abspath(cwd)}"


def get_session(cwd: str, user_id: str = "", agent: str = "claude") -> Optional[str]:
    """返回该 (agent, cwd) 上次 Coding Agent 会话的 session_id（用于续接多轮）。"""
    return _load_sessions(user_id).get(_session_key(cwd, agent))


def set_session(cwd: str, session_id: str, user_id: str = "", agent: str = "claude") -> None:
    sessions = _load_sessions(user_id)
    sessions[_session_key(cwd, agent)] = session_id
    _save_sessions(sessions, user_id)


def clear_session(cwd: str, user_id: str = "", agent: str = "claude") -> None:
    sessions = _load_sessions(user_id)
    sessions.pop(_session_key(cwd, agent), None)
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

        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        await _terminate_proc(proc)
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


def _codex_item_to_step(item: dict) -> Optional[dict]:
    """把 codex 的一条 item.completed 转成 sub_step（工具调用/命令/改文件）。

    codex exec --json 的 item 形态随版本变化，这里按已知类型尽量提取，未知类型返回 None。
    """
    itype = item.get("type") or ""
    if itype in ("agent_message", "reasoning", "thread.started"):
        return None  # 文本/思考不算工具步骤
    if itype == "command_execution":
        cmd = item.get("command") or item.get("cmd") or ""
        return {
            "tool": "shell",
            "args": _preview(cmd if isinstance(cmd, str) else " ".join(map(str, cmd)), 60),
            "state": "error" if item.get("exit_code") not in (0, None) else "done",
            "duration_ms": item.get("duration_ms"),
            "result_preview": _preview(str(item.get("aggregated_output") or item.get("output") or "")),
        }
    if itype in ("file_change", "patch", "apply_patch"):
        changes = item.get("changes") or item.get("files") or []
        names = ", ".join(str(c.get("path") if isinstance(c, dict) else c) for c in changes) if isinstance(changes, list) else str(changes)
        return {"tool": "edit", "args": _preview(names, 80), "state": "done", "duration_ms": None, "result_preview": ""}
    if itype in ("mcp_tool_call", "tool_call", "function_call"):
        return {
            "tool": item.get("server") or item.get("name") or "tool",
            "args": _preview(str(item.get("arguments") or item.get("input") or ""), 60),
            "state": "error" if item.get("is_error") else "done",
            "duration_ms": item.get("duration_ms"),
            "result_preview": _preview(str(item.get("result") or item.get("output") or "")),
        }
    if itype == "error":
        msg = str(item.get("message") or "")
        # 弃用/配置提示类「error」是警告而非真失败（turn 仍正常完成），不计入步骤，
        # 以免在镜像会话/时间轴里显示成吓人的红色错误（如 codex_hooks deprecated）。
        low = msg.lower()
        if any(k in low for k in ("deprecated", "is no longer supported", "use `[features]")):
            return None
        return {"tool": "error", "args": _preview(msg, 80),
                "state": "error", "duration_ms": None, "result_preview": ""}
    return None


def _codex_item_text(item: dict) -> str:
    """从 agent_message item 里取最终文本。"""
    if (item.get("type") or "") != "agent_message":
        return ""
    return str(item.get("text") or item.get("message") or "").strip()


def _codex_provider_overrides() -> tuple[list[str], dict, str]:
    """返回 (codex -c 覆盖参数, 额外环境变量, 模型名)。

    复用 ethan 的 cliproxy provider（OpenAI 兼容，wire_api=responses），避开
    ~/.codex/config.toml 里可能失效的默认 provider（ChatGPT 登录态过期等）。
    无 cliproxy 配置时返回空 → 退回 codex 自身 config，不破坏既有行为。
    模型默认 gpt-5.5，可用 ETHAN_CODEX_MODEL 覆盖。
    """
    try:
        from ethan.core.config import get_config
        p = get_config().providers.get("cliproxy")
        if not p or not p.api_key or not p.base_url:
            return [], {}, ""
        base = p.base_url.rstrip("/")
        env_key = "ETHAN_CODEX_KEY"
        args = [
            "-c", "model_provider=ethan_codex",
            "-c", 'model_providers.ethan_codex.name="ethan_codex"',
            "-c", f'model_providers.ethan_codex.base_url="{base}"',
            "-c", f'model_providers.ethan_codex.env_key="{env_key}"',
            "-c", 'model_providers.ethan_codex.wire_api="responses"',
        ]
        model = os.environ.get("ETHAN_CODEX_MODEL", "gpt-5.5")
        return args, {env_key: p.api_key}, model
    except Exception:
        return [], {}, ""


async def _run_codex(
    prompt: str,
    cwd: Optional[str] = None,
    timeout: int = 180,
    resume_session_id: Optional[str] = None,
    user_id: str = "",
    on_event: Optional[callable] = None,
) -> ACPResult:
    """Run Codex with `codex exec --json`，解析事件流，支持多轮续接。

    首轮：codex exec --json <prompt> → 从 thread.started 拿 thread_id 作 session_id。
    续轮：codex exec resume <session_id> --json <prompt>。
    session_id 按 (codex, cwd) 持久化，与 Claude Code 路径并存互不覆盖。
    provider 经 _codex_provider_overrides 注入（复用 ethan cliproxy），避开失效的默认 provider。

    on_event 可选：回调函数，每有中间事件调用一次，传 (event_type, data)。
    """
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return ACPResult(success=False, output="codex command not found.", agent="codex")

    work_dir = cwd or str(Path.cwd())
    prov_args, prov_env, model = _codex_provider_overrides()
    model_args = ["-m", model] if model else []
    base_flags = ["--json", "--dangerously-bypass-approvals-and-sandbox", *prov_args, *model_args]
    # --dangerously-bypass-approvals-and-sandbox：非交互委派场景跳审批与沙箱
    if resume_session_id:
        cmd = [codex_bin, "exec", "resume", resume_session_id, *base_flags, prompt]
    else:
        cmd = [codex_bin, "exec", *base_flags, prompt]

    sub_steps: list[dict] = []
    session_id = resume_session_id or ""
    final_result = ""
    is_error = False

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,  # 否则 codex 会阻塞等 stdin
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=work_dir,
            env={**os.environ, **prov_env} if prov_env else None,
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
                t = evt.get("type") or ""
                if t == "thread.started":
                    sid = evt.get("thread_id")
                    if sid:
                        session_id = sid
                elif t == "item.completed":
                    item = evt.get("item") or {}
                    text = _codex_item_text(item)
                    if text:
                        final_result = text  # 末个 agent_message 即最终答复
                    step = _codex_item_to_step(item)
                    if step:
                        sub_steps.append(step)
                        if on_event:
                            await on_event("step", step)
                elif t == "turn.failed":
                    is_error = True
                    err = (evt.get("error") or {}).get("message") or ""
                    if err and not final_result:
                        final_result = f"(codex turn failed) {err}"
                elif t == "error":
                    msg = evt.get("message") or ""
                    if msg and not final_result:
                        final_result = f"(codex error) {msg}"
                # 把 agent_message 的增量文本也推出去，让流式展示完整
                if t == "item.completed" and (evt.get("item") or {}).get("type") == "agent_message":
                    text = _codex_item_text(evt.get("item"))
                    if text and on_event:
                        await on_event("text", text)

        await asyncio.wait_for(_consume(), timeout=timeout)
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        await _terminate_proc(proc)
        # 超时即便优雅终止，该 thread 也可能停在「turn 进行中」而无法 resume；
        # 清掉持久化的 session_id，下次该 (codex, cwd) 自动从新会话开始，避免续接到坏 thread。
        if session_id:
            clear_session(work_dir, user_id=user_id, agent="codex")
        return ACPResult(success=False, output=f"Timed out after {timeout}s",
                         agent="codex", session_id=session_id, sub_steps=sub_steps)
    except Exception as e:
        return ACPResult(success=False, output=f"Error: {e}",
                         agent="codex", session_id=session_id, sub_steps=sub_steps)

    if not final_result and sub_steps:
        final_result = "(Codex 未返回最终文本结果，可展开查看各步骤)"
    if len(final_result) > 12000:
        final_result = final_result[:12000] + "\n...(truncated)"

    if session_id:
        set_session(work_dir, session_id, user_id=user_id, agent="codex")

    return ACPResult(
        success=not is_error and bool(final_result),
        output=final_result or "(no output)",
        agent="codex",
        session_id=session_id,
        sub_steps=sub_steps,
    )


# ── 主入口 ────────────────────────────────────────────────────────────

async def delegate(
    prompt: str,
    cwd: Optional[str] = None,
    prefer: str = "auto",
    timeout: int = 180,
    resume: bool = True,
    reset_session: bool = False,
    user_id: str = "",
    mirror: bool = True,
) -> ACPResult:
    """Delegate a task to the best available local coding agent.

    Args:
        resume: 是否续接该 cwd 上次的 Coding Agent 会话（多轮）。
        reset_session: 清除该 cwd 的会话记忆，从新会话开始。
        mirror: 是否把本次委派落成一条 Ethan 镜像 session（query+回复+步骤可在 web 回看）。
    """
    work_dir = cwd or str(Path.cwd())

    # 解析本次实际使用的 agent 名（供镜像会话标题/归类），不改变下面的分派逻辑。
    if prefer in ("opencode", "codex"):
        agent_name = prefer
    elif shutil.which("claude"):
        agent_name = "claude"
    elif shutil.which("opencode"):
        agent_name = "opencode"
    elif shutil.which("codex"):
        agent_name = "codex"
    else:
        agent_name = "none"

    mirror_session = None
    if mirror and agent_name != "none":
        from ethan.acp.mirror import MirrorSession
        mirror_session = await MirrorSession.start(
            agent=agent_name, task=prompt, cwd=work_dir, user_id=user_id,
        )

    on_event = mirror_session.on_event if mirror_session is not None else None
    result = await _dispatch(
        prompt, work_dir, prefer, timeout, resume, reset_session, user_id, agent_name,
        on_event=on_event,
    )

    if mirror_session is not None:
        await mirror_session.finish(
            result.output, result.sub_steps, is_error=not result.success,
        )
    return result


async def _dispatch(
    prompt: str,
    work_dir: str,
    prefer: str,
    timeout: int,
    resume: bool,
    reset_session: bool,
    user_id: str,
    agent_name: str,
    on_event: Optional[callable] = None,
) -> ACPResult:
    """实际分派到具体 Coding Agent。镜像会话由 delegate() 在外层包裹。"""
    if prefer == "opencode":
        resume_sid = None
        if reset_session:
            clear_session(work_dir, user_id=user_id, agent="opencode")
        elif resume:
            resume_sid = get_session(work_dir, user_id=user_id, agent="opencode")
        return await _run_opencode(
            prompt, cwd=work_dir, timeout=timeout,
            resume_session_id=resume_sid, user_id=user_id, on_event=on_event,
        )
    if prefer == "codex":
        resume_sid = None
        if reset_session:
            clear_session(work_dir, user_id=user_id, agent="codex")
        elif resume:
            resume_sid = get_session(work_dir, user_id=user_id, agent="codex")
        return await _run_codex(
            prompt, cwd=work_dir, timeout=timeout,
            resume_session_id=resume_sid, user_id=user_id, on_event=on_event,
        )

    # 默认优先 Claude Code（支持多轮 + 子步骤）
    if agent_name == "claude":
        resume_sid = None
        if reset_session:
            clear_session(work_dir, user_id=user_id, agent="claude")
        elif resume:
            resume_sid = get_session(work_dir, user_id=user_id, agent="claude")
        return await _run_claude_code(
            prompt, cwd=work_dir, timeout=timeout,
            resume_session_id=resume_sid, user_id=user_id, on_event=on_event,
        )
    elif agent_name == "opencode":
        return await _run_opencode(prompt, cwd=work_dir, timeout=timeout, user_id=user_id, on_event=on_event)
    elif agent_name == "codex":
        return await _run_codex(prompt, cwd=work_dir, timeout=timeout, user_id=user_id, on_event=on_event)
    else:
        return ACPResult(
            success=False,
            output="No coding agent found. Install Claude Code (https://claude.ai/code), OpenCode, or Codex.",
            agent="none",
        )
