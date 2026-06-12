# Interface 层设计文档

## 概述

Ethan 提供三种交互方式，适应不同场景：

| 模式 | 入口 | 适用场景 |
|------|------|---------|
| REPL | `ethan` | 日常对话，快速启动 |
| 单轮 | `ethan -p "..."` | 脚本集成，一问一答 |
| HTTP API | `ethan serve` | Web UI 对接，远程调用 |

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
| POST | `/chat` | 对话（支持 stream） |

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

## Feishu (Lark) Bot（`ethan/interface/lark.py`）

### 概述

允许用户通过飞书机器人与 Ethan 对话。每条消息经 FastAPI 路由到 Agent，回复写回同一飞书会话。

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/lark/webhook` | 飞书事件回调入口（URL 验证 + 消息接收） |

### 配置步骤

1. 在[飞书开放平台](https://open.feishu.cn)创建企业自建应用，获取 `App ID` 和 `App Secret`。

2. 在 `~/.ethan/config.yaml` 中添加：

```yaml
lark:
  app_id: "cli_xxxxxxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  verification_token: ""   # 事件订阅验证 Token（可选）
  encrypt_key: ""          # 加密密钥（可选）
```

也可通过环境变量方式后续扩展；目前直接写入 config 文件即可。

3. 在飞书开放平台 → **事件订阅** → 请求网址 URL 填写：

```
https://your-domain:8900/lark/webhook
```

4. 订阅事件：`im.message.receive_v1`（接收消息）。

5. 在应用权限管理中开通：
   - `im:message:send_as_bot`（发送消息）
   - `im:message`（读取消息内容）

6. 发布应用并将机器人添加到目标群组或开启单聊权限。

### 会话持久化

每个飞书 `open_chat_id` 对应一个独立 Session，标题格式为 `lark:<chat_id>:<short_id>`，存储在同一 SQLite 数据库中，可在 Web UI 中查看历史。

### 当前限制

- 仅处理 `text` 类型消息，图片/文件等消息类型静默忽略。
- 暂不验证 `verification_token` / `encrypt_key`（可在 `lark.py` 中按需启用）。

---

## 启动速度优化

当前 `ethan -h` 约 0.3s（Python 导入），进入 REPL 约 1.5s（uv + 解释器冷启动）。

已做的优化：
- 延迟导入重量级模块（anthropic、openai 只在对话时加载）
- `_build_agent()` 在 callback 内部调用，不影响子命令

未来可选方案：
- Daemon + client 架构（类似 Claude Code）：进程常驻，客户端只做 IPC
- `uv tool install` 预编译，跳过每次的依赖解析
