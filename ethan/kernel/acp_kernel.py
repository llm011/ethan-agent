"""Codex / OpenCode 内核 —— 复用 ACPKernelBase，只是换 CLI 和 prefer 参数。

这两个 CLI 的 stream 事件形态与 Claude 略有差异（见 `ethan/acp/agent_codex.py`
与 `agent_opencode.py`），但 ACP 层已经把差异吸收成了统一的
`on_event("step"|"text", data)`，所以这里只需要声明路由信息。

⚠️ 与 Claude Code 相同的取舍：不走 Ethan 工具/技能/记忆、不做中途授权。
详见 `claude_kernel.py` 的模块 docstring。
"""
from __future__ import annotations

from ethan.kernel.claude_kernel import ACPKernelBase
from ethan.kernel.runtime import KernelKind


class CodexKernel(ACPKernelBase):
    kind = KernelKind.CODEX
    display_name = "Codex"
    acp_agent = "codex"
    cli_binary = "codex"

    @property
    def install_hint(self) -> str:
        return "npm i -g @openai/codex"

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


class OpenCodeKernel(ACPKernelBase):
    kind = KernelKind.OPENCODE
    display_name = "OpenCode"
    acp_agent = "opencode"
    cli_binary = "opencode"

    @property
    def install_hint(self) -> str:
        return "curl -fsSL https://opencode.ai/install | bash"
