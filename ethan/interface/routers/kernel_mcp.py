"""`/kernel-tools` MCP 端点：把 Ethan 的工具集暴露给外部内核。

## 与 `/mcp` 的分工

| 端点 | 语义 | 使用者 |
|---|---|---|
| `/mcp` | 「把整件事交给 Ethan」——只暴露 `ask_ethan` | 豆包等外部 MCP 客户端 |
| `/kernel-tools` | 「把 Ethan 的手脚拆开给你编排」——暴露原子工具 | DSH / Claude Code 等内核 |

两者不能混：前者是黑盒委托，后者是能力注入。混在一起会让工具描述与语义
互相干扰（外部 agent 会纠结"我该调 ask_ethan 还是自己编排工具"）。

## 安全设计

工具由 `ethan.kernel.tool_bridge` 筛选（默认只读、永远排除 shell 等）。
鉴权与 `/mcp` 一致：`network.mcp_api_key`（未配置时不校验，靠网络层保护）。

额外约束：这个端点**只在被内核使用时才启动**，由 `api.py` 根据配置决定是否
mount——不给不需要的用户凭空多开一个攻击面。
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ethan.kernel.tool_bridge import _tool_schema, build_mcp_tools

logger = logging.getLogger(__name__)

# 独立的 FastMCP 实例（与 /mcp 的 mcp_server 分开）
kernel_mcp = FastMCP("EthanTools", stateless_http=True)
kernel_mcp.settings.streamable_http_path = "/"

# 标记是否已注册过工具（FastMCP 的工具注册是全局的，重复注册会覆盖）
_registered = False


def _register_tools() -> None:
    """把 Ethan 工具注册成 MCP tool。

    为什么要延迟注册：`build_tool_registry()` 很重（60+ 工具实例化，
    还要读 MCP 配置、连外部 server），不应该在 import 时就跑。
    """
    global _registered
    if _registered:
        return

    from ethan.core.config import get_config

    share = getattr(get_config().defaults.kernel, "share_tools", "all")
    tools = build_mcp_tools(share=share)

    for tool in tools:
        _register_one(tool)

    _registered = True
    logger.info("kernel-tools MCP 端点就绪，暴露 %d 个工具", len(tools))


def _register_one(tool: Any) -> None:
    """把一个 Ethan 工具注册成 MCP 工具。

    ## 为什么不用 `mcp.add_tool(fn)`

    FastMCP 的 `add_tool` 会从**函数签名**推导 inputSchema。我们没法为 58 个工具
    各写一个函数，只能写 `async def _invoke(**kwargs)`——而 FastMCP 把 `**kwargs`
    当成一个名为 `kwargs` 的**必填字段**，于是任何调用都报：

        1 validation error for ethan_web_searchArguments
        kwargs  Field required

    （实测踩到：tools/list 正常列出 58 个工具，tools/call 全部失败。）

    ## 做法

    手工构造 `Tool` 并显式给出 `parameters`——它是 Ethan 工具自带的标准
    JSON Schema（OpenAI function calling 格式），与 MCP 的 inputSchema 完全同构，
    直接透传，零转换。
    """
    from mcp.server.fastmcp.tools.base import Tool, func_metadata

    name = f"ethan_{tool.name}"
    schema = _tool_schema(tool)
    props = schema["inputSchema"].get("properties", {}) or {}
    required = schema["inputSchema"].get("required", []) or []

    async def _invoke(**kwargs: Any):
        missing = [k for k in required if k not in kwargs or kwargs[k] in (None, "")]
        if missing:
            return f"缺少必填参数：{', '.join(missing)}"

        # 丢弃 schema 之外的字段：外部 agent 可能臆造参数名，传进去会 TypeError
        clean = {k: v for k, v in kwargs.items() if k in props}

        try:
            result = await tool.run(**clean)
        except TypeError as e:
            return f"参数不匹配（可用参数：{list(props)}）：{e}"
        except Exception as e:  # noqa: BLE001 - 工具失败要变成文本，不能打挂 MCP
            logger.debug("kernel-tools 调用 %s 失败", tool.name, exc_info=True)
            return f"工具执行失败：{e}"

        from mcp.types import TextContent

        content = getattr(result, "content", None)
        text = str(content if content is not None else result)
        # MCP 要求 content 是 ContentBlock 列表，不能返回裸字符串——
        # 否则 FastMCP 会把字符串按字符逐个当块解析，报上万条校验错误
        # （实测：14705 validation errors，input_value='*'）。
        return [TextContent(type="text", text=text)]

    _invoke.__name__ = name
    _invoke.__doc__ = schema["description"]

    # 用子类覆盖 run：`Tool` 是 pydantic 模型，**不能给实例赋方法**
    # （会报 `"Tool" object has no field "run"`），只能定义子类。
    #
    # 为什么要覆盖 run：
    #   `Tool.run` 走 `fn_metadata.call_fn_with_arg_validation(...)`，而
    #   `func_metadata` 把 `**kwargs` 看成「一个名为 kwargs 的必填字段」，
    #   于是任何调用都报 `kwargs Field required`——不管 `parameters` 里写的什么。
    #   实测：tools/list 正常列出 58 个工具，tools/call 全部失败。
    #
    # 入参校验已由 Ethan 工具自身的 schema 定义（`tool.parameters`），且
    # `_invoke` 内部也做了必填检查与冗余字段丢弃，再叠一层错误的 pydantic
    # 校验只会帮倒忙。所以直接原样透传 arguments。
    class _PassthroughTool(Tool):
        async def run(self, arguments, context=None, convert_result: bool = False):  # type: ignore[override]
            return await _invoke(**arguments)

    registered = _PassthroughTool(
        fn=_invoke,
        name=name,
        description=schema["description"],
        # 显式给 schema，让 tools/list 返回正确的 inputSchema
        parameters=schema["inputSchema"],
        # structured_output=False：工具返回的是纯文本（正文/JSON 字符串），
        # 不开 structured output。否则 MCP 会声明 outputSchema 并要求返回
        # 结构化对象，而我们返回 str → 报错
        # `outputSchema defined but no structured output returned`（实测踩到）。
        fn_metadata=func_metadata(_invoke, structured_output=False),
        is_async=True,
    )
    kernel_mcp._tool_manager._tools[name] = registered


def get_kernel_tools_app():
    """返回可 mount 的 Starlette ASGI app（含鉴权中间件）。

    **每次调用都新建**，不做缓存。原因与 `/mcp` 完全一致（见 mcp_server.py 的
    get_mcp_lifespan docstring）：`streamable_http_app()` 返回的 session manager
    的 `run()` **每实例只能调一次**。

    缓存会踩两个坑：
      · 测试里每个用例重建 app（因为上一个实例的 run() 已消耗），缓存到旧实例
        就抛 `run() can only be called once per instance`
      · 顶层 lifespan 驱动的实例必须与处理请求的实例是同一个，缓存会破坏这个
        对应关系 → `Task group is not initialized`

    必须缓存的是 `_register_tools()`（工具注册是纯 CPU 且幂等），不是 app。
    """
    _register_tools()

    from ethan.interface.routers.mcp_server import _wrap_with_auth

    return _wrap_with_auth(kernel_mcp.streamable_http_app(), tag="kernel-tools")


def get_kernel_tools_lifespan(mcp_app):
    """供 api.py 顶层 lifespan 显式 enter。

    与 `/mcp` 同样的坑：Starlette 的 `Mount` 不转发子应用 lifespan，
    必须由顶层显式驱动 session manager 的 task group，否则每个请求都抛
    `Task group is not initialized`。
    """
    inner = getattr(mcp_app, "_ethan_inner_mcp_app", None)
    if inner is None:
        inner = kernel_mcp.streamable_http_app()
    return inner.router.lifespan_context
