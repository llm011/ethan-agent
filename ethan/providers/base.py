from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # for tool result messages
    usage: Optional[dict] = None  # {"input": N, "output": N, "cache": N}

    @property
    def is_tool_call(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_final: bool = False
    usage: Optional[dict] = None  # {"input": N, "output": N, "cache": N}


class BaseProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> Message: ...

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]: ...

    @property
    @abstractmethod
    def model(self) -> str: ...
