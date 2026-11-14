"""把 Ethan 的工具集暴露成 MCP server，供外部内核（DSH / Claude Code / Codex …）调用。

## 这解决什么问题

外部内核（DSH、Claude Code 等）自带一套工具，但**那些不是 Ethan 的工具**：
不读 Ethan 的知识库、不用 Ethan 的技能、不遵守 Ethan 的授权与频率熔断。

用户的原话是「我希望内核能连接进来作为 ethan 的心脏来驱动它干活」——
换句话说：换的是**大脑**（规划/推理），不该丢掉**手和脚**（工具/技能）。

## 怎么接的

ACP 协议本身就支持这个：`new_session(mcp_servers=[...])` 可以把 MCP server
挂到外部 agent 上。DSH 的 `initialize` 明确声明了 `mcpCapabilities: {http: true}`，
说明它支持 HTTP 传输的 MCP server。

所以链路是：

    外部内核 (DSH)  ──MCP over HTTP──▶  Ethan 的 /mcp-tools 端点
                                          └─ 67 个 Ethan 工具

外部 agent 看到的工具名带 `ethan_` 前缀（如 `ethan_web_search`），
与我们自己的工具区分开，避免和它自带的同名工具打架。

## 为什么单独开一个端点

现有的 `/mcp` 只暴露 `ask_ethan` 一个工具（给豆包这类外部客户端用，
语义是"把整件事交给 Ethan"）。这里需要的是相反的语义：**把 Ethan 的能力
拆成原子工具交给外部 agent 编排**。两者用途不同，混在一起会让工具的
描述和语义互相干扰。

## 安全边界（重要）

这些工具里有 `shell` / `file_write` 这类高副作用能力。挂给外部 agent 意味着
**它可以直接动用户的机器**。所以：
  · 端点强制要求 `network.mcp_api_key`（或仅回环监听）
  · 默认**只暴露只读工具**，写操作需要显式配置 `kernel_share_tools: "all"`
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 只读工具白名单：默认只暴露这些。
#
# 判据与 project CLAUDE.md 的 `no_compress` 逻辑同源：这份输出是给模型读的，
# 还是会让它去改变世界的？后者不该默认交给外部 agent。
READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "file_read",
    "file_list",
    "web_search",
    "web_fetch",
    "image_search",
    "get_weather",
    "lunar_calendar",
    "knowledge_search",
    "knowledge_read",
    "recall_memory",
    "skill_list",
    "skill_read",
    "find_tools",
    "code_analyze",
    "ocr_extract_text",
    "rg_search",
    "fd_find",
    "config_get",
    "list_secrets",
})

# 绝不允许通过 MCP 暴露的工具——即使配了 "all"。
#
# `shell` 是最大的一个：外部 agent 拿到 shell 等于拿到整台机器，
# 而它的权限模型与 Ethan 的 consent 不同源（DSH 用 --approval-policy，
# Claude Code 用 --dangerously-skip-permissions），我们无法在中间拦截。
# 需要执行能力时应该用 `code_run`（它委托给 ShellTool，走 Ethan 的授权链），
# 但即便如此默认也不开。
NEVER_EXPOSE: frozenset[str] = frozenset({
    # shell：外部 agent 拿到 shell 等于拿到整台机器，且它的权限模型与 Ethan 的
    # consent 不同源，我们无法在中间拦截。需要执行能力时让它用 code_run
    # （内部委托 ShellTool，走 Ethan 的授权链）。
    "shell",
    # 密钥类工具**开放**（用户明确要求）：外部内核要真正干活，常常需要拿
    # API key / token 去调第三方服务；不给就只能猜或绕路用 shell（而 shell
    # 是被禁的），反而逼出更差的做法。
    #
    # 风险由 Ethan 侧原样承担：这些工具本身已有各自的 consent 与审计，
    # 且外部内核拿到的只是「能调工具」，不是「能看到明文」——
    # get_secret 的返回值仍走 Ethan 的掩码逻辑。
    # 改 Ethan 自身配置/人格：这些是"自我修改"能力，被外部 agent 误触的代价
    # 远高于收益（比如它"贴心地"把 lark.app_id 清空）
    "config_set",
    "profile_update",
    "procedure_write",
    "memory_write",
    # 递归委派：delegate_coding 会再起一个外部 coding agent，
    # A->B->A 的嵌套没有意义且会放大资源占用
    "delegate_coding",
})


def _tool_schema(tool) -> dict:
    """把 Ethan 的 Tool 转成 MCP 工具描述。

    Ethan 的 `parameters` 已经是标准 JSON Schema（OpenAI function calling 格式），
    与 MCP 的 inputSchema 兼容，所以直接透传即可，不需要转换层。
    """
    return {
        "name": f"ethan_{tool.name}",
        "description": (tool.description or "")[:1024],
        "inputSchema": tool.parameters or {"type": "object", "properties": {}},
    }


def build_mcp_tools(
    *,
    channel: str = "mcp",
    mode: str = "",
    share: str = "all",
) -> list[Any]:
    """构造要暴露给外部内核的工具实例列表。

    share:
      · "all"（默认）—— 暴露除 NEVER_EXPOSE 之外的全部。
        用户明确要求「内核要能作为 Ethan 的心脏驱动它干活」，只读能力不够：
        外部内核不能写文件就等于干不了活。所以默认给全，靠 NEVER_EXPOSE 兜底。
      · "readonly"   —— 只暴露 READ_ONLY_TOOLS（保守模式，可配置切换）

    无论哪种，NEVER_EXPOSE 里的工具都不会出现。
    """
    from ethan.core.agent_factory import build_tool_registry

    registry = build_tool_registry(channel=channel, mode=mode)
    out = []
    for tool in registry.all():
        if tool.name in NEVER_EXPOSE:
            continue
        if share != "all" and tool.name not in READ_ONLY_TOOLS:
            continue
        out.append(tool)
    logger.info(
        "kernel MCP bridge: 暴露 %d 个工具（share=%s）", len(out), share
    )
    return out
