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


class OpenCodeKernel(ACPKernelBase):
    kind = KernelKind.OPENCODE
    display_name = "OpenCode"
    acp_agent = "opencode"
    cli_binary = "opencode"

    @property
    def install_hint(self) -> str:
        return "curl -fsSL https://opencode.ai/install | bash"
