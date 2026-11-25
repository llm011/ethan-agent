"""Persisted session value objects."""
from dataclasses import dataclass, field

from ethan.providers.base import Message


class PaginatedList(list):
    """A list that carries a .total attribute for pagination."""

    total: int = 0


@dataclass
class Session:
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    messages: list[Message] = field(default_factory=list)
    snippet: str | None = None
    source: str = "web"  # web | repl | lark | cli | desktop | acp | custom
    mode: str = ""  # "" = 工作助手; 规范英文 key，如 "legal"/"companion"（见 core/modes.py）
    pinned_at: float = 0.0  # >0 表示已置顶，值为置顶时间戳
    last_read_at: float = 0.0  # 未读水位：updated_at > last_read_at 即有未读（侧边栏红点）
    # 运行中「补充信息」待消费队列（跨刷新持久化）：[{"id": str, "content": str}]。
    # inject 时落库；agent drain / run 结束时清空。前端在工具时间线上方展示，可删除。
    pending_injected: list = field(default_factory=list)
    # 外部内核自己的 session id（DSH 的 `session-xxx` / Claude 的 UUID）。
    # 用户需要它去命令行定位这条对话（如 `dsh --session-id <id>`），所以落库、
    # 在标题下展示并支持复制。原生内核下为空字符串。
    kernel_session_id: str = ""
    # 产生上面那个 id 的内核名（dsh / claude_code / pi …），用于 UI 标注来源
    kernel_kind: str = ""
