"""ClaudeCodeKernel — 用 Claude Code CLI 接管 agent 运行时。

## 怎么接的

`ethan/acp/agent_claude.py` 已经把这件难事做完了：起 `claude -p ... --output-format
stream-json` 子进程、逐行解析 stream-json、把 tool_use / tool_result 配对成 step、
拿到 final result、持久化 session_id 供续接。它通过 `on_event(type, data)` 往外抛
两种事件：`("step", dict)` 和 `("text", str)`。

本内核只做一件事：**把这两种事件翻译成 `Agent.stream_chat` 的词表**，让上游
producers.py → SSE → 前端一行都不用改。

    ACP                           →  stream_chat
    ("text", str)                 →  str
    ("step", {state:"running"})   →  ToolEvent(state="start")
    ("step", {state:"done"})      →  ToolEvent(state="done")
    ("step", {state:"error"})     →  ToolEvent(state="error")

## 实时性

`delegate()` 是「跑完才返回」的，但 `on_event` 在过程中就会被调用。所以不能
等 delegate 返回再吐事件——那样用户要盯着空白等到最后。正确做法是把回调推进
`asyncio.Queue`，`run()` 边收边 yield：delegate 跑在独立 task 里，run() 循环
消费队列。这样工具调用过程是实时可见的。

## 已知取舍（不是 bug）

1. **不走 Ethan 的工具/技能/记忆**。Claude Code 有自己的工具集和系统提示词，
   把 Ethan 的技能注进去会打架（两份 system prompt、两套工具同名不同义）。
   所以 `ethan_context=False`：只把用户原始输入递过去。

2. **不做中途授权**。ACP 用 `--dangerously-skip-permissions` 让 CLI 不询问；
   它的权限模型和 Ethan 的 consent 是两套东西，无法在这层对齐。所以
   `consent=False`——调用方应该只在用户明确知情（比如手动切到该内核）时使用。

3. **流式粒度更粗**。`claude -p` 的 stream-json 不保证 token 级增量，text 事件
   是按 assistant message 粒度到达的。所以首字延迟通常比原生慢，但换来的是
   Claude Code 自己的规划/编辑能力。

4. **cwd 语义**。Codex/Claude 都在 `working_dir` 里跑，后续工具调用（Read/Edit/Bash）
   都是相对它解析。不给就用进程 cwd——这在 web 会话里通常是 Ethan 的安装目录，
   容易误改项目，所以调用方应尽量显式传 `working_dir`。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any, AsyncIterator

from ethan.kernel.runtime import (
    KernelCapabilities,
    KernelContext,
    KernelKind,
    KernelRequest,
    KernelRuntime,
)

logger = logging.getLogger(__name__)

# 事件队列的哨兵：表示 delegate 已结束
_DONE = object()


class ACPKernelBase(KernelRuntime):
    """经 ACP 驱动外部 coding agent CLI 的内核基类。

    Claude / Codex / OpenCode 三者共用同一套 ACP 接口（`ethan.acp.delegate`），
    差别只在 `acp_agent`（传给 delegate 的 prefer 参数）和 CLI 名字。
    """

    acp_agent: str = ""       # 传给 acp.delegate(prefer=...) 的值
    cli_binary: str = ""      # 用于 available() 探测的 CLI 名

    capabilities = KernelCapabilities(
        streaming=True,
        tools=True,
        consent=False,        # 见模块 docstring 取舍 2
        ethan_context=False,  # 见取舍 1
        resumable=True,       # ACP 用 claude --resume / codex resume 续接
    )

    def available(self) -> tuple[bool, str]:
        if not self.cli_binary:
            return False, "未配置 CLI 名"
        if shutil.which(self.cli_binary) is None:
            return False, f"未安装 {self.cli_binary} CLI（{self.install_hint}）"
        return True, ""

    @property
    def install_hint(self) -> str:
        return "见项目文档"

    async def run(
        self,
        request: KernelRequest,
        context: KernelContext | None = None,
    ) -> AsyncIterator[Any]:
        # 延迟导入：acp 模块本身会拉不少东西，不必让 kernel 包导入时就付出代价
        from ethan.acp import delegate
        from ethan.providers.base import ToolEvent

        ok, reason = self.available()
        if not ok:
            # 可用性应该在调用前由 registry.resolve() 过滤掉；兜底给一条明确错误
            yield f"[内核不可用] {reason}"
            return

        prompt = self._build_prompt(request)
        if not prompt:
            yield "[空输入] 没有可执行的内容"
            return

        queue: asyncio.Queue = asyncio.Queue()
        # step dict 的 id() → tool_call_id，用于把 running/done 两次回调配成一对
        pending_ids: dict[int, str] = {}
        tool_seq = 0
        streamed_text: list[str] = []

        async def _on_event(event_type: str, data: Any) -> None:
            """ACP 回调 → 事件队列。必须是非阻塞的（用 put_nowait）。"""
            nonlocal tool_seq
            if event_type == "text":
                if data:
                    text = str(data)
                    streamed_text.append(text)
                    queue.put_nowait(text)
                return
            if event_type != "step" or not isinstance(data, dict):
                return

            # running → start（前端开始转圈）；done/error 原样映射
            raw_state = data.get("state", "done")
            mapped_state = "start" if raw_state == "running" else raw_state

            key = id(data)
            if mapped_state == "start":
                tool_seq += 1
                call_id = f"acp-{tool_seq}"
                pending_ids[key] = call_id
            else:
                call_id = pending_ids.pop(key, f"acp-{key}")

            queue.put_nowait(
                ToolEvent(
                    tool_name=data.get("tool", "tool"),
                    args_summary=data.get("args", "") or "",
                    state=mapped_state,
                    result_preview=data.get("result_preview", "") or "",
                    tool_call_id=call_id,
                    entity_type="acp",
                    # 注意：ToolEvent 没有 duration_ms 字段——耗时由上层
                    # stream_collector 按 start/done 时间戳自己算（见
                    # ethan/core/stream_collector.py:137）。这里不要加。
                )
            )

        async def _drive() -> None:
            """跑 delegate，结束时投哨兵。异常也转成事件，不让 run() 卡住。"""
            try:
                result = await delegate(
                    prompt=prompt,
                    cwd=request.working_dir or None,
                    prefer=self.acp_agent,
                    timeout=self._timeout(request),
                    resume=True,
                    reset_session=False,
                    user_id=request.user_id,
                    mirror=False,  # 内核模式下不落镜像会话，避免和主会话重复
                    on_event=_on_event,
                )
                queue.put_nowait(("__result__", result))
            except Exception as e:  # noqa: BLE001 - 必须兜住，否则消费者永久阻塞
                logger.exception("%s 内核执行失败", self.display_name)
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
                    if tag == "__result__":
                        # 流式已经吐过内容就不再重复输出最终文本，否则用户会看到两遍
                        already = "".join(streamed_text).strip()
                        out = (payload.output or "").strip()
                        if out and not already:
                            yield payload.output
                        elif out and already and out not in already:
                            # CLI 的 result 比流式 text 更完整时，补上差额部分
                            leftover = out[len(already):] if out.startswith(already) else ""
                            if leftover.strip():
                                yield leftover
                        if not payload.success and not out and not already:
                            yield f"[{self.display_name}] 任务未成功完成（无输出）"
                        continue
                yield item
        finally:
            # 调用方中途取消（客户端断开）时，别把子进程晾在那儿
            if not driver.done():
                driver.cancel()
                try:
                    await driver
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    def _build_prompt(self, request: KernelRequest) -> str:
        """把消息历史压成单条 prompt。

        外部 CLI 每次 `-p` 是无状态调用，多轮历史必须自己拼进去。ACP 层的
        `--resume` 续接的是「同一个 CLI 会话自己的上下文」，不能替代我们这边
        按 request.messages 组织的对话——所以两个都用：历史展开 + resume 保留
        CLI 侧上一轮的工具上下文。
        """
        msgs = request.messages or []
        if not msgs:
            return ""

        # 只取 user/assistant 的文本；tool 消息是 Ethan 侧的中间产物，喂给 CLI 会干扰
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
        # 单轮直接用原文，避免给 CLI 加无谓前缀干扰理解
        if len(turns) == 1:
            return turns[0]
        return "以下是对话历史，请接着回答最后一条用户消息：\n\n" + "\n\n".join(turns)

    def _timeout(self, request: KernelRequest) -> int:
        # coding 任务本来就慢，给足时间；普通对话也别短到秒退
        return 300 if (request.task_kind or "") == "coding" else 180


class ClaudeCodeKernel(ACPKernelBase):
    kind = KernelKind.CLAUDE_CODE
    display_name = "Claude Code"
    acp_agent = "claude"
    cli_binary = "claude"

    @property
    def install_hint(self) -> str:
        return "npm i -g @anthropic-ai/claude-code"
