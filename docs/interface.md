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
| `/new` | 新建会话（沿用当前对话模式） |
| `/model [ID]` | 查看或切换模型 |
| `/mode [名称]` | 查看或切换对话模式（如 `/mode 法律`；不带参数或 `/mode default` 切回默认）。名称无法识别时保持当前模式不变 |
| `/help` | 显示帮助 |

> `/mode` 在 CLI（REPL）和消息渠道（飞书等）通用。模式持久化在 `sessions.mode`，`/resume` 恢复会话或切会话时自动同步到 `Agent._mode`，并经 `resolve_mode().key` 参与 Skill 的 `modes` 过滤。垂类技能（如「法律专家模式」的 `legal-assistant`）只在对应模式生效。模式注册表见 [modes.py](../ethan/core/modes.py)。

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
| `/schedule` | 定时任务列表，支持暂停/恢复/删除/重命名 |
| `/skills` | Skill 列表及内容预览 |
| `/sessions` | 历史会话列表，支持按标题搜索 |
| `/settings` | 配置项：代理、max_tokens、max_tool_iterations、fast-path 关键词、心跳配置、System Prompt 预览 |
| `/channels` | 渠道管理：查看/编辑已配置的通知渠道 |

### 与后端通信

- 所有数据请求走 `ethan serve` 暴露的 FastAPI（默认 `http://localhost:8900`）
- 流式回复使用 SSE（`/chat` 端点 `stream: true`）
- 工具调用过程通过 SSE 事件分块推送，前端实时渲染调用详情
- 生成与连接解耦：一次生成是一个后台 `ChatRun`（`ethan/core/run_manager.py`），SSE 响应只是订阅者。刷新页面断开连接不会中断生成——producer 照常跑完并入库。前端加载会话时若 `active_run` 为真，调 `GET /chat/{id}/stream` 重连，回放缓冲 + 继续实时

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
| GET | `/chat/{session_id}/stream` | 重连仍在进行的生成：回放缓冲 + 继续实时推送；无活跃生成返回 204 |
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

SSE chunk 类型汇总：

