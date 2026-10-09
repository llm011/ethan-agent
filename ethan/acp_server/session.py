"""ACPSession —— 单个 ACP 会话的 stream_chat 消费与事件映射。

消费模式照抄 `ethan/interface/routers/mcp_server.py` ask_ethan 的范本：
create_agent(channel="acp") → is_owner=False → WorkingMemory(hot_size=10)
重建历史 → StreamCollector().bind(agent) → async for stream_chat → collector.full 落库。

差异（相对 MCP）：MCP 只回最终文本，ACP 要求**流式**推送中间事件——
- str → AgentMessageChunk（正文增量）
- ThinkingEvent → AgentThoughtChunk（思考增量）
- ToolEvent → ToolCallStart / ToolCallProgress（工具时间线）
- ConsentEvent（ACPConsentProvider 注入）→ 消费掉（Provider 已在后台发
  request_permission），不外发任何 session_update

一个 ACP agent 进程可以并发多个会话（daemon 为每个 session 单独 new_session），
每个 ACPSession 有自己的 Agent 实例，互不共享 working memory。
"""
from __future__ import annotations

import asyncio
import logging

from ethan.acp_server import mapping
from ethan.providers.base import InjectEvent, SkillsMatchedEvent, ThinkingEvent, ToolEvent

logger = logging.getLogger(__name__)


