"""MCP Client — 连接外部 MCP Server，自动注册其工具到 ToolRegistry。"""
import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ethan.tools.base import BaseTool


class MCPTool(BaseTool):
    """包装 MCP server 暴露的工具为 BaseTool。"""

    def __init__(self, name: str, description: str, parameters: dict[str, Any], session: ClientSession):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._session = session

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def run(self, **kwargs) -> str:
        result = await self._session.call_tool(self._name, arguments=kwargs)
        if result.content:
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "\n".join(parts) if parts else "(empty result)"
        return "(empty result)"


class MCPClient:
    """管理与一个 MCP server 的连接。"""

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None):
        self._params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
        )
        self._session: ClientSession | None = None
        self._read = None
        self._write = None
        self._cm = None
        self._session_cm = None

    async def connect(self) -> list[MCPTool]:
        """连接到 MCP server 并返回其暴露的工具列表。"""
        self._cm = stdio_client(self._params)
        self._read, self._write = await self._cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()

        tools_result = await self._session.list_tools()
        tools = []
        for tool in tools_result.tools:
            mcp_tool = MCPTool(
                name=tool.name,
                description=tool.description or "",
                parameters=tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                session=self._session,
            )
            tools.append(mcp_tool)

        return tools

    async def disconnect(self) -> None:
        if self._session_cm:
            await self._session_cm.__aexit__(None, None, None)
        if self._cm:
            await self._cm.__aexit__(None, None, None)
        self._session = None
