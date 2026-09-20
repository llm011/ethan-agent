"""MCP Server 端点：暴露 ask_ethan 工具供豆包等外部 MCP 客户端调用。"""
from __future__ import annotations

import asyncio
import logging

from mcp.server.fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ethan.core.config import get_config
from ethan.memory.session import _generate_id, get_session_store
from ethan.providers.base import Message

logger = logging.getLogger(__name__)

mcp_server = FastMCP("Ethan", stateless_http=True)
mcp_server.settings.streamable_http_path = "/"


@mcp_server.tool()
async def ask_ethan(prompt: str, session_id: str | None = None) -> str:
    """Ask Ethan agent a question. Ethan can search the web, read files, manage tasks, and more.

    Args:
        prompt: Your question or instruction for Ethan.
        session_id: Optional session ID for multi-turn conversation continuity.

    Returns:
        Ethan's response text, with session_id appended for follow-up use.
    """
    from ethan.core.stream_collector import StreamCollector
    from ethan.interface.routers.deps import create_agent
    from ethan.memory.working import MemoryConfig, WorkingMemory
    from ethan.providers.base import InjectEvent, SkillsMatchedEvent, ThinkingEvent, ToolEvent

    if not session_id:
        session_id = _generate_id()
        store = await get_session_store()
        model_id = get_config().defaults.model
        await store.create_with_id(session_id, model_id, source="mcp")
        init_title = prompt.strip().replace("\n", " ")[:40]
        await store.update_title(session_id, init_title)
    else:
        store = await get_session_store()
        existing = await store.load(session_id)
        if not existing:
            model_id = get_config().defaults.model
            await store.create_with_id(session_id, model_id, source="mcp")

    agent = create_agent(channel="mcp")
    agent.session_id = session_id
    agent.is_owner = False

    user_msg = Message(role="user", content=prompt)
    await store.save_message(session_id, user_msg)

    session_obj = await store.load(session_id)
    history = session_obj.messages if session_obj else []

    memory = WorkingMemory(config=MemoryConfig(hot_size=10))
    pairs: list[tuple[Message, Message]] = []
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

    messages = memory.build_context() + [user_msg]

    collector = StreamCollector().bind(agent)
    try:
        async for item in agent.stream_chat(messages):
            if isinstance(item, (ToolEvent, ThinkingEvent, SkillsMatchedEvent, InjectEvent)):
                collector.feed(item)
                continue
            collector.feed(item)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception("ask_ethan error session=%s", session_id)
        return f"[Error: {e}]\n\n[session_id={session_id}]"

    content = collector.full or ""
    if content:
        asst_msg = Message(
            role="assistant", content=content,
            thought=collector.thought,
            usage=collector.usage_dict,
            tool_steps=collector.tool_steps or [],
        )
        await store.save_message(session_id, asst_msg)
        await store.touch(session_id)

    return f"{content}\n\n[session_id={session_id}]"


def get_mcp_lifespan(mcp_app=None):
    """MCP streamable-HTTP 的 session manager lifespan。

    **为什么需要这个函数**：`/mcp` 是 mount 到主 FastAPI app 上的，而 Starlette 的
    `Mount` **不会**转发子应用的 lifespan（只有交给 Uvicorn 的那个顶层 lifespan 会被
    调用）。`streamable_http_app()` 却把 session manager 的启动放在它返回的那个 Starlette
    的 lifespan 里 —— 于是没人 enter 它，session manager 的 task group 从未初始化，
    **每一个**请求（连 initialize 都是）都抛
    `RuntimeError: Task group is not initialized. Make sure to use run().`，
    表现为 MCP 端点整体 HTTP 500。

    只在子应用上挂 `lifespan=` 是**没用的**（Mount 不转发，我实测过），必须由 `api.py`
    的顶层 lifespan 显式 enter 这里返回的 context。

    `mcp_app` 必须是 `get_mcp_app()` 的返回值本身：session manager 的 `.run()` 每实例只能
    调用一次，且驱动 lifespan 的实例必须与处理请求的实例是同一个，否则 task group 依然
    没启动。不传时退回 `get_mcp_app()` 新建一个，仅供单测等场景。
    """
    app = mcp_app if mcp_app is not None else get_mcp_app()
    inner = getattr(app, "_ethan_inner_mcp_app", None)
    if inner is None:  # 传进来的不是 get_mcp_app() 的产物
        inner = mcp_server.streamable_http_app()
    return inner.router.lifespan_context


def get_mcp_app():
    """Return the Starlette ASGI app for mounting, with API key auth middleware."""

    class MCPAuthMiddleware:
        def __init__(self, app: ASGIApp):
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] not in ("http", "websocket"):
                await self.app(scope, receive, send)
                return

            cfg = get_config()
            mcp_key = cfg.network.mcp_api_key
            if not mcp_key:
                await self.app(scope, receive, send)
                return

            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth.startswith("Bearer ") and auth.removeprefix("Bearer ").strip() == mcp_key:
                await self.app(scope, receive, send)
                return

            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)

    app = mcp_server.streamable_http_app()

    from starlette.applications import Starlette
    from starlette.routing import Mount

    # 这里不再挂 lifespan：本 app 是被 api.py mount 的，Starlette 的 Mount 不会转发
    # 子应用 lifespan，挂在这儿等于没挂。session manager 由顶层 lifespan 经
    # get_mcp_lifespan() 启动（见该函数 docstring）。
    authed_app = Starlette(
        routes=[Mount("/", app=app)],
        middleware=[Middleware(MCPAuthMiddleware)],
    )
    # 记下 inner app，供 get_mcp_lifespan(authed_app) 取到同一个 session manager
    authed_app._ethan_inner_mcp_app = app
    return authed_app
