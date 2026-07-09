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
    always: bool = False  # 高危调用（如 rm -rf）：每次都须确认，后台任务也绝不自动批准


class ConsentProvider:
    """授权提供者基类。"""
    streamed: bool = False  # True = 需要向流注入 ConsentEvent（Web）
    session_id: str = ""    # 所属会话；用于 session 维度授权记忆（同会话同工具授权过不再弹）

    async def request(self, description: str, tool: str = "", detail: str = "") -> bool:
        """请求授权，返回是否允许。streamed=True 时由 Agent 调 create() + await。"""
        return True

    def policy_check(self, tool: str, side_effect: bool) -> str | None:
        """渠道级硬策略：在 consent_check 之外，按工具自身属性决定是否直接拒绝。

        返回非空字符串 → 直接拒绝（字符串是拒绝原因，回给模型当作工具结果）；
        返回 None → 不拦截，交给后续 consent 流程。
        默认不拦截。用于三方渠道（如飞书）认主人后，非主人不得执行 side_effect 工具。
        """
        return None


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

    def __init__(self, session_id: str = ""):
        self._pending: dict[str, asyncio.Future] = {}
        self.session_id = session_id

    def create(self, description: str, tool: str = "", detail: str = "", always: bool = False) -> tuple[ConsentEvent, asyncio.Future]:
        req_id = _secrets.token_hex(8)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        _REGISTRY[req_id] = self  # 全局注册，供 /consent 端点查找
        return ConsentEvent(request_id=req_id, description=description, tool=tool, detail=detail, always=always), fut

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


class AutoConsentProvider(ConsentProvider):
    """自动批准所有授权请求（自动化/测试/API 调用场景）。"""
    streamed = False

    def __init__(self, session_id: str = ""):
        self.session_id = session_id

    async def request(self, description: str, tool: str = "", detail: str = "") -> bool:
        return True

    def cancel_all(self) -> None:
        """No-op：AutoConsent 无 pending futures。"""


class ChannelGuardProvider(ConsentProvider):
    """三方渠道（飞书/微信等）的硬策略守卫。

    与 TUI/Web 不同，三方渠道没有交互式确认 UI。一旦渠道已认主人（owner_claimed），
    非主人发来的指令对 side_effect 工具一律【直接拒绝】，不放行也不询问——纯靠 prompt
    约束不可靠，这里在 Agent 循环层做硬拦截。

    - is_owner=True：放行（仍受 consent_check 里的密钥等单独保护）
    - is_owner=False 且 owner_claimed=True：拒绝所有 side_effect 工具
    - owner_claimed=False（还没认主人）：不装这个 provider（permissive），由 lark_events 决定
    """
    streamed = False

    def __init__(self, is_owner: bool):
        self._is_owner = is_owner

    async def request(self, description: str, tool: str = "", detail: str = "") -> bool:
        # consent_check 命中（如读密钥）：主人放行，非主人拒绝
        return self._is_owner

    def policy_check(self, tool: str, side_effect: bool) -> str | None:
        if self._is_owner:
            return None
        if side_effect:
            return (
                f"[已拒绝] 工具 {tool} 会产生副作用（改数据/执行/对外操作），"
                "当前会话的发起人不是主人，无权执行此类操作。"
                "请告知用户：这类操作仅限主人，需主人在主会话中授权。"
            )
        return None


# 全局注册表：request_id → WebConsentProvider，跨请求供 /consent 端点查找
_REGISTRY: dict[str, WebConsentProvider] = {}

# session 维度授权记忆：{session_id: {scope, ...}}。scope 由工具的 consent_scope() 决定——
# 默认是工具名（整工具授权一次），文件类工具返回目录路径（目录授权后子目录免问）。
_SESSION_GRANTS: dict[str, set[str]] = {}


def is_granted(session_id: str, scope: str) -> bool:
    """该 session 是否已对此 scope 授权过。

    - 路径型 scope（以 / 开头）：被任一已授权的祖先目录覆盖即算授权
      （授权 /a/b 后，/a/b 及 /a/b/c 等子目录都放行）。
    - 非路径 scope（工具名、get_secret 等）：精确匹配。
    """
    if not session_id or not scope:
        return False
    granted = _SESSION_GRANTS.get(session_id, set())
    if scope in granted:
        return True
    if scope.startswith("/"):
        from pathlib import Path
        sp = Path(scope)
        for g in granted:
            if g.startswith("/"):
                gp = Path(g)
                if gp == sp or gp in sp.parents:
                    return True
    return False


def record_grant(session_id: str, scope: str) -> None:
    """记录一次 session 维度授权（scope = 工具名 或 目录路径）。"""
    if session_id and scope:
        _SESSION_GRANTS.setdefault(session_id, set()).add(scope)


def clear_session_grants(session_id: str) -> None:
    """清除某 session 的授权记忆（会话删除时调用）。"""
    _SESSION_GRANTS.pop(session_id, None)


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
