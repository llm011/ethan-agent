"""授权（consent）框架 —— 敏感操作前请求用户确认。

设计：
- BaseTool.consent_check(**kwargs) 返回描述字符串则需授权，None 则放行
- Agent 在执行工具前检查 consent_check，对需要的工具请求授权
- ConsentProvider 按 channel 实现：
    · TuiConsentProvider：阻塞式 y/N 输入（REPL）
    · WebConsentProvider：向 SSE 流注入 ConsentEvent，await Future；
      前端弹窗确认后 POST /api/consent/{id} 解析 Future
- Provider 通过 ContextVar 注入，请求级隔离

为什么 consent 在 Agent 循环层（而非 tool 内部）：
  tool 执行在 `await executor.execute()` 内部，此时 async generator 无法 yield。
  把 consent 提到 execute 之前，generator 就能 yield ConsentEvent + await 响应。
"""
from __future__ import annotations

import asyncio
import secrets as _secrets
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class ConsentEvent:
    """向流中注入的事件 —— Web 渠道用来请求用户授权。"""
    request_id: str
    description: str
    tool: str = ""
    detail: str = ""


class ConsentProvider:
    """授权提供者基类。"""
    streamed: bool = False  # True = 需要向流注入 ConsentEvent（Web）

    async def request(self, description: str, tool: str = "", detail: str = "") -> bool:
        """请求授权，返回是否允许。streamed=True 时由 Agent 调 create() + await。"""
        return True


class TuiConsentProvider(ConsentProvider):
    """REPL 模式：阻塞式 y/N 输入。"""
    streamed = False

    def __init__(self, console=None):
        self._console = console

    async def request(self, description: str, tool: str = "", detail: str = "") -> bool:
        def _ask() -> bool:
            c = self._console
            if c is not None:
                c.print()
                c.print("[yellow bold]🔒 需要授权[/yellow bold]")
                label = f"[bold]{tool}[/bold] · {description}" if tool else description
                c.print(f"  {label}")
                if detail:
                    c.print(f"  [dim]{detail}[/dim]")
            else:
                print(f"\n🔒 需要授权: {tool} · {description}")
            try:
                ans = input("  允许？ [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            return ans in ("y", "yes", "是", "ok")

        return await asyncio.to_thread(_ask)


class WebConsentProvider(ConsentProvider):
    """Web 模式：创建 Future，Agent yield ConsentEvent 后 await。前端 POST 解析。"""
    streamed = True

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}

    def create(self, description: str, tool: str = "", detail: str = "") -> tuple[ConsentEvent, asyncio.Future]:
        req_id = _secrets.token_hex(8)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        _REGISTRY[req_id] = self  # 全局注册，供 /consent 端点查找
        return ConsentEvent(request_id=req_id, description=description, tool=tool, detail=detail), fut

    def resolve(self, request_id: str, allowed: bool) -> bool:
        fut = self._pending.pop(request_id, None)
        _REGISTRY.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.set_result(allowed)
            return True
        return False

    def cancel_all(self) -> None:
        """请求结束/中断时，把未决的 Future 全部取消，避免泄漏。"""
        for req_id, fut in list(self._pending.items()):
            _REGISTRY.pop(req_id, None)
            if not fut.done():
                fut.cancel()
        self._pending.clear()


# 全局注册表：request_id → WebConsentProvider，跨请求供 /consent 端点查找
_REGISTRY: dict[str, WebConsentProvider] = {}


def resolve_consent(request_id: str, allowed: bool) -> bool:
    """供 /consent 端点调用：解析某个待授权请求。"""
    provider = _REGISTRY.get(request_id)
    if provider is not None:
        return provider.resolve(request_id, allowed)
    return False


_PROVIDER: ContextVar[ConsentProvider | None] = ContextVar("ETHAN_CONSENT_PROVIDER", default=None)


def set_consent_provider(provider: ConsentProvider | None) -> None:
    _PROVIDER.set(provider)


def get_consent_provider() -> ConsentProvider | None:
    return _PROVIDER.get()
