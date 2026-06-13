# Interface 层设计文档

## 概述

Ethan 提供三种交互方式，适应不同场景：

| 模式 | 入口 | 适用场景 |
|------|------|---------|
| REPL | `ethan` | 日常对话，快速启动 |
| 单轮 | `ethan -p "..."` | 脚本集成，一问一答 |
| HTTP API | `ethan serve` | Web UI 对接，远程调用 |
| Web UI | `http://localhost:3000` | 浏览器访问，多页面管理 |
| 飞书 Bot | `lark-cli event consume` | 手机/飞书消息接入，无需公网 IP |

---

## REPL 模式（`ethan/interface/repl.py`）

### 设计思路

参考 Hermes Agent 和 Claude Code 的 CLI 体验：
- **prompt_toolkit** 处理输入（正确支持中文宽字符编辑）
- **Rich** 渲染输出（Markdown、表格、spinner）
- **bottom_toolbar** 固定在终端底部显示状态

### 界面结构

```
╭──────────────────────────────────────╮
│ Ethan Agent v0.0.1                   │  Banner（启动时显示一次）
│ Type exit to quit · ...              │
╰──────────────────────────────────────╯

（对话内容，流式输出）

────────────────────────────────────────  分隔线
› 用户输入区                              prompt_toolkit 输入
 ⚡ model · ~/path · ↑67 ↓19           底部状态栏（固定）
```

### 状态栏信息

| 字段 | 含义 |
|------|------|
| ⚡ model | 当前使用的模型 |
| ~/path | 工作目录（~ 替换 home，超长截断） |
| ↑N ↓M | 输入/输出 token 累计 |
| ⚡N | 缓存命中 token（如有） |

### 斜杠命令

在 REPL 内输入以 `/` 开头的命令：

| 命令 | 功能 |
|------|------|
| `/sessions` | 列出最近会话 |
| `/resume ID` | 恢复指定会话（支持短 ID 尾部匹配） |
| `/new` | 新建会话 |
| `/model [ID]` | 查看或切换模型 |
| `/help` | 显示帮助 |

### Session 集成

每次 REPL 启动自动创建 Session，消息实时写入 SQLite。
退出后可用 `ethan -r last` 恢复。

### 记忆集成

REPL 内部维护 `WorkingMemory` 实例：
- 每轮对话后调用 `memory.add_turn()`
- 热区满后检查是否需要压缩
- 发送给 LLM 的 context 由 `memory.build_context()` 构建

---

## Web UI（`web/`）

### 技术栈

- **Next.js 16**，App Router，React 19
- 使用 `(protected)` 路由组做统一鉴权，所有页面共享同一 layout shell

### 路由结构

| 路径 | 功能 |
|------|------|
| `/chat` | 新建对话（默认落地页） |
| `/chat/[id]` | 指定会话的对话界面，支持流式输出和工具调用可视化；消息气泡显示 TTFT 耗时 |
| `/memory` | 查看/编辑持久记忆，三个 Tab：Facts / Episodes / Procedures；支持编辑、删除，内容 Markdown 渲染 |
| `/knowledge` | 知识库管理（查询、上传、删除文档） |
| `/schedule` | 定时任务列表，支持暂停/恢复/删除 |
| `/skills` | Skill 列表及内容预览 |
| `/sessions` | 历史会话列表，支持按标题搜索 |
| `/settings` | 配置项：代理、max_tokens、max_tool_iterations、fast-path 关键词、心跳配置、System Prompt 预览 |
| `/channels` | 渠道管理：查看/编辑已配置的通知渠道 |

### 与后端通信

- 所有数据请求走 `ethan serve` 暴露的 FastAPI（默认 `http://localhost:8900`）
- 流式回复使用 SSE（`/chat` 端点 `stream: true`）
- 工具调用过程通过 SSE 事件分块推送，前端实时渲染调用详情

---

## HTTP API（`ethan/interface/api.py`）

### 设计思路

- FastAPI + uvicorn，异步高性能
- 支持 SSE（Server-Sent Events）流式输出
- 无状态设计 — 每个请求独立创建 Agent（后续可加 session 支持）

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查，返回版本号 |
| GET | `/models` | 列出所有已配置模型 |
| POST | `/chat` | 对话（支持 stream），使用 HOT_SIZE=20 滑动窗口截断历史 |
| POST | `/knowledge/search` | 语义检索知识库，返回最相关的条目 |
| GET | `/channels` | 列出所有已配置渠道 |
| PATCH | `/channels` | 更新渠道配置 |
| GET | `/system-prompt-preview` | 预览当前实际使用的完整 system prompt（含 skill 注入结果） |

### /chat 请求格式

```json
{
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "model": "gemini-3.1-flash-lite-preview",  // 可选
  "stream": false                             // true 则 SSE
}
```

### /chat 响应（非流式）

```json
{
  "content": "你好！有什么可以帮你？",
  "model": "gemini-3.1-flash-lite-preview",
  "usage": {"input": 67, "output": 12, "cache": 0}
}
```

