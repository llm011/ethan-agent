import asyncio
import hashlib
import json

from ethan.providers.base import ToolCall
from ethan.tools.base import BaseTool, ToolResult

_COMPRESS_THRESHOLD = 4000


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
        self._cache: dict[str, str] = {}  # 轮次内缓存：key = "tool_name:args_hash"

    def reset_cache(self) -> None:
        """每次新的 chat() 调用前重置。"""
        self._cache.clear()

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

        # 可缓存的工具：命中缓存直接返回，避免重复调用
        if tool.cacheable:
            args_hash = hashlib.md5(json.dumps(tc.arguments, sort_keys=True).encode()).hexdigest()
            cache_key = f"{tc.name}:{args_hash}"
            if cache_key in self._cache:
                return ToolResult(tool_call_id=tc.id, content=self._cache[cache_key])

        try:
            out = await tool.run(**tc.arguments)
            # 工具可返回 str（普通）或 ToolResult（携带 sub_steps 等元信息）
            if isinstance(out, ToolResult):
                result = out
                result.tool_call_id = tc.id  # 工具自身不知道 call id，由执行器回填
            else:
                result = ToolResult(tool_call_id=tc.id, content=out)

            # 安全网：把工具输出里出现的任何已知 secret 真值替换成掩码，
            # 防止 `echo $KEY` 这类把注入的密钥回流进模型上下文。
            # get_secret 是授权取值路径，放行原文（否则失去意义）。
            if tc.name != "get_secret" and result.content:
                from ethan.core.secrets_store import mask_text
                result.content = mask_text(result.content)

            if tool.cacheable:
                self._cache[cache_key] = result.content

            # 超长结果用廉价模型压缩（只压缩 content，保留 sub_steps）
            # no_compress 工具（技能文档/文件原文）必须逐字给模型，跳过压缩
            if not getattr(tool, "no_compress", False) and len(result.content) > _COMPRESS_THRESHOLD:
                from ethan.tools.result_compressor import maybe_compress
                result.content = await maybe_compress(tc.name, result.content)

            return result
        except Exception as e:
            return ToolResult(
                tool_call_id=tc.id,
                content=f"Tool error: {e}",
                is_error=True,
            )
