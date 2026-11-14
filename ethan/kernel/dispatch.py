"""内核调度层 —— 把「选哪个内核」和「跑这个内核」接到现有 chat 链路。

## 为什么要这层

上游 `producers.py` 现在的写法是：

    async for item in agent.stream_chat(messages):
        if isinstance(item, ToolEvent): ...

它直接依赖 `Agent` 实例。但选内核之后，执行者可能是 `EthanKernel`（内部仍是
这个 Agent），也可能是 `ClaudeCodeKernel`（完全没有 Agent）。

本层提供一个 **鸭子类型兼容的句柄**：

    runner = KernelRunner(...)          # 有 .stream_chat() / .usage / .model
    async for item in runner.stream_chat(messages): ...

producers.py 只需要把 `agent` 换成 `runner`（一行），其余判断/落库/SSE 逻辑
完全不用动。这样「多内核」对上层是透明的。

## 默认行为必须与现在完全一致

`kernel.default` 未配置时 → `KernelKind.ETHAN` → `EthanKernel` 原样转发
`Agent.stream_chat`。除了多一层 `async for` 转发，没有任何行为变化。

## 为什么保留 agent 属性

`collector.bind(agent)` 要读 `agent.usage` 取 token 统计，另外还有几处读
`agent._provider.model` / `agent.session_id` / `agent.runtime_context`。
与其改一堆调用方，不如让 `KernelRunner` 代理这些属性：

  · 原生内核：属性透传给真正的 Agent（行为不变）
  · 外部内核：`usage` 用自己统计的 token（拿不到就当 0）、`model` 报内核名
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator

from ethan.kernel.runtime import (
    KernelContext,
    KernelKind,
    KernelRequest,
    KernelRuntime,
    KernelStats,
    get_kernel_registry,
)

logger = logging.getLogger(__name__)


class KernelUsage:
    """与 `Agent.usage` 同形的 token 统计。

    collector 读的是 `agent.usage.input_tokens` / `.output_tokens` /
    `.cache_tokens` / `.total`，这里提供同名属性。外部内核拿不到精确 token 时
    保持 0，不要瞎估——估出来的数会污染「内核对比」这个用途。
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_tokens = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def dict(self) -> dict:
        return {
            "input": self.input_tokens,
            "output": self.output_tokens,
            "cache": self.cache_tokens,
        }


