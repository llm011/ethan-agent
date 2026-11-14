"""通过 ACP 协议驱动外部 agent 的内核。

## 为什么这条路更轻

外部 agent（DSH / Claude Code / Pi / Codex / OpenCode）里，**DSH 原生支持 ACP**：

    dsh --profile acp      # 走 Agent Client Protocol stdio

实测握手（2026-11-14）：

    → {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}
    ← {"result":{"agentInfo":{"name":"deepseek-harness-acp","version":"0.0.1"},
                 "agentCapabilities":{...sessionCapabilities:{close,list,resume}}}}

这意味着**不需要为每个 CLI 手写事件解析器**。之前三个 kernel（claude/dsh/pi）
各有一套「读 stdout → 判 JSON → 猜字段」的逻辑，共 990 行，而且每家的 schema
一变就得跟着改（实测踩过：Pi 的 `--mode json` 与 Claude 的 `--output-format json`
参数名不同、事件结构不同）。

走 ACP 之后：
  · 协议是标准化的（agent-client-protocol 0.12.x，项目本来就有这个依赖）
  · 事件类型是 pydantic schema 校验过的（`ToolCallStart` / `AgentMessageChunk` ...）
  · 换 agent 只是换启动命令，代码零改动

## 事件映射：与 acp_server/mapping.py 严格互逆

`ethan/acp_server/` 负责把 ethan 事件**编码成** ACP（server 侧）；
本模块负责把 ACP **解码成** ethan 事件（client 侧）。两者共用同一套 schema，
所以映射是天然互逆的——这也保证了「Ethan 作为 ACP server」和「Ethan 作为 ACP
client」看到的是同一套语义。

    ACP                              →  ethan
    AgentMessageChunk                →  str
    AgentThoughtChunk                →  ThinkingEvent
    ToolCallStart                    →  ToolEvent(state="start")
    ToolCallProgress(completed)      →  ToolEvent(state="done")
    ToolCallProgress(failed)         →  ToolEvent(state="error")
    AgentPlanUpdate                  →  （暂存，供未来 UI 展示计划）
    UsageUpdate                      →  记 token

## 打不平的地方（诚实记录）

| 前端字段 | ACP 有没有 | 处理 |
|---|---|---|
| `tool` / `args` / `state` / `result_preview` | 有 | 直接映射 |
| `result_detail` | 有（`raw_output`） | 直接映射 |
| `duration_ms` | **没有** | client 侧按 tool_call_id 自己计时 |
| `skill_category` | 没有 | 留空（不谎报） |
| `sub_steps`（委派链嵌套） | 没有嵌套概念 | 降级为平铺时间线 |
| `cards`（结构化卡片） | 只有 content 块 | 暂不支持，走文本 |
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
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


@dataclass
class AcpAgentSpec:
    """一个 ACP agent 的启动方式。换 agent 只改这张表的行程。"""

    kind: KernelKind
    display_name: str
    # 启动命令（列表）。cwd 由 KernelRequest.working_dir 决定，不写进命令。
    cmd: list[str]
    # 依赖探测用的可执行名
    binary: str
    # 是否需要注入 Ethan 的 provider 配置（DSH 的 headless/acp profile 默认要
    # DEEPSEEK_API_KEY，用户可能只在 Ethan 里配过）
    inject_provider: bool = False


class AcpClientKernel(KernelRuntime):
    """通用 ACP 客户端内核。子类只需声明 `spec`。"""

    spec: AcpAgentSpec | None = None

    capabilities = KernelCapabilities(
        streaming=True,
        tools=True,
        consent=True,        # ACP 有 request_permission，可以真正对齐授权
        ethan_context=False,  # 外部 agent 有自己的系统提示词与工具集
        resumable=True,       # sessionCapabilities.resume
    )

    def __init__(self) -> None:
        self.last_usage: dict[str, int] = {}
        self._last_plan: list = []

    # 交给 KernelRuntime 的鸭子属性
    @property
    def kind(self) -> KernelKind:  # type: ignore[override]
        return self.spec.kind if self.spec else KernelKind.ETHAN

    @property
    def display_name(self) -> str:  # type: ignore[override]
        return self.spec.display_name if self.spec else "ACP"

    def available(self) -> tuple[bool, str]:
        from ethan.kernel.deps import locate

        if self.spec is None:
            return False, "未配置 ACP agent spec"
        if locate(self.spec.kind) is None:
            return False, f"未安装 {self.spec.binary}"
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
        driver = asyncio.create_task(self._drive(prompt, request, queue))
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, tuple) and item[0] == "__error__":
                    yield f"[{self.display_name} 执行失败] {item[1]}"
                    continue
                yield item
        finally:
            if not driver.done():
                driver.cancel()
                try:
                    await driver
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    async def _drive(self, prompt: str, request: KernelRequest, queue: asyncio.Queue) -> None:
        try:
            await self._run_acp(prompt, request, queue)
        except Exception as e:  # noqa: BLE001
            logger.exception("%s ACP 执行失败", self.display_name)
            queue.put_nowait(("__error__", e))
        finally:
            queue.put_nowait(_DONE)

    # ── ACP 会话 ─────────────────────────────────────────────

    async def _run_acp(
        self, prompt: str, request: KernelRequest, queue: asyncio.Queue
    ) -> None:
        import acp
        from acp.interfaces import Client
        from acp.schema import AllowedOutcome, RequestPermissionResponse, TextContentBlock

        kernel = self
        patch_path, env_extra = ("", {})
        if self.spec and self.spec.inject_provider:
            patch_path, env_extra = self._build_provider_patch()

        class _Client(Client):
            """最小 ACP 客户端：把 update 转成 ethan 事件推进队列。"""

            async def session_update(self, session_id: str, update: Any, **kw: Any) -> None:
                for out in kernel._map_update(update, queue):
                    queue.put_nowait(out)

            async def request_permission(self, session_id, tool_call, options, **kw):
                # 内核模式下默认放行——外部 agent 自己的权限模型我们已经
                # 通过启动参数（--approval-policy / --dangerously-skip-permissions）
                # 交给它了，这里再拦一次只会让流程卡住。
                opt_id = options[0].option_id if options else "allow"
                return RequestPermissionResponse(
                    outcome=AllowedOutcome(outcome="selected", option_id=opt_id)
                )

        cmd = list(self.spec.cmd)
        if patch_path:
            cmd += ["--patch", patch_path]

        cwd = request.working_dir or str(Path.cwd())
        env = dict(os.environ)
        env.update(env_extra)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            conn = acp.connect_to_agent(_Client(), proc.stdin, proc.stdout)
            await conn.initialize(protocol_version=1, client_capabilities=None)
            session = await conn.new_session(cwd=cwd, mcp_servers=[])
            request.session_id = session.session_id
            try:
                await conn.prompt(
                    session_id=session.session_id,
                    prompt=[TextContentBlock(type="text", text=prompt)],
                )
            finally:
                # 关闭会话，避免外部 agent 留着进程
                close = getattr(conn, "close_session", None)
                if close is not None:
                    try:
                        await close(session_id=session.session_id)
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            if proc.returncode is None:
                from ethan.acp.utils import _terminate_proc

                await _terminate_proc(proc)
            if patch_path:
                Path(patch_path).unlink(missing_ok=True)

            # 没拿到任何正文时把 stderr 尾部给出去（凭证类错误走这里）
            if proc.stderr is not None:
                try:
                    err = (await proc.stderr.read()).decode(errors="replace").strip()
                    if err and not self._emitted:
                        queue.put_nowait(f"[{self.display_name}] {err.splitlines()[-1][:300]}")
                except Exception:  # noqa: BLE001
                    pass

    # ── 事件映射 ─────────────────────────────────────────────

    def _map_update(self, update: Any, queue: asyncio.Queue) -> list[Any]:
        """一条 ACP session_update → 0..n 个 ethan 事件。"""
        from ethan.providers.base import ThinkingEvent, ToolEvent

        t = getattr(update, "session_update", None)
        out: list[Any] = []

        if t == "agent_message_chunk":
            text = getattr(getattr(update, "content", None), "text", "") or ""
            if text:
                self._emitted = True
                out.append(text)

        elif t == "agent_thought_chunk":
            text = getattr(getattr(update, "content", None), "text", "") or ""
            out.append(ThinkingEvent(delta=text))

        elif t == "tool_call":
            call_id = getattr(update, "tool_call_id", "") or f"acp-{id(update)}"
            # ACP 的 title 是「工具名: 参数摘要」的合并文本，前端要把两者分开显示，
            # 所以按第一个冒号切；切不出来就整体当工具名。
            title = getattr(update, "title", "") or "tool"
            name, _, args = title.partition(": ")
            # ACP 的 ToolCallStart 有 raw_input（结构化参数）。title 有时只有工具名，
            # 参数全在 raw_input 里——那样前端就看不到「这个工具在干什么」。
            if not args:
                raw = getattr(update, "raw_input", None)
                if isinstance(raw, dict) and raw:
                    args = ", ".join(f"{k}={str(v)[:40]}" for k, v in list(raw.items())[:3])
                elif raw:
                    args = str(raw)[:100]
            self._tool_started[call_id] = time.time()
            self._tool_names[call_id] = name
            out.append(
                ToolEvent(
                    tool_name=name,
                    args_summary=args,
                    state="start",
                    tool_call_id=call_id,
                    entity_type="acp",
                )
            )

        elif t == "tool_call_update":
            call_id = getattr(update, "tool_call_id", "") or f"acp-{id(update)}"
            status = getattr(update, "status", "") or ""
            state = "start" if status == "in_progress" else ("error" if status == "failed" else "done")
            preview = self._extract_content_text(getattr(update, "content", None))
            # ACP 不提供耗时，client 侧按 tool_call_id 自己算
            name = self._tool_names.get(call_id) or getattr(update, "title", "") or "tool"
            if state != "start":
                self._tool_started.pop(call_id, None)
            out.append(
                ToolEvent(
                    tool_name=name,
                    args_summary="",
                    state=state,
                    result_preview=preview,
                    result_detail=preview if len(preview) > 200 else "",
                    tool_call_id=call_id,
                    entity_type="acp",
                )
            )

        elif "plan" in (t or ""):
            # 计划更新：先存下来，未来接 UI（ACP 这里比 Ethan 原生多一个能力）
            entries = getattr(update, "entries", None) or getattr(update, "plan", None)
            if entries:
                self._last_plan = entries
                logger.debug("ACP plan updated: %d entries", len(entries))

        elif t == "usage_update":
            used = getattr(update, "used", 0) or 0
            self.last_usage = {"input": used, "output": 0}

        return out

    @staticmethod
    def _extract_content_text(content: Any) -> str:
        """从 ACP 的 content 列表里拼出文本（结构见 acp_server/mapping.py 的注释）。"""
        if not content:
            return ""
        parts: list[str] = []
        items = content if isinstance(content, list) else [content]
        for item in items:
            inner = getattr(item, "content", None)
            if inner is None:
                continue
            text = getattr(inner, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)

    # ── provider 注入（仅 DSH 这类需要 token 的 agent 用）────────

    def _build_provider_patch(self) -> tuple[str, dict[str, str]]:
        """把 Ethan 的默认 provider 注入成 DSH 的 route。

        DSH 的 profile 默认要 `DEEPSEEK_API_KEY`，而用户可能只在 Ethan 里配过。
        用它提供的 `--patch` 覆盖机制注入，不修改用户的 `~/.dsh` 文件。
        """
        try:
            from ethan.core.config import get_config

            cfg = get_config()
            provider_name, _, model = (cfg.defaults.model or "").partition("/")
            if not provider_name:
                return "", {}
            prov = cfg.providers.get(provider_name)
            if prov is None or not prov.base_url or not prov.api_key:
                return "", {}
        except Exception:
            return "", {}

        key_env = "ETHAN_ACP_PROVIDER_KEY"
        patch = [
            {
                "id": "llm-pi-ai",
                "config": {
                    "providers": {
                        "ethan": {
                            "apiKeyEnv": key_env,
                            "baseURL": prov.base_url.rstrip("/"),
                            "api": "openai-completions",
                            "models": [{"id": model or "default"}],
                        }
                    }
                },
            },
            {"id": "agent-default-model", "config": {"provider": "ethan", "model": model or "default"}},
        ]
        try:
            import tempfile

            import yaml

            fd, path = tempfile.mkstemp(prefix="ethan_acp_patch_", suffix=".yml")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(patch, f, allow_unicode=True)
            return path, {key_env: prov.api_key}
        except Exception:
            return "", {}

    # ── 杂项 ─────────────────────────────────────────────────

    _emitted: bool = False
    _tool_started: dict[str, float] = {}
    # tool_call_id → (工具名, 起始时间)。ToolCallProgress 不带 title，
    # 必须在 start 时记下来，否则 done 事件只能报 "tool"，前端时间线就没名字了。
    _tool_names: dict[str, str] = {}

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


_DONE = object()


# ── 具体 agent 声明 ─────────────────────────────────────────


class DshAcpKernel(AcpClientKernel):
    spec = AcpAgentSpec(
        kind=KernelKind.DSH,
        display_name="DSH",
        cmd=["dsh", "--profile", "acp"],
        binary="dsh",
        inject_provider=True,
    )
