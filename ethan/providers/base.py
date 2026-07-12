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
    a2ui: Optional[list] = None  # ui_card 工具产出的 A2UI envelope 列表，持久化以便刷新后仍渲染卡片
    images: list[dict] = field(default_factory=list)  # [{"data": "base64...", "media_type": "image/png"}]
    matched_skills: Optional[list] = None  # 本次对话命中的 Skill 列表 [{name, is_default}]，用于可视化

    @property
    def is_tool_call(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_final: bool = False
    usage: Optional[dict] = None
    reasoning: str = ""  # 模型思考内容（reasoning_content / thinking）；与 content 分流，不当正文展示


@dataclass
class ThinkingEvent:
    """stream_chat 产出：模型正在思考。渠道收到后只显示占位（如「🤔 thinking...」），不打印 delta 原文。"""
    delta: str = ""


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
    ui: Optional[list] = None  # ui_card 工具产出的 A2UI envelope 列表，透传给前端渲染卡片
    intent: str = ""  # 模型在 intent 参数里填的「本次调用目的」，展示在工具调用旁
    entity_type: str = ""  # 实体类型（builtin/browser/delegate/computer_use/...），用于可视化分类
    entity_id: str = ""  # 关联实体 ID（如 browser session_id），用于可视化实体聚合
    skill_category: str = ""  # 工具所属 skill 分类，前端按类别展示工具调用


@dataclass
class SkillsMatchedEvent:
    """stream_chat 产出：本次对话命中的 Skill 列表。

    在 stream_chat 开头（system prompt 构建完毕、skill 匹配完成后）yield 一次，
    让消费者（StreamCollector / SSE / 落库）记录命中的 Skill 上下文。
    """
    skills: list = field(default_factory=list)  # [{"name": str, "is_default": bool}]


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
