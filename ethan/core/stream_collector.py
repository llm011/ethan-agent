"""统一的 stream_chat 消费器。

chat 路由（SSE）、lark、heartbeat、repl 四处都在做「遍历 agent.stream_chat()，
把 ToolEvent 收集成 tool_steps + 计时，文本累积到 full/thought」。本类收口该逻辑。

用法：
    collector = StreamCollector()
    async for item in agent.stream_chat(messages):
        text = collector.feed(item)  # ToolEvent→None（已记录）；文本→返回该块
        if text: ...  # 渠道特化处理（yield SSE / Live 渲染）
    # 结束后：collector.full / .thought / .tool_steps / .usage_dict
"""
from __future__ import annotations

import time
from typing import Any

from ethan.providers.base import ToolEvent


class StreamCollector:
    def __init__(self):
        self.full: str = ""
        self.thought: str = ""
        self.tool_steps: list[dict] = []
        self._times: dict[str, float] = {}
        self._agent = None  # 可选，用于取 usage

    def bind(self, agent) -> "StreamCollector":
        """绑定 agent，结束时从 agent.usage 取 token。"""
        self._agent = agent
        return self

    def feed(self, item: Any) -> str | None:
        """处理一个 stream_chat 产出项。返回文本块（str）或 None（ToolEvent）。"""
        if isinstance(item, ToolEvent):
            self._handle_tool_event(item)
            return None
        # 文本块
        text = item if isinstance(item, str) else getattr(item, "content", "")
        if not text:
            return None
        # 工具开始前累积的文本算作 thought（思考过程）
        if self.tool_steps and any(s["state"] == "running" for s in self.tool_steps):
            # 工具执行中收到的文本：暂归 full，工具结束后由调用方决定
            self.full += text
        else:
            self.full += text
        return text

    def _handle_tool_event(self, item: ToolEvent) -> None:
        if item.state == "start":
            # 工具开始前累积的文本转入 thought
            if self.full:
                self.thought += ("\n\n" if self.thought else "") + self.full
                self.full = ""
            self._times[item.tool_name] = time.time()
            self.tool_steps.append({
                "tool": item.tool_name,
                "args": item.args_summary,
                "state": "running",
                "duration_ms": None,
                "result_preview": "",
                "sub_steps": [],
            })
        else:  # done / error
            duration_ms = int(
                (time.time() - self._times.pop(item.tool_name, time.time())) * 1000
            )
            # 找最近一个同名 running step 关闭
            for step in reversed(self.tool_steps):
                if step["tool"] == item.tool_name and step["state"] == "running":
                    step["state"] = item.state
                    step["duration_ms"] = duration_ms
                    step["result_preview"] = item.result_preview or ""
                    step["sub_steps"] = item.sub_steps or []
                    break

    @property
    def usage_dict(self) -> dict:
        if self._agent is not None:
            u = self._agent.usage
            return {"input": u.input_tokens, "output": u.output_tokens, "cache": u.cache_tokens}
        return {"input": 0, "output": 0, "cache": 0}
