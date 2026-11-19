"""Codex 内核 —— 复用 ACPKernelBase。

OpenCode 已迁往 `acp_client_kernel.OpenCodeAcpKernel`（走原生 `opencode acp`
协议，支持按会话 HTTP MCP 注入 Ethan 工具）；此处保留 `OpenCodeKernel` 别名
兼容既有直接导入路径。
"""
from __future__ import annotations

from ethan.kernel.acp_client_kernel import OpenCodeAcpKernel as OpenCodeKernel  # noqa: F401
from ethan.kernel.claude_kernel import ACPKernelBase
from ethan.kernel.runtime import KernelCapabilities, KernelKind


class CodexKernel(ACPKernelBase):
    kind = KernelKind.CODEX
    display_name = "Codex"
    acp_agent = "codex"
    cli_binary = "codex"

    capabilities = KernelCapabilities(
        streaming=True,
        tools=True,
        consent=False,
        ethan_context=False,
        resumable=True,
        # 实测：`-c mcp_servers.*` 与写进 config.toml 都能让 Codex 接受配置，
        # 但工具列表里始终没有 MCP 工具（只有它自带的 10 个）。加载条件未明，
        # 与其给用户一个"看起来接上了其实没接"的状态，不如如实说没有。
        shares_ethan_tools=False,
        shares_ethan_tools_reason=(
            "Codex 能接受 MCP 配置但不加载其中的工具（实测其工具列表始终只有自带的 10 个），"
            "暂不支持共享 Ethan 工具。CI 助手建议改用 Claude Code 或 DSH"
        ),
    )

    @property
    def install_hint(self) -> str:
        return "npm i -g @openai/codex"

    async def _resolve_kernel_model(self, request) -> str | None:
        from ethan.kernel.model_sync import resolve_codex_model

        return await resolve_codex_model(request.model)

    async def run(self, request, context=None):
        """Codex 内核在执行前先关掉 ACP 层的 provider 覆盖。

        ACP 的 `_codex_provider_overrides` 是为「委派编码任务」设计的：它强制把
        codex 指向 Ethan 自己的 cliproxy provider，并写死 `ETHAN_CODEX_MODEL`
        （默认 gpt-5.5）。这在委派场景是对的——要复用 Ethan 的额度。

        但作为**内核**用时这是错的：
          · 用户自己的 ~/.codex/config.toml 里已经配好了 provider/model，
            覆盖它等于无视用户配置
          · 写死的 gpt-5.5 在 cliproxy 上没有 → 实测报
            `unknown provider for model gpt-5.5`

        所以用环境变量让 ACP 层跳过覆盖，走用户原生配置。
        """
        import os

        old = os.environ.get("ETHAN_CODEX_NO_PROVIDER_OVERRIDE")
        os.environ["ETHAN_CODEX_NO_PROVIDER_OVERRIDE"] = "1"
        try:
            async for event in super().run(request, context):
                yield event
        finally:
            # 恢复原值：委派工具（delegate_coding）还要用覆盖逻辑
            if old is None:
                os.environ.pop("ETHAN_CODEX_NO_PROVIDER_OVERRIDE", None)
            else:
                os.environ["ETHAN_CODEX_NO_PROVIDER_OVERRIDE"] = old
