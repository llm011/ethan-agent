"""ACP (Agent Client Protocol) stdio server —— 让 Multica 等 ACP client 直接拉起 ethan。

与 `ethan/acp/`（委派编码 agent 的 subprocess 机制，Client 侧）不同，本包是
**Server 侧**：ethan 作为被拉起的 ACP agent，通过 stdio 的 JSON-RPC 与 daemon 通信。

协议：ACP v1（JSON-RPC 2.0 over stdio，newline-delimited），实现走官方 SDK
`agent-client-protocol`（import 名 `acp`）。

模块结构：
- `server.py`  — EthanACPAgent(Agent 协议)：initialize/new_session/load_session/prompt/cancel
- `session.py` — ACPSession：单会话的 stream_chat 消费与事件映射（str/ThinkingEvent/ToolEvent
                 → ACP session_update），落库走 sessions.db（source="acp"）
- `mapping.py` — 内容块/事件类型 → ACP schema 的纯映射函数（无副作用，单测重点）
- `consent.py` — ACPConsentProvider：把 ethan 的 consent 流程桥接到 ACP request_permission
"""
from ethan.acp_server.server import EthanACPAgent, serve

__all__ = ["EthanACPAgent", "serve"]
