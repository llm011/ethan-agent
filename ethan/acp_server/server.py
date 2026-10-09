"""EthanACPAgent —— ACP v1 agent 侧实现（官方 SDK 的 Agent 协议）。

入口 `serve()`：配置 stderr 日志（stdout 只允许 JSON-RPC）后
`asyncio.run(run_agent(EthanACPAgent()))` 起 stdio 主循环。

协议要点（ACP v1）：
- agent 启动后静默等待 client 的 initialize
- session 生命周期：session/new → session/prompt（流式 session/update）→ session/cancel
- session/load：可选能力；我们声明 load_session=True，从 sessions.db 重放历史
- prompt 返回 PromptResponse(stop_reason=...)：end_turn / cancelled
"""
from __future__ import annotations

import logging
import sys

from acp import Agent, run_agent
from acp.schema import (
    AgentCapabilities,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptCapabilities,
    PromptResponse,
)

from ethan.acp_server import mapping
from ethan.acp_server.session import ACPSession

logger = logging.getLogger(__name__)


def _configure_stderr_logging() -> None:
    """stdio 模式下根 logger 必须走 stderr：stdout 上一行非 JSON-RPC 输出
    就会让 client 解析炸掉。ethan 核心/工具层已排查过（print 全走 stderr，
    logging 无 handler 时默认 stderr），这里显式兜底。"""
    root = logging.getLogger()
    for h in list(root.handlers):
        # 已有 handler 若指向 stdout，换成 stderr
        if getattr(h, "terminator", None) is not None and getattr(getattr(h, "stream", None), "name", "") == "<stdout>":
            root.removeHandler(h)
    if not any(
        isinstance(h, logging.StreamHandler) and getattr(getattr(h, "stream", None), "name", "") == "<stderr>"
        for h in root.handlers
    ):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
        root.addHandler(handler)
    root.setLevel(logging.INFO)


class EthanACPAgent(Agent):
    """ACP agent：管理 ACPSession 生命周期，prompt 时驱动 stream_chat。"""

    def __init__(self):
        self._conn = None
        self._sessions: dict[str, ACPSession] = {}

    # SDK 在连接建立后回调（官方 echo_agent 同款模式）
    def on_connect(self, conn) -> None:
        self._conn = conn

    # ── initialize ───────────────────────────────────────────────────

    async def initialize(self, protocol_version: int, client_capabilities=None, client_info=None, **kw):
        return InitializeResponse(
            protocol_version=1,
            agent_capabilities=AgentCapabilities(
                load_session=True,
                prompt_capabilities=PromptCapabilities(image=True, embedded_context=True),
            ),
        )

    # ── session/new ──────────────────────────────────────────────────

    async def new_session(self, cwd: str, mcp_servers=None, **kw) -> NewSessionResponse:
        from ethan.memory.session import _generate_id

        session_id = _generate_id()
        session = ACPSession(session_id=session_id, cwd=cwd, conn=self._conn)
        await session.create_in_store()
        self._sessions[session_id] = session
        return NewSessionResponse(session_id=session_id)

    # ── session/load（历史会话恢复）───────────────────────────────────

    async def load_session(self, session_id: str, cwd: str = "", mcp_servers=None, **kw) -> LoadSessionResponse:
        session = ACPSession(session_id=session_id, cwd=cwd, conn=self._conn)
        if not await session.exists_in_store():
            from acp.exceptions import RequestError

            raise RequestError.invalid_params({"details": f"Unknown session: {session_id}"})
        await session.replay_history()
        self._sessions[session_id] = session
        return LoadSessionResponse(session_id=session_id)

    # ── session/prompt ───────────────────────────────────────────────

    async def prompt(self, session_id: str, prompt: list, **kw) -> PromptResponse:
        session = self._sessions.get(session_id)
        if session is None:
            # daemon 可能重启后直接 prompt（未走 load）；尽力按未知会话建新档

            logger.warning("prompt for unknown session %s, creating implicitly", session_id)
            session = ACPSession(session_id=session_id, cwd="", conn=self._conn)
            await session.create_in_store()
            self._sessions[session_id] = session

        text, images = mapping.blocks_to_text_and_images(prompt)
        if not text and not images:
            return PromptResponse(stopReason="end_turn")
        # 保存用户消息前先确保标题存在（首轮用首行截断，与 ask_ethan 一致）
        await self._ensure_title(session_id, text)
        try:
            await session.run(text=text, images=images)
        except Exception:
            # 上游异常已记日志；协议上仍要回响应，正文已尽力推送，归 end_turn
            return PromptResponse(stopReason="end_turn")
        return PromptResponse(stopReason="end_turn")

    # ── session/cancel（notification，无响应）─────────────────────────

    async def cancel(self, session_id: str, **kw) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.cancel()

    # ── helpers ──────────────────────────────────────────────────────

    async def _ensure_title(self, session_id: str, text: str) -> None:
        """首轮 prompt 时用首行设初始标题（后续 _auto_title 可能智能覆盖）。"""
        if not text:
            return
        try:
            from ethan.memory.session import get_session_store, strip_title_decoration

            store = await get_session_store()
            session_obj = await store.load(session_id)
            if session_obj is not None and session_obj.title in ("", "新对话"):
                init_title = strip_title_decoration(text.strip().replace("\n", " "))[:40].strip()
                if init_title:
                    await store.update_title(session_id, init_title)
        except Exception:
            logger.debug("ensure_title failed for %s", session_id, exc_info=True)


def serve() -> None:
    """`ethan acp` 入口：stderr 日志 + stdio 主循环。"""
    _configure_stderr_logging()
    asyncio_run(run_agent(EthanACPAgent()))


def asyncio_run(coro) -> None:
    """薄封装便于测试 patch；仅透传 asyncio.run。"""
    import asyncio

    asyncio.run(coro)
