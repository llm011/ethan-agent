from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ethan.providers.base import ToolDefinition


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    sub_steps: list = field(default_factory=list)  # 委派类工具的子步骤（如 delegate_coding 的 Coding Agent 工具调用）


class BaseTool(ABC):
    fast_path: bool = True  # 是否在 Fast Path 时加载。设为 False 的工具只在 Full Path 使用
    cacheable: bool = True  # 同参数是否可缓存；副作用类工具（shell）应设为 False
    side_effect: bool = False  # 是否有副作用（改文件/删数据/执行/花钱/对外发消息）。
    # 三方渠道（如飞书）认主人后，非主人调用 side_effect=True 的工具会被守卫拦截。
    no_compress: bool = False  # 输出永不走 result_compressor 摘要（技能文档/文件原文等必须逐字给模型）。

    def consent_check(self, **kwargs) -> str | None:
        """检查此次调用是否需要用户授权。

        返回非空字符串 → 需要授权，字符串作为授权说明展示给用户；
        返回 None → 放行。默认所有工具放行，子类按参数判定（如 file_read 命中 .secrets/）。
        """
        return None

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
    async def run(self, **kwargs) -> str | ToolResult: ...

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )
