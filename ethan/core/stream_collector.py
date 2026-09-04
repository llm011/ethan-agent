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

from ethan.providers.base import InjectEvent, SkillsMatchedEvent, ThinkingEvent, ToolEvent


class StreamCollector:
    def __init__(self):
        self.full: str = ""
        self.thought: str = ""
        self.reasoning: str = ""  # 模型思考链（reasoning_content / thinking），与正文分流：
                                 # - 用于 DeepSeek / Anthropic 等 reasoning 模型的续轮回传
                                 #   （API 要求：上一轮返回过 reasoning_content，下一轮必须原样
                                 #   带回；否则返回 400）
                                 # - 前端不展示该字段，仅内部持久化与回放使用
        self.tool_steps: list[dict] = []
        self.a2ui: list = []  # ui_card 工具汇总的 A2UI envelopes（持久化进 assistant 消息）
        self.mcp_apps: list = []  # 工具 UI 资源数据列表 [{uri, data}]，透传给前端 iframe 渲染
        self.cards: list = []  # 结构化卡片数据（web_search/image_search 产出），持久化后前端渲染横向滚动卡片
        self.matched_skills: list = []  # 本次对话命中的 Skill 列表 [{name, is_default}]
        self._times: dict[str, float] = {}
        self._agent = None  # 可选，用于取 usage
        self._started_at: float | None = None
        self._first_text_at: float | None = None
        # 用户「看到第一个东西」的时刻：第一次工具调用开始 或 首段文本，取较早者。
        # TTFB 以此为基准（而非仅首字），这样先跑工具再出正文的场景也能正确反映「首响应」。
        self._first_visible_at: float | None = None
        # 用户「运行中补充信息」：InjectEvent 来了存这里，下一个 tool start 时挂到 step 上并清空。
        self._pending_injected: list[str] = []

    def bind(self, agent) -> "StreamCollector":
        """绑定 agent，结束时从 agent.usage 取 token。"""
        self._agent = agent
        self._started_at = time.time()
        return self

    def feed(self, item: Any) -> str | None:
        """处理一个 stream_chat 产出项。返回文本块（str）或 None（ToolEvent / ThinkingEvent / SkillsMatchedEvent）。"""
        if isinstance(item, ToolEvent):
            self._handle_tool_event(item)
            return None
        if isinstance(item, ThinkingEvent):
            return None  # 思考内容不计入正文
        if isinstance(item, InjectEvent):
            self._pending_injected.extend(item.messages)
            return None
        if isinstance(item, SkillsMatchedEvent):
            self.matched_skills = item.skills
            return None
        # 先累积 reasoning（与 content/text 独立字段）：DeepSeek reasoning_content 或
        # Anthropic thinking 作为 StreamChunk.reasoning 传入，需要回放给下一轮请求。
        rc = getattr(item, "reasoning", "")
        if rc:
            self.reasoning += rc
            # reasoning 只做累积，不对外 yield（渠道 UI 层通常不会显示思考过程）
        # 文本块
        text = item if isinstance(item, str) else getattr(item, "content", "")
        if not text:
            return None
        if self._first_text_at is None:
            self._first_text_at = time.time()
        if self._first_visible_at is None:
            self._first_visible_at = time.time()
        # 工具开始前累积的文本算作 thought（思考过程）
        if self.tool_steps and any(s["state"] == "running" for s in self.tool_steps):
            # 工具执行中收到的文本：暂归 full，工具结束后由调用方决定
            self.full += text
        else:
            self.full += text
        return text

    def _handle_tool_event(self, item: ToolEvent) -> None:
        if item.state == "start":
            # 工具开始前累积的文本：作为这个工具的 thought（前端可折叠展示），不污染全局
            pre_thought = ""
            if self.full:
                pre_thought = self.full
                self.full = ""
            # 第一次工具调用开始 = 用户看到第一个东西，记为 TTFB 起点
            if self._first_visible_at is None:
                self._first_visible_at = time.time()
            self._times[item.tool_name] = time.time()
            self.tool_steps.append({
                "tool": item.tool_name,
                "id": item.tool_call_id or "",
                "args": item.args_summary,
                "intent": item.intent or "",
                "state": "running",
                "duration_ms": None,
                "result_preview": "",
                "result_detail": "",
                "thought": pre_thought,
                "sub_steps": [],
                "cards": [],
                "entity_type": item.entity_type or "",
                "entity_id": item.entity_id or "",
                "injected": self._pending_injected.copy() if self._pending_injected else [],
            })
            self._pending_injected.clear()
        else:  # done / error
            duration_ms = int(
                (time.time() - self._times.pop(item.tool_name, time.time())) * 1000
            )
            if getattr(item, "ui", None):
                self.a2ui.extend(item.ui)
            if getattr(item, "mcp_app", None):
                self.mcp_apps.append(item.mcp_app)
            if getattr(item, "cards", None):
                self.cards.extend(item.cards)
            # 找最近一个同名 running step 关闭
            for step in reversed(self.tool_steps):
                if step["tool"] == item.tool_name and step["state"] == "running":
                    step["state"] = item.state
                    step["duration_ms"] = duration_ms
                    step["result_preview"] = item.result_preview or ""
                    step["result_detail"] = item.result_detail or ""
                    step["sub_steps"] = item.sub_steps or []
                    # 结构化卡片（如 web_search 结果）挂到该 step，供前端时间线直接渲染
                    if getattr(item, "cards", None):
                        step["cards"] = item.cards
                    # done/error 时补全 entity_type/entity_id（start 时已设，但兜底）
                    if not step.get("entity_type") and item.entity_type:
                        step["entity_type"] = item.entity_type
                    if not step.get("entity_id") and item.entity_id:
                        step["entity_id"] = item.entity_id
                    break

    def flush_pending_injected(self) -> None:
        """流结束时兜底：若仍有未挂载的补充信息（inject 之后模型只回文本、没再调工具，
        `_pending_injected` 就永远等不到 tool start 来消费），挂到最后一个工具步骤上，
        避免这条补充信息既不展示也不持久化而静默丢失。无任何工具步骤时无处可挂，只能放弃
        （此时内容已进模型上下文、模型已据此回复，仅时间线标记缺失）。"""
        if self._pending_injected and self.tool_steps:
            last = self.tool_steps[-1]
            last["injected"] = (last.get("injected") or []) + self._pending_injected
            self._pending_injected.clear()

    @property
    def usage_dict(self) -> dict:
        if self._agent is not None:
            u = self._agent.usage
            return {"input": u.input_tokens, "output": u.output_tokens, "cache": u.cache_tokens}
        return {"input": 0, "output": 0, "cache": 0}

    @property
    def ttfb_ms(self) -> int | None:
        if self._first_visible_at and self._started_at:
            return int((self._first_visible_at - self._started_at) * 1000)
        return None

    @property
    def total_ms(self) -> int | None:
        if self._started_at:
            return int((time.time() - self._started_at) * 1000)
        return None
