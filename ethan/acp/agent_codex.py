"""ACP Codex agent: exec --json event stream, multi-turn session support."""
import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from .models import ACPResult
from .session import clear_session, set_session
from .utils import _preview, _terminate_proc


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
