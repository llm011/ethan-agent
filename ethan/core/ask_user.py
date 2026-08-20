"""ask_user 框架 —— Agent 向用户请求选择/确认，阻塞等待回复（20s 超时走默认）。

与 consent（敏感操作授权）完全分离：
- consent: 危险操作的允许/拒绝，由 agent loop 自动触发
- ask_user: LLM 主动发起的业务确认/选择，作为工具调用

设计：
- LLM 调用 ask_user 工具 → agent loop 拦截（不进 executor）
- 向 SSE 流 yield AskUserEvent → 前端显示选择卡片
- await Future（20s 超时）→ 超时返回 default_option
- 用户点击后 POST /api/ask-user/{id} → resolve Future
- 结果作为 tool result 写入 working messages，进入下一轮 LLM
"""

from __future__ import annotations

import asyncio
import secrets as _secrets
from dataclasses import dataclass, field


@dataclass
class AskUserEvent:
    """向 SSE 流注入的事件 —— 请求用户选择。"""

    request_id: str
    question: str
    options: list[dict] = field(default_factory=list)  # [{"label": "...", "value": "..."}]
    default: str = ""  # 超时默认值（对应 options 中某个 value）
    timeout: int = 20  # 秒


class AskUserProvider:
    """Web 模式：创建 Future，Agent yield AskUserEvent 后 await。前端 POST 解析。

    TODO(渠道覆盖): 仅实现 Web 消费端。飞书/微信渠道需替换为飞书交互卡片 / 微信菜单 + 回调，
    否则会 20s 超时走默认值且用户无任何感知。
    """

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}

    def create(
        self,
        question: str,
        options: list[dict],
        default: str = "",
        timeout: int = 20,
    ) -> tuple[AskUserEvent, asyncio.Future]:
        req_id = _secrets.token_hex(8)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        _REGISTRY[req_id] = self
        # 存 options 供端点校验 value 合法性
        _OPTIONS_REGISTRY[req_id] = {str(o.get("value", "")) for o in options}
        return AskUserEvent(
            request_id=req_id,
            question=question,
            options=options,
            default=default,
            timeout=timeout,
        ), fut

    def resolve(self, request_id: str, value: str) -> bool:
        fut = self._pending.pop(request_id, None)
        _REGISTRY.pop(request_id, None)
        _OPTIONS_REGISTRY.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.set_result(value)
            return True
        return False

    def cancel(self, request_id: str) -> None:
        """取消单个待决请求（producer 收尾时按 run 精确清理用）。"""
        fut = self._pending.pop(request_id, None)
        _REGISTRY.pop(request_id, None)
        _OPTIONS_REGISTRY.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.cancel()

    def cancel_all(self) -> None:
        for req_id, fut in list(self._pending.items()):
            _REGISTRY.pop(req_id, None)
            _OPTIONS_REGISTRY.pop(req_id, None)
            if not fut.done():
                fut.cancel()
        self._pending.clear()


# 全局注册表：request_id → AskUserProvider
_REGISTRY: dict[str, AskUserProvider] = {}
# request_id → 合法 value 集合（供端点校验）
_OPTIONS_REGISTRY: dict[str, set[str]] = {}


def resolve_ask_user(request_id: str, value: str) -> bool:
    """供 /ask-user 端点调用：解析某个待选择请求。"""
    provider = _REGISTRY.get(request_id)
    if provider is not None:
        return provider.resolve(request_id, value)
    return False
