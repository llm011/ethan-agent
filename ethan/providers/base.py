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
    id: Optional[int] = None  # DB primary key (messages.id)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    usage: Optional[dict] = None  # {"input": N, "output": N, "cache": N}
    created_at: Optional[float] = None
    tool_steps: Optional[list] = field(default_factory=list)  # ToolEvent 执行摘要
    thought: Optional[str] = None  # 独立分离出来的思考过程
    reasoning: Optional[str] = None  # DeepSeek/Anthropic reasoning_content 原始思考链；续跑时回传 API
    quote: Optional[dict] = None  # 用户引用的某条历史消息 {role, content}，持久化以便刷新后仍显示引用气泡
    a2ui: Optional[list] = None  # ui_card 工具产出的 A2UI envelope 列表，持久化以便刷新后仍渲染卡片
    mcp_apps: Optional[list] = None  # 工具 UI 资源列表 [{uri, data}]，持久化后刷新仍可重渲染交互式图表
    images: list[dict] = field(default_factory=list)  # [{"data": "base64...", "media_type": "image/png"}]
    matched_skills: Optional[list] = None  # 本次对话命中的 Skill 列表 [{name, is_default}]，用于可视化
    ttfb_ms: Optional[int] = None  # 收到第一个文本块的耗时（毫秒）
    total_ms: Optional[int] = None  # 从请求到完成的总耗时（毫秒）
    cards: Optional[list] = None  # 结构化卡片数据（web_search/image_search 产出），前端按 type 渲染横向滚动卡片
    intermediate_blob_id: int = 0  # 中间过程正文外置文件索引；0 表示无
    status: str = "completed"  # running | completed | interrupted | stopped — 消息生成状态，用于中断检测与续跑

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
    truncated: bool = False  # SSL 中途断连导致输出被截断，上层可据此决定是否续接


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
    mcp_app: Optional[dict] = None  # MCP Apps UI 资源数据，前端用 iframe 渲染
    intent: str = ""  # 模型在 intent 参数里填的「本次调用目的」，展示在工具调用旁
    entity_type: str = ""  # 实体类型（builtin/browser/delegate/computer_use/...），用于可视化分类
    entity_id: str = ""  # 关联实体 ID（如 browser session_id），用于可视化实体聚合
    skill_category: str = ""  # 工具所属 skill 分类，前端按类别展示工具调用
    cards: Optional[list] = None  # 结构化卡片数据（web_search/image_search 产出），透传给前端渲染横向滚动卡片
    cards_meta: Optional[dict] = None  # 卡片元数据，如 {"total_results": 12300, "showing": 7}


@dataclass
class InjectEvent:
    """stream_chat 产出：用户运行中补充信息被 agent loop 消费。

    在每轮开头 drain injected_messages 后 yield，让 StreamCollector 把内容
    挂到随后第一个 tool step 上，前端可在时间线中展示。
    """
    messages: list = field(default_factory=list)


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
        max_tokens: int | None = None,
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

    async def close(self) -> None:
        """释放底层 HTTP 连接。子类持有长连接 client 时覆盖。"""
        return None
