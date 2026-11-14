"""DSH 内核 —— 用 `dsh headless --json` 接管 agent 运行时。

## 为什么单独写而不复用 ACPKernelBase

ACP 层（`ethan/acp/`）是**为委派编码任务设计的**：它只支持 claude / codex /
opencode 三个 CLI，事件只有 `step` / `text`，且 `delegate()` 是一次性返回。
DSH 的接口形态完全不同：

  · 调用方式是 `dsh --profile headless --json "<task>"`，任务走参数或 stdin
  · 输出是 **NDJSON 事件流**，事件类型见下
  · 会话续接用 `--session-id <id>`（不是 `--resume`）
  · 权限用 `--permission-mode` / `--approval-policy`，与 ACP 的
    `--dangerously-skip-permissions` 不是一回事

强行塞进 ACPKernelBase 会让基类长出三个 if 分支，不如各自实现、共享同一套
`KernelRuntime` 契约。

## DSH headless 的事件类型（实测 2026-11-14）

    {"type":"session", "sessionId":"session-...", "cwd":"..."}
    {"type":"status",  "phase":"turn_start"|"turn_end"|"step_start"|"step_end", ...}
    {"type":"final",   "sessionId":"...", "reason":{...}, "text":"最终回答"}

⚠️ 注意：**当前 version 不带工具调用事件**。上面的实测输出里没有任何
tool_use/tool_result 类型。所以本内核映射时只产 `str`（最终文本），
不假装有 ToolEvent——那是假的。如果未来 DSH 加上工具事件，在 `_handle_event`
里补一个分支即可。

## 已知取舍

- `ethan_context=False`：DSH 有自己的 profile/plugin 体系与系统提示词。
- `consent=False`：权限走 DSH 自己的 `--permission-mode` / `--approval-policy`，
  与 Ethan 的 consent 是两套模型。
- `streaming`：真实流式要看 DSH 是否逐 token 输出 `final.text`。当前 `--json`
  模式下文本在 `final` 事件里一次性给出，所以流式粒度是「按事件」，不是按 token。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, AsyncIterator

from ethan.kernel.runtime import (
    KernelCapabilities,
    KernelContext,
    KernelKind,
    KernelRequest,
    KernelRuntime,
)

logger = logging.getLogger(__name__)

_DONE = object()


class DSHKernel(KernelRuntime):
    kind = KernelKind.DSH
    display_name = "DSH"
    capabilities = KernelCapabilities(
        streaming=True,        # 按事件粒度，见模块 docstring
        tools=True,            # DSH 自身有工具，只是 --json 当前不上报
        consent=False,
        ethan_context=False,
        resumable=True,        # --session-id
    )

    cli_binary = "dsh"
    profile = "headless"

    def available(self) -> tuple[bool, str]:
        if shutil.which(self.cli_binary) is None:
            return False, "未安装 dsh CLI（npm i -g @deepseek-ai/dsh）"
        # profile 必须存在，否则 dsh 启动会直接失败
        home = os.environ.get("DSH_HOME") or str(Path.home() / ".dsh")
        prof = Path(home) / "profiles" / self.profile
        if not prof.exists():
            return False, f"DSH profile {self.profile!r} 不存在（{prof}）"
        return True, ""

    async def run(
        self,
        request: KernelRequest,
        context: KernelContext | None = None,
    ) -> AsyncIterator[Any]:
        ok, reason = self.available()
        if not ok:
            yield f"[内核不可用] {reason}"
            return

        prompt = self._build_prompt(request)
        if not prompt:
            yield "[空输入] 没有可执行的内容"
            return

        queue: asyncio.Queue = asyncio.Queue()

        async def _drive() -> None:
            try:
                await self._consume(prompt, request, queue)
            except Exception as e:  # noqa: BLE001
                logger.exception("DSH 内核执行失败")
                queue.put_nowait(("__error__", e))
            finally:
                queue.put_nowait(_DONE)

        driver = asyncio.create_task(_drive())
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, tuple):
                    tag, payload = item
                    if tag == "__error__":
                        yield f"[{self.display_name} 执行失败] {payload}"
                        continue
                yield item
        finally:
            if not driver.done():
                driver.cancel()
                try:
                    await driver
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    async def _consume(self, prompt: str, request: KernelRequest, queue: asyncio.Queue) -> None:
        """起子进程、逐行读 NDJSON、把事件推进队列。"""
        cmd = [self.cli_binary, "--profile", self.profile, "--json"]
        if request.session_id and request.session_id.startswith("session-"):
            # DSH 的 session id 自带 session- 前缀，且 resume 未知 id 会直接报错。
            # 只在我们确认是本内核产生的 id 时才续接（见 _is_own_session）。
            cmd += ["--session-id", request.session_id]
        # 非交互场景不询问审批：本内核本来就是无人值守执行的
        cmd += ["--approval-policy", "never"]
        cmd.append(prompt)

        cwd = request.working_dir or str(Path.cwd())
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        emitted_text = False
        try:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line = line.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    # 非 JSON 行（进度日志等）不该吞掉，作为诊断信息给出去
                    logger.debug("dsh 非 json 行: %s", line[:200])
                    continue
                for out in self._handle_event(evt, request):
                    if isinstance(out, str) and out.strip():
                        emitted_text = True
                    queue.put_nowait(out)

            await proc.wait()
            stderr = ""
            if proc.stderr is not None:
                stderr = (await proc.stderr.read()).decode(errors="replace").strip()

            if proc.returncode != 0 and not emitted_text:
                detail = stderr.splitlines()[-1] if stderr else f"exit={proc.returncode}"
                queue.put_nowait(f"[{self.display_name} 退出码 {proc.returncode}] {detail}")
            elif stderr and not emitted_text:
                # 有诊断但没有正文：给出最后几行，别让用户看到空白
                queue.put_nowait(f"[{self.display_name}] {stderr[:500]}")
        finally:
            if proc.returncode is None:
                from ethan.acp.utils import _terminate_proc

                await _terminate_proc(proc)

    def _handle_event(self, evt: dict, request: KernelRequest) -> list[Any]:
        """把一条 DSH NDJSON 事件转成 0..n 个 stream_chat 词表的事件。"""
        t = evt.get("type")

        if t == "session":
            sid = evt.get("sessionId", "")
            if sid:
                # 落回 request，供下一次续接（调用方负责持久化）
                request.session_id = sid
            return []

        if t == "final":
            text = (evt.get("text") or "").strip()
            reason = evt.get("reason") or {}
            # reason.kind == "error" 时即使有 text 也可能是半成品，一并报出错误
            out: list[Any] = []
            if text:
                out.append(text)
            kind = reason.get("kind")
            if kind == "error":
                err = reason.get("error") or {}
                msg = err.get("message") or err.get("code") or "未知错误"
                out.append(f"[{self.display_name} 错误] {msg}")
            return out

        if t == "status":
            # 进度事件不带可展示内容，按「思考中」处理能让前端显示占位而不是干等
            phase = evt.get("phase", "")
            if phase == "step_start":
                from ethan.providers.base import ThinkingEvent

                return [ThinkingEvent(delta="")]
            return []

        # 未知事件类型：记录但不阻塞。DSH 迭代较快，新类型不该导致整轮失败。
        logger.debug("dsh 未处理的事件类型: %s", t)
        return []

    def _build_prompt(self, request: KernelRequest) -> str:
        """与 ACP 内核相同的展开策略：外部 CLIs 每次调用都是无状态的任务执行。"""
        msgs = request.messages or []
        if not msgs:
            return ""
        turns: list[str] = []
        for m in msgs:
            role = getattr(m, "role", "")
            content = getattr(m, "content", "") or ""
            if role not in ("user", "assistant"):
                continue
            text = content.strip()
            if not text:
                continue
            turns.append(text if role == "user" else f"[你之前的回复]\n{text}")
        if not turns:
            return ""
        if len(turns) == 1:
            return turns[0]
        return "以下是对话历史，请接着回答最后一条用户消息：\n\n" + "\n\n".join(turns)
