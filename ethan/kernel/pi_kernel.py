"""Pi Coding Agent 内核 —— `pi -p --mode json` 事件流对接到 stream_chat 词表。

## 实测输出结构（pi 0.73.x，2026-11-14 验证）

```
{"type":"session","id":"01a1...","cwd":"..."}
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_start","message":{"role":"user"|"assistant","content":[...]}}
{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"收到"}}
{"type":"message_update","assistantMessageEvent":{"type":"text_end","content":"收到"}}
{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"收到"}],
                                 "usage":{"input":7555,"output":2,...}}}
{"type":"turn_end","message":{...},"toolResults":[]}
{"type":"agent_end","messages":[...]}
```

**注意 `--mode json` 不是 `--output-format json`**——后者是 Claude Code 的参数，
Pi 会直接报 `Unknown option`。这是实际踩过的坑。

## 映射

    message_update + text_delta  →  str（真正的 token 级流式，比 claude -p 更细）
    message_update + text_start  →  ThinkingEvent（模型开始产出，前端显示占位）
    message_end (assistant)      →  从 usage 里取 token 数（可选）
    tool_use / tool_result       →  ToolEvent

⚠️ Pi 的 json 模式把**完整 message 对象**嵌在每个事件里（`partial` / `message`），
一条 `message_update` 可能上千字符。所以只取需要的字段，不要把整行透传出去——
否则同一段文本会被重复发很多遍（text_start/text_delta/text_end 都带着它）。

## 会话续接

`--session <path|id>` 或 `--continue`。用 `--session-id` 传我们记录的 id。
session id 形如 `01a1d8de-...`（UUID），来自 `session` 事件。

## 已知取舍

- `ethan_context=False`：Pi 有自己的系统提示词与技能体系（`--skill`）。
- `consent=False`：Pi 的工具权限模型与 Ethan consent 不同源。
"""
from __future__ import annotations

import asyncio
import json
import logging
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


class PiKernel(KernelRuntime):
    kind = KernelKind.PI
    display_name = "Pi Agent"
    capabilities = KernelCapabilities(
        streaming=True,       # token 级（text_delta）
        tools=True,
        consent=False,
        ethan_context=False,
        resumable=True,       # --session <id>
    )

    cli_binary = "pi"

    def available(self) -> tuple[bool, str]:
        # 走统一的 deps 探测：它会把内核自带 bin 目录补进 PATH，也维护安装说明
        from ethan.kernel.deps import detect

        return detect(self.kind)

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
            except Exception as e:  # noqa: BLE001 - 必须兜住，否则消费者永久阻塞
                logger.exception("Pi 内核执行失败")
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
        # 关键：`--mode json`（不是 --output-format json）
        cmd = [self.cli_binary, "-p", "--mode", "json"]
        if request.session_id and self._looks_like_pi_session(request.session_id):
            cmd += ["--session", request.session_id]
        cmd.append(prompt)

        cwd = request.working_dir or str(Path.cwd())
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        emitted = False
        try:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if not text:
                    continue
                try:
                    evt = json.loads(text)
                except json.JSONDecodeError:
                    # 非 JSON 行（启动诊断等）当纯文本，别吞掉
                    queue.put_nowait(text)
                    emitted = True
                    continue

                for out in self._handle_event(evt, request):
                    if isinstance(out, str) and out.strip():
                        emitted = True
                    queue.put_nowait(out)

            await proc.wait()
            stderr = ""
            if proc.stderr is not None:
                stderr = (await proc.stderr.read()).decode(errors="replace").strip()

            if not emitted:
                # 没有任何可展示内容：把 stderr 尾部给出去，别让用户看空白
                detail = stderr.splitlines()[-1] if stderr else f"exit={proc.returncode}"
                queue.put_nowait(f"[{self.display_name} 退出码 {proc.returncode}] {detail}")
        finally:
            if proc.returncode is None:
                from ethan.acp.utils import _terminate_proc

                await _terminate_proc(proc)

    def _handle_event(self, evt: dict, request: KernelRequest) -> list[Any]:
        """一条 Pi NDJSON 事件 → 0..n 个 stream_chat 词表事件。

        核心纪律：**只取所需字段，绝不透传整个 message 对象**。
        Pi 的 message_update 里嵌着完整 partial message（含 usage/cost），
        透传会让同一段文本重复出现多次。
        """
        t = evt.get("type")

        if t == "session":
            sid = evt.get("id") or ""
            if sid:
                request.session_id = sid  # 供调用方持久化，下次 --session 续接
            return []

        if t == "message_update":
            inner = evt.get("assistantMessageEvent") or {}
            itype = inner.get("type")
            if itype == "text_delta":
                delta = inner.get("delta") or ""
                return [delta] if delta else []
            if itype == "text_start":
                from ethan.providers.base import ThinkingEvent

                return [ThinkingEvent(delta="")]
            # toolcall_start/delta 只是模型产出工具调用的流式片段，
            # 真正能展示的时机是 tool_execution_start/end（见下面两个分支）。
            # 这里不吐事件，避免前端看到「工具开始」但永远等不到「结束」。
            return []

        if t == "tool_execution_start":
            # 实测结构：{"type":"tool_execution_start","toolCallId":"call_00_...",
            #            "toolName":"read","args":{"path":"m.py"}}
            from ethan.providers.base import ToolEvent

            args = evt.get("args") or {}
            summary = ""
            if isinstance(args, dict):
                summary = ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:3])
            return [ToolEvent(
                tool_name=str(evt.get("toolName") or "tool"),
                args_summary=summary,
                state="start",
                tool_call_id=f"pi-{evt.get('toolCallId') or id(evt)}",
                entity_type="pi",
            )]

        if t == "tool_execution_end":
            # 实测结构：{"type":"tool_execution_end","toolCallId":"...","toolName":"read",
            #            "result":{"content":[{"type":"text","text":"..."}]},"isError":false}
            from ethan.acp.utils import _preview
            from ethan.providers.base import ToolEvent

            result = evt.get("result") or {}
            text = ""
            if isinstance(result, dict):
                for c in result.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text += c.get("text") or ""
                if not text:
                    text = str(result.get("text") or result.get("output") or "")
            else:
                text = str(result)
            return [ToolEvent(
                tool_name=str(evt.get("toolName") or "tool"),
                args_summary="",
                state="error" if evt.get("isError") else "done",
                result_preview=_preview(text),
                tool_call_id=f"pi-{evt.get('toolCallId') or id(evt)}",
                entity_type="pi",
            )]

        if t == "message_end":
            # assistant 消息结束：正文已通过 text_delta 流式发出，不再重复吐
            return []

        # turn_end / agent_end / agent_start / turn_start / message_start 等：
        # 它们只是流程标记，正文已经通过 text_delta 流式发出，无需再吐一遍
        if t in (
            "turn_end", "agent_end", "agent_start", "turn_start", "message_start",
            "toolcall_start", "toolcall_delta", "toolcall_end",
        ):
            return []

        logger.debug("pi 未识别事件: %s", t)
        return []

    def _looks_like_pi_session(self, sid: str) -> bool:
        """Pi 的 session id 是 UUID（可能带路径）。不是的话不要传给 --session，
        否则 pi 会报 unknown session 直接失败。"""
        s = (sid or "").strip()
        if len(s) < 8:
            return False
        # 含 / 说明是路径形式，直接可用；纯 UUID 也认
        return "/" in s or s.count("-") >= 4

    def _build_prompt(self, request: KernelRequest) -> str:
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