class KernelRunner:
    """内核运行句柄：对 `Agent` 的鸭子类型兼容包装。

    `stream_chat` 是唯一真正被调用的方法；其余属性是为兼容既有调用方而代理的。
    """

    def __init__(
        self,
        runtime: KernelRuntime,
        agent: Any = None,
        *,
        model: str = "",
        channel: str = "",
        user_id: str = "",
        mode: str = "",
        task_kind: str = "",
        working_dir: str = "",
    ) -> None:
        self.runtime = runtime
        self._agent = agent          # 原生内核时的真实 Agent（外部内核为 None）
        # 这三个字段在原 Agent 上本来就有，上游代码（producers / 渠道层）会直接读
        # `agent._channel` 之类。所以**有 agent 时必须沿用 agent 上的值**，否则
        # 我们自己的默认值会把原属性遮住，导致上游拿到空字符串。
        # 显式传参优先（调用方明确指定本次用哪个渠道/用户），其次是 agent 上的。
        self._channel = channel or getattr(agent, "_channel", "") if agent is not None else channel
        self._user_id = user_id or getattr(agent, "_user_id", "") if agent is not None else user_id
        self._mode = mode or getattr(agent, "_mode", "") if agent is not None else mode
        self._task_kind = task_kind
        self._working_dir = working_dir
        self._model = model or (getattr(agent, "_provider", None) and agent._provider.model) or ""
        self.usage = KernelUsage()
        self.session_id = getattr(agent, "session_id", "") if agent is not None else ""
        self.runtime_context = getattr(agent, "runtime_context", "") if agent is not None else ""
        self.last_stats: KernelStats | None = None

    # ── 属性代理：让既有代码以为它拿到的还是 Agent ──────────────────

    @property
    def kernel_kind(self) -> str:
        return self.runtime.kind.value

    @property
    def kernel_name(self) -> str:
        return self.runtime.display_name

    @property
    def model(self) -> str:
        # 原生内核报真实模型；外部内核报内核名（它的模型由 CLI 自己决定）
        if self.runtime.kind == KernelKind.ETHAN:
            return self._model
        return f"{self.runtime.display_name}"

    def __getattr__(self, item: str) -> Any:
        """未定义属性一律透传给底层 Agent。

        注意只在 `_agent` 存在时生效。`__getattr__` 只在正常属性查找失败时调用，
        所以不会干扰上面显式定义的 property。
        """
        agent = self.__dict__.get("_agent")
        if agent is not None:
            return getattr(agent, item)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {item!r}")

    # ── 真正干活 ──────────────────────────────────────────────────

    async def stream_chat(self, messages: list) -> AsyncIterator[Any]:
        """按选中的内核产出事件流，并顺手统计可观测数据。"""
        started = time.time()
        tool_calls = 0
        request = KernelRequest(
            messages=messages,
            user_id=self._user_id,
            channel=self._channel,
            mode=self._mode,
            session_id=self.session_id,
            working_dir=self._working_dir,
            task_kind=self._task_kind,
        )
        context = KernelContext(
            # 关键：把原 agent 实例传进去。EthanKernel 直接用它，不新建——
            # 否则 session_id / runtime_context / is_owner / current_run 全丢。
            agent=self._agent,
            # 这两个是给「没有 agent 但给了 registry」的兜底路径用的
            tool_registry=getattr(self._agent, "_registry", None),
            skill_registry=getattr(self._agent, "_skills", None),
        )

        error = ""
        try:
            async for event in self.runtime.run(request, context):
                if not isinstance(event, str):
                    # 只数「start」，避免同名工具的 done 事件重复计数
                    if getattr(event, "state", "") == "start":
                        tool_calls += 1
                yield event
        except Exception as e:  # noqa: BLE001 - 统计数据落库不能因异常丢失
            error = str(e)
            raise
        finally:
            elapsed = int((time.time() - started) * 1000)
            # 原生内核的真实 token 从 Agent.usage 取；外部内核拿不到就保持 0
            if self._agent is not None:
                u = getattr(self._agent, "usage", None)
                if u is not None:
                    self.usage.input_tokens = getattr(u, "input_tokens", 0)
                    self.usage.output_tokens = getattr(u, "output_tokens", 0)
                    self.usage.cache_tokens = getattr(u, "cache_tokens", 0)
            self.last_stats = KernelStats(
                kernel=self.runtime.kind.value,
                elapsed_ms=elapsed,
                tool_calls=tool_calls,
                input_tokens=self.usage.input_tokens,
                output_tokens=self.usage.output_tokens,
                error=error,
            )
            logger.info("kernel=%s elapsed=%dms tools=%d", self.runtime.kind.value, elapsed, tool_calls)


def build_runner(
    agent: Any,
    *,
    kernel: str = "",
    task_kind: str = "",
    working_dir: str = "",
    channel: str = "",
    user_id: str = "",
    mode: str = "",
) -> KernelRunner:
    """根据配置选出内核并包成 runner。

    `agent` 是上游已经建好的 Agent（`create_agent` 的产物）。即使选了外部内核，
    也先建它——因为需要它的 model / channel / 会话信息，且原生内核要复用它。
    外部内核只是不使用它的执行逻辑。
    """
    from ethan.core.config import get_config

    cfg = get_config()
    kernel_cfg = getattr(cfg.defaults, "kernel", None)
    if kernel is None or kernel == "":
        kernel = getattr(kernel_cfg, "default", "") if kernel_cfg else ""
    task_rules = getattr(kernel_cfg, "task_rules", None) if kernel_cfg else None

    runtime = get_kernel_registry().resolve(
        explicit=kernel or None,
        task_kind=task_kind,
        task_rules=task_rules,
        default=KernelKind.ETHAN,
    )
    if runtime.kind != KernelKind.ETHAN:
        logger.info("使用外部内核 %s 执行本轮对话", runtime.kind.value)

    return KernelRunner(
        runtime,
        agent,
        model=getattr(agent, "model", "") or "",
        channel=channel or getattr(agent, "_channel", ""),
        user_id=user_id or getattr(agent, "_user_id", ""),
        mode=mode or getattr(agent, "_mode", ""),
        task_kind=task_kind,
        working_dir=working_dir,
    )
