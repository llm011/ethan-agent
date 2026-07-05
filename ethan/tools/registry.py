import asyncio
import hashlib
import json

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

        # 可缓存的工具：命中缓存直接返回，避免重复调用。
        # intent 是展示用的注入参数，不影响工具语义，排除出缓存键（否则同实参不同 intent 会误判未命中）。
        if tool.cacheable:
            cache_args = {k: v for k, v in tc.arguments.items() if k != "intent"}
            args_hash = hashlib.md5(json.dumps(cache_args, sort_keys=True).encode()).hexdigest()
            cache_key = f"{tc.name}:{args_hash}"
            if cache_key in self._cache:
                return ToolResult(tool_call_id=tc.id, content=self._cache[cache_key])

        try:
            # 只传工具 schema 里声明的参数：剥掉 intent（展示用）以及模型偶尔幻觉出的
            # 多余字段（如 description=），防止 run() 报 unexpected keyword argument。
            valid_params = set(tool.parameters.get("properties", {}).keys())
            run_args = {k: v for k, v in tc.arguments.items() if k in valid_params}
            out = await tool.run(**run_args)
            # 工具可返回 str（普通）或 ToolResult（携带 sub_steps 等元信息）
            if isinstance(out, ToolResult):
                result = out
                result.tool_call_id = tc.id  # 工具自身不知道 call id，由执行器回填
            else:
                result = ToolResult(tool_call_id=tc.id, content=out)

            # 安全网：把工具输出里出现的任何已知 secret 真值替换成掩码，
            # 防止 `echo $KEY` 这类把注入的密钥回流进模型上下文。
            # get_secret 是授权取值路径，放行原文（否则 Agent 取出来没法用）。
            if tc.name != "get_secret" and result.content:
                from ethan.core.secrets_store import mask_text
                result.content = mask_text(result.content)

            if tool.cacheable:
                self._cache[cache_key] = result.content

            # 超长结果用廉价模型压缩（只压缩 content，保留 sub_steps）
            # no_compress 工具（file_read/shell/web_fetch/skill_read）必须逐字给模型，跳过压缩
            # 其他工具（web_search/grep/browser snapshot）由 compressor 根据阈值判断
            if not getattr(tool, "no_compress", False):
                from ethan.tools.result_compressor import maybe_compress, COMPRESS_THRESHOLD
                if len(result.content) > COMPRESS_THRESHOLD:
                    result.content = await maybe_compress(tc.name, result.content)

            return result
        except Exception as e:
            return ToolResult(
                tool_call_id=tc.id,
                content=f"Tool error: {e}",
                is_error=True,
            )
