"""MCP Client — 连接外部 MCP Server，自动注册其工具到 ToolRegistry。

支持两种传输方式：
  - streamable HTTP：远程服务（url + 可选 Bearer Token），如滴答清单 MCP
    (https://mcp.dida365.com)。这是滴答清单官方唯一支持的协议。
  - stdio：本地子进程（command + args），向后兼容旧用法。

远程/子进程会话运行在独立的常驻事件循环线程里（MCPManager._loop）。
原因：create_agent → build_tool_registry 是同步调用，且常在 FastAPI 异步
上下文中执行，不能直接 asyncio.run()（会关掉 session 的后台读任务）。
MCP 工具的 run() 在 Agent 的异步循环里被调，通过 run_coroutine_threadsafe
把 call_tool 桥接到常驻循环执行，保证 session 存活。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable

try:
    import httpx
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamable_http_client
    _mcp_available = True
except ImportError:  # pragma: no cover - mcp 未安装时静默降级
    _mcp_available = False

from ethan.tools.base import BaseTool


class LoopRunner:
    """把 awaitable 调度到常驻事件循环执行，并返回结果。"""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def run(self, coro: Awaitable[Any]) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await asyncio.wrap_future(fut)


class MCPTool(BaseTool):
    """包装 MCP server 暴露的工具为 BaseTool。

    外部状态（任务/数据库/第三方数据）随时可变，因此：
      - cacheable = False：同参数结果不缓存，避免读到过期数据。
      - no_compress = True：任务详情等原样给模型，摘要会丢关键字段。
    """

    cacheable = False
    no_compress = True

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        session: ClientSession,
        runner: LoopRunner,
        call_name: str | None = None,
    ):
        self._name = name
        self._call_name = call_name or name
        self._description = description
        self._parameters = parameters
        self._session = session
        self._runner = runner

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def run(self, **kwargs) -> str:
        # 调用时用原始工具名（不带 server 前缀），前缀只用于本地展示与去重
        result = await self._runner.run(self._session.call_tool(self._call_name, arguments=kwargs))
        if result.content:
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "\n".join(parts) if parts else "(empty result)"
        return "(empty result)"


class MCPClient:
    """管理与一个 MCP server 的连接（HTTP 或 stdio）。"""

    def __init__(
        self,
        name: str,
        url: str = "",
        command: str = "",
        args: list[str] | None = None,
        bearer_token: str = "",
    ):
        self.name = name
        self._url = url
        self._command = command
        self._args = args or []
        self._token = bearer_token or ""
        self.session: ClientSession | None = None
        self._read_cm = None
        self._session_cm = None

    @property
    def is_http(self) -> bool:
        return bool(self._url) and not self._command

    async def connect(self) -> list[dict[str, Any]]:
        """建立连接并返回该 server 暴露的工具元数据（name/description/schema）。"""
        if self.is_http:
            headers: dict[str, str] = {}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            # trust_env=False：不受 HTTP_PROXY/HTTPS_PROXY 影响，避免本地/私网
            # MCP server 被开发机代理（如 Clash 127.0.0.1:7890）劫持导致连接失败。
            http_client = httpx.AsyncClient(headers=headers, trust_env=False)
            self._read_cm = streamable_http_client(
                self._url, http_client=http_client, terminate_on_close=True
            )
        else:
            params = StdioServerParameters(command=self._command, args=self._args)
            self._read_cm = stdio_client(params)
        try:
            streams = await self._read_cm.__aenter__()
        except Exception:
            # 进入失败也在 finally 里尝试关闭，避免泄漏
            await self._read_cm.__aexit__(None, None, None)
            raise
        if len(streams) == 3:  # http: (read, write, get_session_id)
            self._read, self._write, self._get_session_id = streams
        else:  # stdio: (read, write)
            self._read, self._write = streams
        self._session_cm = ClientSession(self._read, self._write)
        self.session = await self._session_cm.__aenter__()
        await self.session.initialize()

        tools_result = await self.session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "schema": t.inputSchema if t.inputSchema else {"type": "object", "properties": {}},
            }
            for t in tools_result.tools
        ]

    async def disconnect(self) -> None:
        if self._session_cm:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                pass
        if self._read_cm:
            try:
                await self._read_cm.__aexit__(None, None, None)
            except Exception:
                pass
        self.session = None


class MCPManager:
    """单例 — 管理所有配置的 MCP server 连接。

    连接缓存：首次 build_tool_registry 时连接并缓存，之后命中缓存，避免每次请求
    都握手。一个常驻后台线程承载全部 session 的事件循环。
    """

    _instance: "MCPManager | None" = None

    @classmethod
    def get(cls) -> "MCPManager":
        if cls._instance is None:
            cls._instance = MCPManager()
        return cls._instance

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._clients: dict[str, MCPClient] = {}
        self._tools: list[MCPTool] = []
        self._connected = False

    # ── 循环 / 桥接 ──────────────────────────────────────────────
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or not self._loop.is_running():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True, name="mcp-loop")
            thread.start()
            self._loop = loop
            self._thread = thread
        return self._loop

    def _run(self, coro: Awaitable[Any]) -> Any:
        """同步阻塞地在一个 coroutine 上等待其完成（在常驻循环里执行）。"""
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result()

    def _configured_servers(self) -> list[Any]:
        if not _mcp_available:
            return []
        try:
            from ethan.core.config import get_config
            return [s for s in get_config().tools.mcp.servers if s.enabled]
        except Exception:
            return []

    # ── 工具暴露 ─────────────────────────────────────────────────
    def get_tools(self) -> list[MCPTool]:
        """返回已连接 MCP server 暴露的全部工具（同步）。

        无配置 / 未装 mcp 包时返回空列表。连接失败只跳过该 server，不阻塞工具注册。
        """
        if not _mcp_available:
            return []
        if not self._configured_servers():
            return []
        with self._lock:
            if self._connected:
                return list(self._tools)
            self._ensure_loop()
            runner = LoopRunner(self._loop)
            for server in self._configured_servers():
                client = MCPClient(
                    name=server.name,
                    url=server.url,
                    command=server.command,
                    args=server.args,
                    bearer_token=server.bearer_token,
                )
                try:
                    metas = self._run(client.connect())
                except Exception as e:  # 单个 server 失败不影响其他工具注册
                    import logging
                    logging.getLogger(__name__).warning(
                        f"[mcp] 连接 {server.name} 失败: {e}", exc_info=True
                    )
                    continue
                self._clients[server.name] = client
                for meta in metas:
                    tool = MCPTool(
                        name=f"{server.name}_{meta['name']}",
                        description=meta["description"],
                        parameters=meta["schema"],
                        session=client.session,
                        runner=runner,
                        call_name=meta["name"],
                    )
                    self._tools.append(tool)
            self._connected = True
            return list(self._tools)

    def disconnect_all(self) -> None:
        """断开全部连接并复位（配置变更后调用 re-get 会重新连接）。"""
        with self._lock:
            for client in self._clients.values():
                try:
                    self._run(client.disconnect())
                except Exception:
                    pass
            self._clients.clear()
            self._tools.clear()
            self._connected = False


def get_mcp_manager() -> MCPManager:
    """进程级 MCP 管理器单例入口。"""
    return MCPManager.get()