class ACPSession:
    """一个 ACP session_id 对应的 ethan 会话。生命周期 = new_session → N 次 prompt。"""

    def __init__(self, session_id: str, cwd: str, conn):
        self.session_id = session_id  # ethan sessions.db 的会话 id（= ACP session id）
        self.cwd = cwd
        self._conn = conn  # AgentSideConnection，发 session_update / request_permission 用
        self._run_task: asyncio.Task | None = None  # 当前 prompt 的消费 task（cancel 用）

    # ── 会话创建/历史重建 ─────────────────────────────────────────────

    async def create_in_store(self) -> None:
        """在 sessions.db 建会话行（source="acp"）。"""
        from ethan.core.config import get_config
        from ethan.memory.session import get_session_store

        store = await get_session_store()
        model_id = get_config().defaults.model
        await store.create_with_id(self.session_id, model_id, source="acp")

    async def exists_in_store(self) -> bool:
        from ethan.memory.session import get_session_store

        store = await get_session_store()
        return await store.load(self.session_id) is not None

    # ── prompt 主流程 ────────────────────────────────────────────────

    async def run(self, text: str, images: list[dict]) -> str:
        """跑一轮对话，流式推送事件，返回最终文本（stop_reason 判定用）。

        返回 "" 表示没有产出正文（全被工具吃掉/出错），上层可据此选 stop_reason。
        """
        from ethan.core.stream_collector import StreamCollector

        user_msg = await self._save_user_message(text, images)
        # 每轮新建 Agent：无 HTTP 请求上下文，ContextVar/working cache 不能跨轮复用
        # （与 ask_ethan / run_once 的做法一致）
        agent = await self._make_agent()
        history = await self._load_history()
        messages = self._build_context(history) + [user_msg]

        collector = StreamCollector().bind(agent)
        self._run_task = asyncio.current_task()
        try:
            async for item in agent.stream_chat(messages):
                await self._forward(item, collector)
        except asyncio.CancelledError:
            logger.info("ACP session=%s prompt 被取消", self.session_id)
            raise
        except Exception:
            logger.exception("ACP session=%s stream_chat 异常", self.session_id)
            raise
        finally:
            self._run_task = None

        content = collector.full or ""
        await self._save_assistant_message(collector)
        return content

    def cancel(self) -> None:
        """取消正在跑的 prompt（session/cancel 通知）。"""
        task = self._run_task
        if task is not None and not task.done():
            task.cancel()

    # ── 事件转发（ethan 流事件 → ACP session_update）─────────────────

    async def _forward(self, item, collector) -> None:
        if isinstance(item, (InjectEvent, SkillsMatchedEvent)):
            collector.feed(item)
            return
        if isinstance(item, ThinkingEvent):
            collector.feed(item)
            delta = item.delta or ""
            if delta:
                await self._conn.session_update(session_id=self.session_id, update=mapping.thought_chunk(delta))
            return
        if isinstance(item, ToolEvent):
            collector.feed(item)
            await self._forward_tool_event(item)
            return
        text = collector.feed(item)  # str / StreamChunk
        if text:
            await self._conn.session_update(session_id=self.session_id, update=mapping.message_chunk(text))

    async def _forward_tool_event(self, item: ToolEvent) -> None:
        tc_id = mapping.tool_call_id_for(item)
        if item.state == "start":
            update = mapping.tool_call_start(tc_id, item.tool_name, item.args_summary or "")
        else:
            update = mapping.tool_call_update(item.state, tc_id, item.tool_name, item.result_preview or "")
        await self._conn.session_update(session_id=self.session_id, update=update)

    # ── Agent / 历史 / 落库（与 ask_ethan 同构）──────────────────────

    async def _make_agent(self):
        from ethan.core.agent_factory import create_agent
        from ethan.core.consent import set_consent_provider

        agent = create_agent(channel="acp")
        agent.session_id = self.session_id
        agent.is_owner = False  # daemon 无头场景，无「主人本人」语义
        set_consent_provider(ACPConsentProviderForSession(self._conn, self.session_id, agent))
        return agent

    async def _save_user_message(self, text: str, images: list[dict]):
        from ethan.memory.session import get_session_store

        store = await get_session_store()
        msg_kwargs = {"images": images} if images else {}
        from ethan.providers.base import Message

        user_msg = Message(role="user", content=text, **msg_kwargs)
        await store.save_message(self.session_id, user_msg)
        return user_msg

    async def _load_history(self):
        from ethan.memory.session import get_session_store

        store = await get_session_store()
        session_obj = await store.load(self.session_id)
        return session_obj.messages if session_obj else []

    @staticmethod
    def _build_context(history):
        """WorkingMemory(hot_size=10) 重建历史上下文 —— 与 ask_ethan 完全同构。"""
        from ethan.memory.working import MemoryConfig, WorkingMemory

        memory = WorkingMemory(config=MemoryConfig(hot_size=10))
        pairs: list = []
        hist_ua = [m for m in history if m.role in ("user", "assistant")]
        i = 0
        while i < len(hist_ua) - 1:
            if hist_ua[i].role == "user" and hist_ua[i + 1].role == "assistant":
                pairs.append((hist_ua[i], hist_ua[i + 1]))
                i += 2
            else:
                i += 1
        for u, a in pairs[-memory.config.hot_size:]:
            memory.hot.append(u)
            memory.hot.append(a)
        return memory.build_context()

    async def _save_assistant_message(self, collector) -> None:
        from ethan.memory.session import get_session_store
        from ethan.providers.base import Message

        content = collector.full or ""
        if not content:
            return
        store = await get_session_store()
        asst_msg = Message(
            role="assistant",
            content=content,
            thought=collector.thought,
            usage=collector.usage_dict,
            tool_steps=collector.tool_steps or [],
        )
        await store.save_message(self.session_id, asst_msg)
        await store.touch(self.session_id)

    # ── 历史重放（session/load）──────────────────────────────────────

    async def replay_history(self) -> None:
        """把 sessions.db 里的历史消息重放为 session_update（client 重建 UI 用）。"""
        from ethan.memory.session import get_session_store

        store = await get_session_store()
        session_obj = await store.load(self.session_id)
        if not session_obj:
            return
        for msg in session_obj.messages:
            if msg.role == "user":
                if msg.content:
                    await self._conn.session_update(
                        session_id=self.session_id, update=mapping.user_chunk(msg.content)
                    )
                for block in mapping.image_blocks_from_message_images(msg.images):
                    from acp.schema import UserMessageChunk

                    await self._conn.session_update(
                        session_id=self.session_id,
                        update=UserMessageChunk(sessionUpdate="user_message_chunk", content=block),
                    )
            elif msg.role == "assistant" and msg.content:
                await self._conn.session_update(
                    session_id=self.session_id, update=mapping.message_chunk(msg.content)
                )


def ACPConsentProviderForSession(conn, acp_session_id: str, agent):
    """构造绑定到当前会话的 ACPConsentProvider。

    独立函数便于测试 patch（monkeypatch 本符号即可替换 provider 行为）。
    """
    from ethan.acp_server.consent import ACPConsentProvider

    return ACPConsentProvider(conn=conn, acp_session_id=acp_session_id, session_id=acp_session_id)
