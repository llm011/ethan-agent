"""wait_for_user 框架 —— Agent 等待用户完成外部操作后继续（300s 超时）。

与 ask_user（业务选择，20s）和 consent（危险操作授权，300s）分离：
- ask_user: LLM 主动发起的业务确认/多选分支，短超时
- consent: 系统自动触发的危险操作授权，是/否
- wait_for_user: LLM 主动发起的"等待用户完成外部操作"，长超时

典型场景：OAuth 授权（飞书/GitHub）、需要用户在浏览器中操作后确认、
需要用户填写验证码/确认码等。

设计：
- LLM 调用 wait_for_user 工具 → agent loop 拦截（不进 executor）
- 向 SSE 流 yield WaitForUserEvent → 前端显示等待卡片
- await Future（300s 超时 → 走 "timeout"）
- 用户点击后 POST /api/wait-for-user/{id} → resolve Future
- 结果作为 tool result 写入 working messages，进入下一轮 LLM
"""
from __future__ import annotations

import asyncio
import secrets as _secrets
from dataclasses import dataclass


@dataclass
class WaitForUserEvent:
    """向 SSE 流注入的事件 —— 请求用户完成外部操作后确认。"""
    request_id: str
    prompt: str
    input_type: str = "confirm"  # "confirm" | "text"
    placeholder: str = ""
    confirm_label: str = "已完成"
    cancel_label: str = "取消"
    timeout: int = 300  # 秒


class WaitForUserProvider:
    """Web 模式：创建 Future，Agent yield WaitForUserEvent 后 await。前端 POST 解析。"""

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}

    def create(
        self,
        prompt: str,
        input_type: str = "confirm",
        placeholder: str = "",
        confirm_label: str = "已完成",
        cancel_label: str = "取消",
        timeout: int = 300,
    ) -> tuple[WaitForUserEvent, asyncio.Future]:
        req_id = _secrets.token_hex(8)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        _REGISTRY[req_id] = self
        return WaitForUserEvent(
            request_id=req_id,
            prompt=prompt,
            input_type=input_type,
            placeholder=placeholder,
            confirm_label=confirm_label,
            cancel_label=cancel_label,
            timeout=timeout,
        ), fut

    def resolve(self, request_id: str, value: str) -> bool:
        fut = self._pending.pop(request_id, None)
        _REGISTRY.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.set_result(value)
            return True
        return False

    def cancel_all(self) -> None:
        for req_id, fut in list(self._pending.items()):
            _REGISTRY.pop(req_id, None)
            if not fut.done():
                fut.cancel()
        self._pending.clear()


# 全局注册表：request_id → WaitForUserProvider
_REGISTRY: dict[str, WaitForUserProvider] = {}


def resolve_wait_for_user(request_id: str, value: str) -> bool:
    """供 /wait-for-user 端点调用：解析某个待确认请求。"""
    provider = _REGISTRY.get(request_id)
    if provider is not None:
        return provider.resolve(request_id, value)
    return False
