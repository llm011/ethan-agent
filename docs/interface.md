# Interface 层设计文档

## 概述

Ethan 提供三种交互方式，适应不同场景：

| 模式 | 入口 | 适用场景 |
|------|------|---------|
| CLI | `ethan` | 日常对话，快速启动 |
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
（界面结构示意，详见下图）
```

### 状态栏信息

| 字段 | 含义 |
|------|------|
| ⚡ model | 当前使用的模型 |
| ~/path | 工作目录（~ 替换 home，超长截断） |
| ↑N ↓M | 输入/输出 token 累计 |
| ⚡N | 缓存命中 token（如有） |

### 斜杠命令

在 CLI 内输入以 `/` 开头的命令：

| 命令 | 功能 |
|------|------|
| `/sessions` | 列出最近会话 |
| `/resume ID` | 恢复指定会话（支持短 ID 尾部匹配） |
| `/new` | 新建会话 |
| `/model [ID]` | 查看或切换模型 |
| `/help` | 显示帮助 |

### Session 集成

每次 CLI 启动自动创建 Session，消息实时写入 SQLite。
退出后可用 `ethan -r last` 恢复。

### 记忆集成

CLI 内部维护 `WorkingMemory` 实例：
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
  "model": "claude-sonnet-4-6",  // 可选
  "stream": false,               // true 则 SSE
  "session_id": "s_xxx",        // 可选，关联已有会话
  "channel": "web"              // 可选，默认 "web"
}
```

### /chat 响应（非流式）

```json
{
  "content": "你好！有什么可以帮你？",
  "model": "claude-sonnet-4-6",
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
ethan                           → CLI (REPL) 对话
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
ethan knowledge list/add/search/delete
ethan update [--channel dev] [--to v0.2.0] [--check] [--no-restart]
```

---

## 飞书 (Lark) 接入（`ethan/interface/lark_events.py`）

### 概述

允许用户通过飞书机器人与 Ethan 对话。采用 **WebSocket 长连接**方式：`ethan serve` 启动时自动调用 `lark-cli event consume im.message.receive_v1`，无需公网 IP，无需配置 Webhook URL。

### 配置方式

在 `~/.ethan/config.yaml` 中添加：

```yaml
lark:
  app_id: "cli_xxxxxxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

`ethan serve` 启动时自动建立长连接，无需额外配置 Webhook URL。

### 事件处理流程

```
lark-cli event consume im.message.receive_v1（WebSocket 长连接）
   │
   ├─ 根据 chat_id 查找或创建 Session
   │
   ├─ 立即给原消息加 THINKING_FACE 表情 → 告知用户已收到
   │
   ├─ 调用 Agent.chat() 处理消息
   │
   └─ 发送单条完整回复（非流式，飞书 IM 协议限制）
```

收到消息后第一步加 `THINKING_FACE` 表情是关键的用户体验设计：飞书消息处理可能需要数秒，及时反馈避免用户以为机器人离线。

### 飞书 Session 与普通 Session 的区别

| 维度 | 普通 Session | 飞书 Session |
|------|-------------|-------------|
| `source` 标记 | — | `"lark"` |
| Session 标识 | 启动时生成 UUID | 由 `chat_id` 映射 |
| 识别方式 | — | Session title 前缀 `lark:<chat_id>:` |
| 可在 Web UI 查看 | 是 | 是（同一 SQLite 数据库） |

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

延迟导入重量级模块（`anthropic`、`openai` 只在实际发起对话时加载），加上 `uv` 的依赖缓存，`ethan` 命令冷启动到第一次响应已降至约 0.16s（相比优化前的 7.6s）。