### /chat 响应（SSE 流式）

```
data: {"content": "你"}
data: {"content": "好"}
data: {"content": "！"}
data: {"done": true, "model": "...", "usage": {...}}
```

### 启动方式

```bash
ethan serve                    # 默认 0.0.0.0:8900
ethan serve --port 9000        # 自定义端口
```

---

## CLI 命令结构（`ethan/interface/cli.py`）

### 设计决策

- 用 **typer** 做命令路由，支持子命令 + 选项 + 自动帮助
- 重量级模块（anthropic、openai）**延迟导入**，只在对话时加载
- `bin/ethan` 脚本覆盖 `sys.argv[0]`，让 Usage 显示 `ethan` 而非 `python -m ...`
- 子命令无参数时自动输出帮助

### 命令树

```
ethan                           → REPL 对话
ethan -p "..."                  → 单轮对话
ethan -m MODEL                  → 指定模型
ethan -r last                   → 恢复上次会话
ethan --tui                     → 全屏 TUI 模式
ethan serve                     → 启动 HTTP API
ethan model list/add/remove/default
ethan provider list/set
ethan session list/show/delete
ethan skill list/show/create
ethan schedule list/remove/pause/resume
```

---

## 飞书 (Lark) 接入（`ethan/interface/lark.py`）

### 概述

允许用户通过飞书机器人与 Ethan 对话。采用 **WebSocket 长连接**方式，无需公网 IP 或手动配置 Webhook 回调地址，由 `lark-cli` 在本地建立持久连接并消费事件。

### 接入方式：WebSocket 长连接（lark-cli）

与传统 HTTP Webhook 不同，本方案基于 `lark-cli event consume`，由客户端主动与飞书服务器建立 WebSocket 长连接。优点：

- **无需公网 IP**，本地开发环境直接可用
- **无需 HTTPS 证书**，无需反向代理
- 飞书开放平台不需要填写回调 URL

运行方式：

```bash
lark-cli event consume
```

该命令会持续监听 `im.message.receive_v1` 事件，并将消息分发给本地的 Ethan Agent 处理。

### 配置方式

在 `~/.ethan/config.yaml` 中添加：

```yaml
lark:
  app_id: "cli_xxxxxxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

`app_id` 和 `app_secret` 从飞书开放平台 → 应用凭证中获取。

### 初始化流程

```bash
lark-cli config init    # 写入 app_id / app_secret
lark-cli auth login     # 获取访问令牌，验证凭证有效性
lark-cli event consume  # 启动 WebSocket 长连接，开始监听消息
```

### 事件处理流程

```
收到 im.message.receive_v1 事件
   │
   ├─ 立即给原消息加 THINKING_FACE 表情 → 告知用户已收到
   │
   ├─ 根据 chat_id 查找或创建 Session
   │
   ├─ 调用 Agent.chat() 处理消息
   │
   └─ 发送单条完整回复（非流式，飞书 IM 协议限制）
```

收到消息后第一步加 `THINKING_FACE` 表情是关键的用户体验设计：飞书消息处理可能需要数秒，及时反馈避免用户以为机器人离线。Agent 处理完成后发送一条完整的文本回复，不做增量推送。

### 新用户引导

首次私聊机器人时，Session 为空，Agent 会发送引导消息介绍自己的能力，帮助用户了解可以提问的内容。

### 飞书 Session 与普通 Session 的区别

| 维度 | 普通 Session | 飞书 Session |
|------|-------------|-------------|
| `source` 标记 | — | `"lark"` |
| Session 标识 | 启动时生成 UUID | 由 `chat_id` 映射 |
| chat_id 映射持久化 | 不适用 | `~/.ethan/memory/lark_sessions.json` |
| Session 标题格式 | 用户自定义或自动摘要 | `lark:<chat_id>:<short_id>` |
| 可在 Web UI 查看 | 是 | 是（同一 SQLite 数据库） |
| 消息来源 | REPL / Web UI | 飞书客户端 |

`chat_id` → `session_id` 的映射写入 `~/.ethan/memory/lark_sessions.json`，确保同一个飞书会话在 Ethan 重启后仍能延续上下文。

### 应用权限要求

在飞书开放平台 → 权限管理中开通：
- `im:message`（读取消息内容）
- `im:message:send_as_bot`（发送消息）
- `im:message.reaction:write`（添加表情反应）

### 当前限制

- 仅处理 `text` 类型消息，图片/文件等消息类型静默忽略。
- 回复为单条完整消息，不支持流式增量输出。

---

## 启动速度优化

当前 `ethan -h` 约 0.3s（Python 导入），进入 REPL 约 1.5s（uv + 解释器冷启动）。

已做的优化：
- 延迟导入重量级模块（anthropic、openai 只在对话时加载）
- `_build_agent()` 在 callback 内部调用，不影响子命令

未来可选方案：
- Daemon + client 架构（类似 Claude Code）：进程常驻，客户端只做 IPC
- `uv tool install` 预编译，跳过每次的依赖解析
