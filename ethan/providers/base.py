from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    usage: Optional[dict] = None  # {"input": N, "output": N, "cache": N}
    created_at: Optional[float] = None
    tool_steps: Optional[list] = field(default_factory=list)  # ToolEvent 执行摘要
    thought: Optional[str] = None  # 独立分离出来的思考过程
    quote: Optional[dict] = None  # 用户引用的某条历史消息 {role, content}，持久化以便刷新后仍显示引用气泡

    @property
    def is_tool_call(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_final: bool = False
    usage: Optional[dict] = None


@dataclass
class ToolEvent:
    """Emitted by stream_chat when a tool is called."""
    tool_name: str
    args_summary: str
    state: str  # "start" | "done" | "error"
    result_preview: str = ""
    result_detail: str = ""  # 更长的多行结果（前端展开看）
    sub_steps: list = field(default_factory=list)  # 委派类工具（如 delegate_coding）的子步骤
    tool_call_id: str = ""  # 唯一标识，前端用来精确配对 start/done（同名工具并发时不串）


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
