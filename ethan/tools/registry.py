import asyncio

from ethan.providers.base import ToolCall
from ethan.tools.base import BaseTool, ToolResult


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())


class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    async def execute(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        tasks = [self._run_one(tc) for tc in tool_calls]
        return await asyncio.gather(*tasks)

    async def _run_one(self, tc: ToolCall) -> ToolResult:
        tool = self._registry.get(tc.name)
        if tool is None:
            return ToolResult(
                tool_call_id=tc.id,
                content=f"Unknown tool: {tc.name}",
                is_error=True,
            )
        try:
            result = await tool.run(**tc.arguments)
            return ToolResult(tool_call_id=tc.id, content=result)
        except Exception as e:
            return ToolResult(
                tool_call_id=tc.id,
                content=f"Tool error: {e}",
                is_error=True,
            )
