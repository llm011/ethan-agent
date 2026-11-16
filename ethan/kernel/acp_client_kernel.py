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


def local_port() -> int:
    """推断当前进程实际在监听的端口。

    不能只读 `cfg.server.port`：那是**主实例**的配置（通常 8900），
    而开发/测试实例可能跑在别的端口（如 8910），配置里没有这个信息。
    优先用 api.py 记录的运行时绑定地址，再退到配置，最后 8900。

    放在模块级而不是类方法：Claude/Codex 内核走的是另一个基类
    （ACPKernelBase），它们也需要这个能力。
    """
    try:
        from ethan.interface.api import _SERVER_BIND

        port = _SERVER_BIND[1]
        if port:
            return int(port)
    except Exception:
        pass
    try:
        from ethan.core.config import get_config

        return int(getattr(get_config().server, "port", 8900) or 8900)
    except Exception:
        return 8900


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
        # DSH 支持 ACP 的 mcp_servers 参数，实测能把 Ethan 的 58 个工具挂上去
        shares_ethan_tools=True,
    )

    def __init__(self) -> None:
        self.last_usage: dict[str, int] = {}
        self._last_plan: list = []
        self._emitted: bool = False
        self._tool_started: dict[str, float] = {}
        self._tool_names: dict[str, str] = {}
        self._tool_args: dict[str, str] = {}

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

        prompt, matched_skills = self._prepare_prompt(request, context)
        if not prompt:
            yield "[空输入] 没有可执行的内容"
            return

        skills_evt = self._record_matched_skills(matched_skills, context)
        if skills_evt is not None:
            yield skills_evt

        # 单例跨轮复用：每轮开始重置本次流式跟踪状态
        self._emitted = False
        self._tool_started.clear()
        self._tool_names.clear()
        self._tool_args.clear()

        queue: asyncio.Queue = asyncio.Queue()
        driver = asyncio.create_task(self._drive(prompt, request, queue))
        # 活性检测：外部内核**不走 Ethan 的 LoopMonitor**——那个熔断器在
        # Agent.stream_chat 内部，内核模式下根本不会执行。所以 DSH/Claude 卡住时
        # Ethan 侧完全无感知，只能等整轮 timeout（180-300s）才报错。
        #
        # 这里补一层：超过 IDLE_TIMEOUT 秒没收到任何事件，就主动判定卡死。
        # 阈值取 120s 而不是 30s——外部 CLI 在"思考 + 跑工具"期间本来就可能长时间
        # 安静（比如跑一个 60 秒的构建），误判比晚报更糟。
        idle_timeout = self._idle_timeout(request)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
                except asyncio.TimeoutError:
                    logger.warning(
                        "%s 内核 %ds 无任何事件，判定卡死", self.display_name, idle_timeout
                    )
                    yield (
                        f"[{self.display_name} 已 {idle_timeout} 秒没有任何输出，"
                        "已中止本轮。外部内核不受 Ethan 的循环熔断保护，"
                        "长时间无响应通常是它自己的 CLI 卡住了（可看后端日志确认）。]"
                    )
                    break
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
                # 交给它了，这里再拦一次只会让流程卡住。
                # 优先选显式的 allow 选项，防止某些 agent 把 reject 排在第一位。
                allow = next(
                    (
                        o
                        for o in (options or [])
                        if getattr(o, "kind", "") in ("allow_once", "allow_always")
                    ),
                    None,
                )
                chosen = allow or (options[0] if options else None)
                opt_id = chosen.option_id if chosen is not None else "allow"
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
            # 把 Ethan 的工具挂给外部内核。
            #
            # 这是「内核作为 Ethan 的心脏驱动它干活」的落点：换掉的是大脑
            # （规划/推理），不该丢掉手脚（工具/技能）。ACP 的 mcp_servers 是
            # **每次 new_session 的参数**，不写入外部 agent 的任何配置文件——
            # 实测验证过：注入后 dsh 自带的 22 个工具全在，只是多出带
            # `mcp__ethan__*` 前缀的那批；不用 Ethan 直接跑 dsh 完全不受影响。
            mcp_servers = self._build_mcp_servers()
            session = await conn.new_session(cwd=cwd, mcp_servers=mcp_servers)
            # 写到独立字段，**不要改 request.session_id**（那是 Ethan 自己的会话 id）
            request.kernel_session_id = session.session_id
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
            name, args = self._parse_tool_title_and_args(
                getattr(update, "title", "") or "tool",
                getattr(update, "raw_input", None),
            )
            if call_id not in self._tool_started:
                self._tool_started[call_id] = time.time()
                self._tool_names[call_id] = name
                self._tool_args[call_id] = args
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
            # OpenCode 等 ACP 服务端会先发 tool_call(pending)，再发多次
            # tool_call_update(in_progress)，且参数常在 in_progress 时才填进来。
            # 若已发过 start，不能再重复 emit start——否则 StreamCollector 会追加
            # 永远关不掉的幽灵 running 步骤。
            if status in ("pending", "in_progress"):
                raw = getattr(update, "raw_input", None)
                if call_id in self._tool_started:
                    if not self._tool_args.get(call_id) and raw:
                        _, rich_args = self._parse_tool_title_and_args(
                            self._tool_names.get(call_id, "tool"), raw
                        )
                        if rich_args:
                            self._tool_args[call_id] = rich_args
                    return out
                name, args = self._parse_tool_title_and_args(
                    self._tool_names.get(call_id) or getattr(update, "title", "") or "tool",
                    raw,
                )
                self._tool_started[call_id] = time.time()
                self._tool_names[call_id] = name
                self._tool_args[call_id] = args
                out.append(
                    ToolEvent(
                        tool_name=name,
                        args_summary=args,
                        state="start",
                        tool_call_id=call_id,
                        entity_type="acp",
                    )
                )
            else:
                state = "error" if status == "failed" else "done"
                preview = self._extract_content_text(getattr(update, "content", None))
                # ACP 不提供耗时，client 侧按 tool_call_id 自己算
                name = self._tool_names.pop(call_id, "") or getattr(update, "title", "") or "tool"
                saved_args = self._tool_args.pop(call_id, "")
                self._tool_started.pop(call_id, None)
                out.append(
                    ToolEvent(
                        tool_name=name,
                        args_summary=saved_args,
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
    def _parse_tool_title_and_args(title: str, raw_input: Any) -> tuple[str, str]:
        """从 ACP 的 title / raw_input 拆出 (tool_name, args_summary)。"""
        name, _, args = (title or "tool").partition(": ")
        if not args and raw_input:
            if isinstance(raw_input, dict):
                args = ", ".join(
                    f"{k}={str(v)[:40]}" for k, v in list(raw_input.items())[:3]
                )
            else:
                args = str(raw_input)[:100]
        return name, args

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

    # ── 工具注入：把 Ethan 的工具挂给外部内核 ──────────────────

    def _build_mcp_servers(self) -> list:
        """构造指向 Ethan `/kernel-tools` 的 MCP server 声明。

        返回空列表的条件（宁可不开也不开错）：
          · 配置里显式关掉了共享（`defaults.kernel_share_tools = "off"`）
          · 拿不到本机服务地址 / api key

        地址取 `network.base_url`（服务对外可达地址）。没有时退到
        `http://127.0.0.1:<port>`——外部内核跑在同一台机器上，回环足够。
        """
        from acp.schema import HttpHeader, HttpMcpServer

        try:
            from ethan.core.config import get_config

            cfg = get_config()
            share = getattr(cfg.defaults.kernel, "share_tools", "all") or "all"
            if share == "off":
                return []

            base = (getattr(cfg.network, "base_url", "") or "").rstrip("/")
            if not base:
                base = f"http://127.0.0.1:{self._local_port()}"

            # headers 必须是 HttpHeader 模型，不能传 (name, value) 元组——
            # 否则 pydantic 校验失败，整个 try 被兜住，表现为「静默不注入」。
            headers = []
            api_key = getattr(cfg.network, "mcp_api_key", "") or ""
            if api_key:
                headers.append(
                    HttpHeader(name="Authorization", value=f"Bearer {api_key}")
                )

            return [
                HttpMcpServer(
                    type="http",
                    name="ethan",
                    url=f"{base}/kernel-tools/",
                    headers=headers,
                )
            ]
        except Exception:
            logger.warning("构造 Ethan MCP server 声明失败，本次不注入工具", exc_info=True)
            return []

    @staticmethod
    def _local_port() -> int:
        return local_port()

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

    def _idle_timeout(self, request: KernelRequest) -> int:
        """多久没事件算卡死（秒）。

        外部内核不走 Ethan 的 LoopMonitor，这是唯一的活性兜底。
        coding 任务放宽到 300s：跑构建/测试时长时间无输出是正常的。
        """
        return 300 if (request.task_kind or "") == "coding" else 120

    # `_build_prompt` 沿用基类实现（压消息历史），简报由基类 `_compose_prompt` 拼。
    # 这里不重复定义——三份同样的实现迟早会漂移。


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


class OpenCodeAcpKernel(AcpClientKernel):
    """OpenCode CLI 经 ACP 协议接入（`opencode acp`）。

    相比旧的 `opencode run --format json`，ACP 模式原生声明了
    `mcpCapabilities: {http: true}`，通过 `new_session(mcp_servers=...)`
    按会话注入 Ethan 的 `/kernel-tools` MCP 服务，无需修改 `~/.config/opencode`。
    """

    spec = AcpAgentSpec(
        kind=KernelKind.OPENCODE,
        display_name="OpenCode",
        cmd=["opencode", "acp"],
        binary="opencode",
        inject_provider=False,
    )


class AntigravityAcpKernel(AcpClientKernel):
    """Google Antigravity CLI 经 ACP 协议接入（`agy acp`）。

    官方文档说明连接客户端传入的 HTTP MCP server 时必须加
    `--process-per-session`（以隔离工作进程按会话提供服务）。
    """

    spec = AcpAgentSpec(
        kind=KernelKind.ANTIGRAVITY,
        display_name="Antigravity",
        cmd=["agy", "acp", "--process-per-session"],
        binary="agy",
        inject_provider=False,
    )