| 字段 | 说明 |
|------|------|
| `content` | 文本片段（流式输出） |
| `done` | 生成结束，附带 `model` / `usage` |
| `error` | 生成出错，附带错误描述字符串 |
| `heartbeat` | 任务卡住超 3 分钟无新事件时由 watchdog 发出，附带 `elapsed`（已用秒数），前端渲染等待提示 |
| `tool_*` | 工具调用进度（见下方工具调用事件） |

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
ethan serve                     → 启动 HTTP API（前台运行）
ethan serve stop                → 停止后台运行的 serve 进程
ethan serve restart             → 重启后台 serve 进程
ethan model list/add/remove/default
ethan provider list/set
ethan session list/show/delete
ethan skill list/show/add/create
ethan router pull/status        → 语义路由模型：下载 / 查看状态（需 [router] 可选依赖）
ethan schedule list/remove/pause/resume
ethan knowledge list/add/search/delete
ethan update [--channel dev] [--to v0.2.0] [--check] [--no-restart]
ethan code "query"              → ACP 委派 Coding Agent（详见 acp.md）
```

---

## 飞书 (Lark) 接入（`ethan/interface/lark_events.py`）

### 概述

允许用户通过飞书机器人与 Ethan 对话。采用 **WebSocket 长连接**方式：`ethan serve` 启动时为每个 EventKey 各起一个 `lark-cli event consume <EventKey>` 子进程，无需公网 IP，无需配置 Webhook URL。

### 模块划分

飞书逻辑按职责拆分到 `ethan/interface/` 下的几个平级模块（`lark.py` 已被占用，故用 `lark_*` 前缀而非包目录）：

| 模块 | 职责 |
|------|------|
| `lark_render.py` | 纯渲染：把文本/markdown/工具进度转成 post 富文本或 interactive 卡片的 content JSON。无 IO。 |
| `lark_send.py` | 收发 IO：client 构建、发送/编辑/删除/回复消息、通知/图片、消息详情拉取、引用解析。 |
| `lark_stream.py` | 消息处理：会话状态（去重 / `chat_id`→`session_id` 映射 / 进行中任务登记）、`/命令` 路由、`_handle_message` 的 Agent 流式回复主循环。 |
| `lark_events.py` | 入口：`lark-cli event consume` 事件循环 + `start/stop_lark_listener` 生命周期，并 re-export `send_lark_notification` / `send_lark_image` 等供外部（定时任务、browser 模块）使用。 |
| `lark.py` | **遗留**：旧的 webhook 模式（`/lark/webhook` 端点），当前未挂载、未使用。保留是因为 `background_task` / `schedule` 仍 import 它的 `_get_lark_client` / `_send_lark_reply`（纯文本回复兜底）。注意：它在模块顶层 `import lark_oapi`，故 **不能** 被 `api.py` 在模块级 `include_router`——否则会触发 lark_oapi 的 ~40s 全量加载，拖垮 `ethan serve` 冷启动。 |

依赖方向单向无环：`lark_events → lark_stream → lark_send → lark_render`。`api.py` 仍从 `lark_events` 导入 `start/stop_lark_listener`，外部导入路径不变。

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
lark-cli event consume <EventKey>（每个 EventKey 一个子进程，WebSocket 长连接）
   │
   ├─ 按 message_id 幂等去重 → 命中重复事件直接丢弃
   │
   ├─ /命令 路由（/new /stop /help 等，免加 THINKING 表情，即时响应）
   │
   ├─ 自然语言中止快速路径：文本精确匹配「停 / 停下 / 不用了 / 取消 / stop / 中止 / 停止」
   │    且当前 chat 有进行中的 Agent 任务时，直接 cancel 并回复「🛑 已停止当前回复。」
   │    无进行中任务则不拦截，继续走 Agent 流程（避免误伤空 chat 的一句"停"）
   │
   ├─ 根据 chat_id 查找或创建 Session
   │
   ├─ 立即给原消息加 THINKING_FACE 表情 → 告知用户已收到
   │
   ├─ 调用 Agent.stream_chat() 流式处理消息
   │     · 思考阶段（ThinkingEvent）只显示「🤔 thinking...」占位，不打印思考原文
   │     · 工具调用过程实时更新进度卡片
   │     · ui_card 工具产出的自定义卡片（lark_card）作为增量额外补发一条 interactive 卡片
   │
   └─ 流式追加/编辑回复卡片，结束时附上 token 统计
```

收到消息后第一步加 `THINKING_FACE` 表情是关键的用户体验设计：飞书消息处理可能需要数秒，及时反馈避免用户以为机器人离线。

> 自然语言中止是 `/stop` 命令的"温柔入口"：用户不必记命令，发个"停"就能中止当前生成。关键词用精确匹配（非包含）防误伤——"停下来一下"或"取消我的会议"不会被拦截。

### 输出形态（两条消息 + 增量卡片）

