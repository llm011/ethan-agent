# ACP Server：让 Multica 等 ACP client 直接拉起 Ethan

## 概述

`ethan acp` 启动一个 **ACP（Agent Client Protocol）v1 stdio server**，让支持 ACP 的客户端（典型：Multica daemon）把 Ethan 作为 runtime 直接拉起，无需 Claude Code + MCP 中转。

**与 `docs/acp.md` 的区别**：那篇讲的是 Ethan 作为 **Client** 委派编码任务给 Claude Code（`ethan/acp/`）；本篇讲 Ethan 作为 **Server** 被别的 client 拉起（`ethan/acp_server/`）。方向相反，互不依赖。

- 协议：ACP v1 = JSON-RPC 2.0 over stdio（newline-delimited）
- SDK：官方 Python SDK [`agent-client-protocol`](https://pypi.org/project/agent-client-protocol/)（import 名 `acp`），版本 >=0.12.1
- 协议纪律：**stdout 上只允许 JSON-RPC 帧**，ethan 的所有日志走 stderr

---

## 快速接入 Multica

Multica 的 runtime 列表没有 ethan provider 时，用 custom runtime profile 接入。选 `protocol_family=kimi`——kimi 家族走的就是标准 ACP v1，daemon 只会追加协议子命令、不注入额外 env，与 `ethan acp` 完全匹配：

```bash
multica runtime profile create \
  --protocol-family kimi \
  --command-name ethan \
  --display-name Ethan
```

daemon 启动顺序：`ethan acp <Multica 协议参数> <agent custom_args>`。daemon 无头模式会**自动应答** request_permission（优先 allow_session → allow_once → reject_once，绝不自动 allow_always），并注入 `MULTICA_TOKEN` / `MULTICA_TASK_ID` / `MULTICA_AGENT_ID` / `MULTICA_WORKSPACE_ID` / `MULTICA_SERVER_URL` 环境变量（ethan 侧目前不消费，仅排障时可看）。

手动验证（不用 Multica，直接 stdio 对话）：

```bash
echo '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' \
  | ethan acp 2>/dev/null
# → {"jsonrpc":"2.0","id":0,"result":{"protocolVersion":1,"agentCapabilities":{"loadSession":true}}}
```

（注意：shell 重定向 `| file` 会因 asyncio pipe transport 拒绝普通文件而报错，真实 client 都是 subprocess.PIPE，不受影响。）

---

## 模块结构

```
ethan/acp_server/
├── __init__.py   # re-export EthanACPAgent / serve
├── server.py     # EthanACPAgent(Agent)：initialize/new_session/load_session/prompt/cancel + serve()
├── session.py    # ACPSession：单会话的 stream_chat 消费 + 事件映射 + 落库
├── mapping.py    # 纯映射函数：内容块/事件 → ACP schema（单测重点）
└── consent.py    # ACPConsentProvider：consent 桥接到 ACP request_permission
```

会话生命周期与 ethan 其他渠道一致：`session/new` 在 sessions.db 建行（`source="acp"`）→ 每轮 prompt 走 `create_agent(channel="acp")` + `WorkingMemory(hot_size=10)` 重建历史 → `stream_chat` 消费 → 落库。ACP 会话出现在 Web 端会话列表里，可跨端查看。

## 协议映射

### initialize 声明

| 能力 | 值 | 说明 |
|---|---|---|
| `agentCapabilities.loadSession` | true | 支持 session/load 历史重放 |
| `promptCapabilities.image` | true | prompt 可带 ImageContentBlock（base64 → `Message.images`） |
| `promptCapabilities.embeddedContext` | true | 接受嵌入式上下文块（忽略） |

### 流事件（stream_chat → session/update）

| ethan 事件 | ACP update | 判别字段 |
|---|---|---|
| `str`（正文增量） | `AgentMessageChunk` | `sessionUpdate="agent_message_chunk"` |
| `ThinkingEvent(delta)` | `AgentThoughtChunk` | `sessionUpdate="agent_thought_chunk"` |
| `ToolEvent(state=start)` | `ToolCallStart` | `sessionUpdate="tool_call"`，status=in_progress |
| `ToolEvent(state=done/error)` | `ToolCallProgress` | `sessionUpdate="tool_call_update"`，completed/failed，结果摘要进 content |

stopReason：正常结束与上游异常一律 `end_turn`；`session/cancel` 取消后无响应（协议上 cancel 是 notification）。

### ToolKind 映射

read（file_read/file_list/skill_read/knowledge_read/plan_read/…）、edit（file_write/file_edit/memory_write/…）、execute（shell/browser/desktop_notify/…）、search（rg_search/fd_find）、fetch（web_search/web_fetch/image_search/weather）、move（deliver_file）、think（ask_user/decide/wait_for_user）、其他 → other。

### session/load（历史重放）

sessions.db 里的历史消息按序重放为 `UserMessageChunk` / `AgentMessageChunk`（含图片块）；未知 session id 返回 Invalid params。

## 权限模型（consent → request_permission）

复用 ethan 的 ConsentProvider 体系（`streamed=True`，与 Web 渠道同构）：agent loop yield `ConsentEvent` 后 await Future，`ACPConsentProvider` 在后台调 `conn.request_permission()`，daemon 的应答（`AllowedOutcome/DeniedOutcome`）解析回 Future。

- options：本会话内允许（allow_always）→ 允许一次（allow_once）→ 拒绝（reject_once）
- **高危操作（`consent_always=True`，如 rm -rf）不提供「本会话内允许」**，逼 client 只能逐次放行或拒绝
- request_permission 本身异常（client 不支持该方法）→ 按拒绝处理，不挂起 agent loop
- session 维度授权记忆（`is_granted`/`record_grant`）与 Web 渠道共用：同会话同 scope 已授权过不再弹

## 渠道差异（vs web/repl）

- **不注册 `ask_user` / `wait_for_user` / `ui_card`**：这三个工具依赖 SSE + POST 消费端，ACP 渠道没有，注册了只会超时走默认且用户无感知
- `agent.is_owner = False`：daemon 场景无「主人本人」语义
- 每轮 prompt 新建 Agent 实例（无 HTTP 请求上下文，ContextVar 不跨轮复用），与 MCP 渠道 `ask_ethan` 同构

## SDK 实测坑（写代码前必读）

1. **所有 session_update 必须带 `sessionUpdate` 判别字段**（`AgentMessageChunk(sessionUpdate="agent_message_chunk", ...)`），漏了会被 agent 侧 pydantic 校验拒掉，client 收到 Invalid params。
2. **ToolKind / ToolCallStatus 是 Literal 字符串**，直接传 str；`ToolKind.execute` 这种属性访问不存在。
3. **`ToolCallProgress.content` 的元素是 `ContentToolCallContent(type="content", content=<单个内容块>)`**，不是裸 TextContentBlock 列表。
4. **union/discriminator 模型都要显式 type**：`TextContentBlock(type="text", text=...)`。
5. `AllowedOutcome` 的字面量是 `outcome="selected"`（不是 "chosen"），选项 id 字段是 `option_id`（alias `optionId`）。
6. SDK 的 stdio 用 asyncio pipe transport：**stdout/stdin 必须是 pipe/char device**，shell 里重定向到普通文件会 `ValueError`；真实 client（subprocess.PIPE）不受影响。

## 测试

`tests/test_acp_server.py`（36 用例）：
- mapping 纯函数：内容块转换 / 判别字段 / ToolKind
- 协议层：FakeTransport 进程内直发 JSON-RPC（initialize/new/prompt 流式事件/cancel 取消真实 task/异常兜底/落库断言）
- spawn 真子进程：stdout 纯净（每行合法 JSON-RPC）+ initialize roundtrip
- ACPConsentProvider：outcome 映射 / 高危不给 allow_always / 请求异常按拒绝

```bash
.venv/bin/pytest tests/test_acp_server.py -q
```
