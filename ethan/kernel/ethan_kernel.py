"""EthanKernel — 原生 Ethan 运行时。

作用有两个：

1. **作为默认内核和兜底内核**：永远可用，不依赖任何外部 CLI。
2. **确立事件契约的参考实现**：其他内核要在行为上对齐「原生 Ethan 产出什么」，
   所以它必须是最薄的一层——只是把 `Agent.stream_chat()` 的产出原样转发，
   不做任何转换。任何转换都意味着行为漂移，那就不是「对齐」了。

刻意不做的事：
  · 不改写事件、不补充事件、不吞事件
  · 不插入额外的工具/记忆/技能逻辑（那些已经在 Agent 里）
  · 不缓存、不重试（重试逻辑在 Agent 内部，重复包装会双重重试）
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from ethan.kernel.runtime import (
    KernelCapabilities,
    KernelContext,
    KernelKind,
    KernelRequest,
    KernelRuntime,
)

logger = logging.getLogger(__name__)


class EthanKernel(KernelRuntime):
    """把现有 Agent 包装成内核。

    Agent 的构造需要 tool_registry / skill_registry / model 等，这些来自
    `KernelContext`。若调用方没提供（比如内核被独立测试），就按 channel 构造一个
    最小可用的 Agent——保证这个内核在任何环境下都能跑起来。
    """

    kind = KernelKind.ETHAN
    display_name = "Ethan 原生"
    capabilities = KernelCapabilities(
        streaming=True,
        tools=True,
        consent=True,
        ethan_context=True,
        resumable=True,  # 会话续接由 sessions.db 承担
    )

    async def run(
        self,
        request: KernelRequest,
        context: KernelContext | None = None,
    ) -> AsyncIterator[Any]:
        agent = self._build_agent(request, context)
        # 原样转发，不做任何转换——这就是「原生」的定义
        async for event in agent.stream_chat(request.messages):
            yield event

    def _build_agent(self, request: KernelRequest, context: KernelContext | None):
        """取出要执行的 Agent。

        优先级（**必须**按这个顺序，见下）：

          1. `context.agent` —— 调用方已建好的实例。这是唯一正确的路径：
             Agent 上挂着 session_id / runtime_context / is_owner /
             _executor.current_run / 已加载的 system_files 等请求级状态，
             新建一个就会全部丢掉（症状：会话串、工具取消失效、记忆召回错人）。
          2. 用传进来的 registry 新建 —— 只在没有人给 agent 时兜底。
          3. 完全现建一个 —— 仅用于独立测试该内核。
        """
        ctx = context or KernelContext()

        if ctx.agent is not None:
            return ctx.agent

        if ctx.tool_registry is not None or ctx.skill_registry is not None:
            from ethan.core.agent import Agent

            return Agent(
                tool_registry=ctx.tool_registry,
                skill_registry=ctx.skill_registry,
                model=None,
                channel=request.channel,
                user_id=request.user_id,
                mode=request.mode,
            )

        from ethan.core.agent_factory import create_agent

        return create_agent(
            channel=request.channel or "web",
            user_id=request.user_id,
        )