- **工具进度**：post 富文本气泡，工具开始/结束时流式 `message.update`。
- **最终回答**：interactive 卡片，流式 `message.patch`；首段缓冲到阈值再发，避免孤立短卡片，出现新工具调用时撤回已发的 narration 卡片。
- **自定义卡片（增量）**：`ui_card` 工具（`channel="lark"`）走 `lark_card_templates` 生成飞书卡片 JSON，经 `ToolEvent.ui` 透传，工具完成时作为独立 interactive 卡片补发。这是「可有可无、有则更好看」的增量能力——基础的工具进度/答案输出不依赖它。Web 端同一套结构化 `card` 数据则渲染成 A2UI（见 [tools.md](./tools.md#ui_carda2ui-结构化卡片)）。

### 卡片 markdown 表格渲染

飞书卡片 markdown element 内嵌的 GFM pipe-table 触发上限：超过 3 张表格会报 `230099 / 11310`。`lark_render._render_card_content` 按表格数量分两路：

- **≤3 张表格**：手拼 `{"tag":"markdown","content":...}` 单元素，前 3 张表格由飞书原生 markdown 解析渲染（样式与正文一致）。0 表格也走这条路——不付 `lark_oapi.channel.card` 的 lazy import 成本（~10s 首次）。
- **>3 张表格**：走 `_render_card_content_rich`，lazy import `lark_oapi.channel.card.new_card`（CardBuilder fluent API）。前 3 张表格仍留在 markdown 元素里，超出部分用 `c.table(headers, rows, page_size=10)` 原生 table 元素（`page_size` 被 CardBuilder clamp 到飞书 Card 2.0 允许的 1-10 范围）。表格之间的文本继续走 `c.markdown()`，正文样式优化（标题降级 / 硬换行）与手拼路径一致。
- **兜底**：CardBuilder import 失败或 build 异常时回退到手拼 markdown + `_sanitize_text_for_card`（超出表格降级成 ` ``` ` 代码块），保证渲染不崩。

> CardBuilder 路径首次调用要付 ~10s 的 `lark_oapi.channel.card` 子树加载（之后 Python 模块缓存命中，~0ms）。冷启动后第一条 >3 表格的消息会感受到这个延迟——目前没在 lifespan 里预热，因为 (a) `_lark_ready()` 探测刻意不触发 lark_oapi 完整加载以保 serve 启动快；(b) >3 张表格的回答不常见。

### 事件去重（幂等）

飞书事件投递是 **at-least-once**：当 bot 未在超时窗口内 ack（长任务耗时、断线重连重放积压事件）时，飞书会重投同一条事件。若不去重，同一条消息会被处理多次，表现为重复回复、以及两份互不相同的 token 统计（每次处理都是独立的 Agent 运行）。

入口处用 `message_id` 做幂等去重（内存 LRU，容量 2000）：命中已处理过的 `message_id` 直接丢弃并记日志。`message_id` 对每条用户消息唯一、重投时保持不变，正好充当幂等键。


### 飞书 Session 与普通 Session 的区别

| 维度 | 普通 Session | 飞书 Session |
|------|-------------|-------------|
| `source` 标记 | — | `"lark"` |
| Session 标识 | 启动时生成 UUID | 由 `chat_id` 映射 |
| 识别方式 | — | Session title 前缀 `lark:<chat_id>:` |
| 可在 Web UI 查看 | 是 | 是（同一 SQLite 数据库） |

> 此外还有**委派镜像会话**（`source="delegate"`）：每次 Ethan 委派给 Coding Agent（codex/claude/opencode）会落一条独立 session，记录下发的 query + Coding Agent 回复 + 工具步骤，并注册 RunManager run 支持实时 attach。详见 [acp.md](./acp.md)。

### 应用权限要求

在飞书开放平台 → 权限管理中开通：
- `im:message`（读取消息内容）
- `im:message:send_as_bot`（发送消息）
- `im:message.reaction:write`（添加表情反应）
- `im:message.group_msg:get_as_user`（读取群聊全部消息，用于背景上下文）

> **权限说明：** Bot 身份只能读取 @ 它的消息，无法看到群内其他消息。为了给 Agent 提供群聊背景上下文（让它在回答时知道群里刚才发生了什么），需要用户身份的 `im:message.group_msg:get_as_user` 权限。配置 lark-cli 时按引导授权即可。

### 鉴权失败自动引导

lark-cli 调用用户身份接口（如 `_fetch_recent_chat_messages` 走 `--as user`）时，若 user token 缺失或过期，会触发授权引导卡片，避免群里「静默无回复」的尴尬体验。

**触发条件**（`_is_lark_auth_error` 判定，任一命中即触发）：
- stderr 含 `need_user_authorization` / `No user logged in`（用户未登录的常见 stderr）
- stdout JSON 的 `error.type == "auth_error"`
- stdout JSON 的 `error.code` 为 `99991663`（user auth missing）/ `99991661`（token invalid）
- stdout JSON 的 `error.message` 含 `User token has expired` / `Token does not exist`

**不触发场景**：网络错误、参数错误（`validation_error`）、`not found`、JSON parse 失败 —— 这些不是鉴权问题，发引导卡片反而误导。

**节流**：模块级 `_auth_card_sent` dict 按 `chat_id` 记录上次发送时间戳，同一 chat 5 分钟内只发一次。避免群里多条用户身份调用连环失败时刷屏。

**卡片内容**：红色 header「需要飞书用户授权」+ markdown body 指引用户在终端执行 `lark-cli auth login --domain im` 完成浏览器授权。复用现有 `_send_interactive_card` 通道发送，结构同 `lark_card_templates` 的 schema 2.0。

**覆盖调用点**（`lark_send.py`）：
- `_fetch_recent_chat_messages`：用户身份调用，最易触发 → 发卡片
- `_send_reply`：bot 身份，理论上不会 user 鉴权失败，但保留检测 → 发卡片
- `_fetch_message_detail`：bot 身份 mget，保留检测 → 仅日志不 发卡片（避免 bot 鉴权失败时刷屏）

> 用户身份的鉴权失败是飞书渠道最常见的「群里突然不回我消息」原因——bot token 一般配在 `config.yaml` 里不会过期，user token 是 Device Flow 授权的，过期/重装机器都会丢。引导卡片把「为什么不回」可视化，用户照着跑一次 `lark-cli auth login` 即可恢复。

### 多事件订阅与卡片回调

`lark_events._EVENT_KEYS` 列出要订阅的 EventKey，`start_lark_listener` 为每个 key 各起一个 `_event_loop` task（独立子进程、独立断线重连、互不影响）。每个子进程把 NDJSON 行解析成 event dict 后交给 `lark_stream._dispatch` 路由：

| EventKey | handler | 用途 |
|----------|---------|------|
| `im.message.receive_v1` | `_handle_message` | 收消息 → 完整 Agent 流式回复（fire-and-forget） |
| `im.message.message_read_v1` | `_handle_message_read` | 用户已读 P2P 消息（仅日志，留「已读回执」扩展点） |
| `im.message.reaction.created_v1` | `_handle_reaction` | 消息被加 reaction（仅日志，留「点赞触发动作」扩展点） |
| `card.action.trigger` | `_handle_card_action` | 交互卡片按钮/表单回调（见下） |

新事件类型只需在 `_EVENT_KEYS` 加一行 + 在 `_dispatch` 加一个 elif 分支，handler 实现保持轻量（先记日志留扩展点），重逻辑仍走 `_handle_message` 那条线。

#### card.action.trigger（卡片按钮回调）

需 lark-cli ≥ 1.0.58（PR #1528，本地已升到 1.0.65）且在飞书开发者后台开启该 Console Event。lark-cli 输出扁平结构，`_handle_card_action` 从顶层取 `action_tag`（button/select/input/checker）、`action_value`（JSON 字符串）、`action_name`、`form_value`、`card_content`（原卡片 userDSL）、`token`（30 分钟有效，最多 2 次卡片更新）、`chat_id`/`message_id`/`open_id`。

当前实现：记日志 + 兜底回执（`action_value.cmd == "test"` 时回一张绿色确认卡，验证链路用）。后续可据 `action_value` 路由到具体工作流，用 `lark-cli api POST /open-apis/interactive/v1/card/update` 配合 `token` 更新原卡片（按钮审批/分步表单等场景）。

调试：飞书里发 `/test-card` 命令，bot 回一张带「🔘 点我测试」按钮的蓝色卡片；点按钮后若后台已开启 Console Event，会收到绿色确认卡（链路打通）。若点按钮无反应，先去飞书开发者后台 → 事件订阅 → 开启 `card.action.trigger`。

### 当前限制

- 仅处理 `text` 类型消息，图片/文件等消息类型静默忽略。

---

## 启动速度优化

延迟导入重量级模块（`anthropic`、`openai` 只在实际发起对话时加载），加上 `uv` 的依赖缓存，`ethan` 命令冷启动到第一次响应已降至约 0.16s（相比优化前的 7.6s）。

`ethan serve` 同样避免在模块加载阶段触发重型 import。飞书 SDK `lark_oapi` 因加载大量业务域 model 包（acs/corehr/hire/calendar/…）单次 import 约 40s，若在 `api.py` 模块级挂 `lark.py` 的 webhook 路由会直接卡死冷启动。对策：

- `api.py` 不 `include_router` 任何 lark 路由；飞书接入走 `lark_events.py` 的 WebSocket 子进程模式，在 lifespan 里启动。
- `lark_send.py` / `lark_stream.py` 里所有 `lark_oapi` 都是**函数内 lazy import**（首次用到才加载），模块级 import 不触发。
- `api.py` 用 `importlib.util.find_spec("lark_oapi")` 轻量探测是否安装，不触发完整 import。

这样 `from ethan.interface.api import app` 约 1.6s，`ethan serve restart` 端口探测在 15s 内通过，不再误报「端口未就绪」。
