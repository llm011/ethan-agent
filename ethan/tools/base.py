from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ethan.providers.base import ToolDefinition


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]: ...

    @abstractmethod
    async def run(self, **kwargs) -> str: ...

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )
