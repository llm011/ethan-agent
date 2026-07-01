# ACP 集成设计文档

## 概述

ACP（Agent Communication Protocol）是 Ethan 委托复杂编码任务给专业 Coding Agent 的机制。

**设计原则**：Ethan 是通用个人 AI Agent，不专注于代码。遇到复杂编码任务时，自动检测并委托给本地 Coding Agent（Claude Code / OpenCode / Codex），把结果整合回对话，并支持多轮续接与过程可视化。

---

## 架构

![ACP Coding Agent 架构](./images/acp-arch.jpg)
<!-- diagram-source
```
用户输入 "帮我实现 JWT 认证的 FastAPI 应用"
    │
    ▼
delegate_coding tool (agent 自动调用)
    │
    ▼
ethan/acp/__init__.py
    ├── is_complex_coding_task() → 复杂度判断
    └── delegate() → 调用本地 Coding Agent（三套均为 JSON 事件流 + 多轮续接）
            ├── Claude Code CLI: claude -p --output-format stream-json --resume <session_id>
            ├── OpenCode CLI:    opencode run --format json -s <session_id> "..."
            └── Codex CLI:       codex exec [resume <thread_id>] --json "..."
    │
    ├── MirrorSession.start() → 落一条 Ethan 镜像会话 + 注册 RunManager run
    ▼
Coding Agent 执行，输出代码/修改文件
    │  (JSON 事件流：每个工具步骤 / agent 文本块)
    ├── on_event 回调：step/text 实时 emit 进镜像会话的 ChatRun
    │                  → web 经 /chat/{session_id}/stream 实时 attach
    ▼
解析为 sub_steps + 最终结果，回传给 Ethan
    │
    ├── MirrorSession.finish() → assistant 消息落库 + 收尾实时流
    ▼
ToolEvent 携带 sub_steps → 主对话 Web UI 时间轴折叠展示
```
-->

---

## 复杂度判断（`is_complex_coding_task`）

启发式判断，两步过滤：

1. **简单问题优先排除**：
   - "什么是"、"解释"、"how does" → 直接回答，不委托

2. **复杂度信号 + 代码关键词**：
   - implement / refactor / create / 实现 / 重构 + code / python / api 等 → 委托

| 输入 | 判断 |
|------|------|
| "什么是 asyncio" | 简单 → 自己回答 |
| "implement REST API with JWT" | 复杂 → 委托 |
| "帮我重构这个文件里的代码" | 复杂 → 委托 |
| "explain how decorators work" | 简单 → 自己回答 |

---

## 支持的 Coding Agent

| Agent | 命令 | 多轮 | 子步骤解析 | 安装 |
|-------|------|------|-----------|------|
| Claude Code | `claude` | ✅ `--resume <session_id>` | ✅ stream-json | https://claude.ai/code |
| OpenCode | `opencode` | ✅ `-s <session_id>` | ✅ `--format json` | https://opencode.ai |
| Codex | `codex` | ✅ `exec resume <thread_id>` | ✅ `--json` | — |

优先级：Claude Code > OpenCode > Codex（按系统 PATH 检测）。可通过 `prefer` 参数指定（`claude` / `opencode` / `codex` / `auto`）。

三套现在都走 JSON 事件流：首轮从事件里取出会话 id（claude 的 `session_id` / opencode 的 `sessionID` / codex 的 `thread_id`），续轮带上该 id 续接。

### Codex provider 注入

Codex 默认读 `~/.codex/config.toml` 的 provider，但该 provider 可能失效（ChatGPT 登录态过期、内网代理不通等）。`_codex_provider_overrides()` 会复用 Ethan 自己的 `cliproxy` provider（OpenAI 兼容，`wire_api=responses`），通过 `-c model_provider=...` 覆盖注入，模型默认 `gpt-5.5`（可用环境变量 `ETHAN_CODEX_MODEL` 覆盖）。未配置 cliproxy 时退回 codex 自身 config，不破坏既有行为。

---

## 多轮会话

三套 Coding Agent 都支持续接。Ethan 按「**Coding Agent × 工作目录**」持久化会话 id：

- 持久化文件：`~/.ethan/<user>/acp_sessions.json`，key 为 `"{agent}::{工作目录绝对路径}"`
- **按 agent 隔离**：codex/claude/opencode 的 id 格式不同，分键存储避免在同一目录互相覆盖导致 resume 失败
- 连续的 `delegate_coding` 调用若指向同一 `working_dir`，自动续接同一会话
- `reset_session=true` 可清除该 (agent, 目录) 的会话记忆，从新会话开始

```python
# 第一轮
delegate_coding(task="实现 JWT 认证", working_dir="/proj")
# → 创建 session A，持久化为 "claude::/proj"

# 第二轮（同目录，自动续接 session A）
delegate_coding(task="再加一个刷新 token 的接口", working_dir="/proj")

# 切换到无关任务，开新会话
delegate_coding(task="重构 utils", working_dir="/proj", reset_session=True)
```

### 超时与 thread 状态保护

Coding Agent 把「turn 是否进行中」记在自己的 session 文件里。若直接 `kill()` 超时进程，会让 thread 停在 'turn in progress'，导致之后手动 `codex resume` / `/resume` 被拒（`/resume is disabled while a task is in progress`）。

`_terminate_proc()` 改为**优雅终止**：先 SIGTERM 给 CLI 收尾机会，超过宽限期仍未退出再 SIGKILL。此外超时后会**清掉该 (agent, 目录) 持久化的会话 id**，下次委派从新会话开始，避免续接到坏 thread。

---

## 镜像会话（MirrorSession）

文件：`ethan/acp/mirror.py`

每次 `delegate()` 调用会落成一条真正的 Ethan 会话，`source` 用**真实的 coding agent 名**（`codex` / `claude` / `opencode`），让用户在 Ethan 侧也能看到「下发给 Coding Agent 的 query + Coding Agent 的回复 + 中间工具步骤」，而不只是主对话里一行 `delegate_coding` 工具结果。web 侧边栏的渠道徽标据此显示是哪个工具（青色 Codex / 琥珀 Claude Code / 玫红 OpenCode）。

- **粒度**：同一 `(agent, cwd)` 的连续委派**累加到同一条** Ethan 会话（多轮对话）；`reset_session=True`（切换任务）时新建一条。映射存在 `acp_sessions.json` 的 `mirror::{agent}::{cwd}` 键。
  - user 消息 = 每一轮下发的 query（委派一开始就落库）
  - assistant 消息 = 每一轮 Coding Agent 的最终回复 + tool_steps（由 sub_steps 转来）
- **同库**：走 per-user 的 `SessionStore`（`user_sessions_db_path()`），与普通 web 会话同库，侧边栏天然能列出（按 `source` 区分）
- **model 字段**：存**真实可用的 chat 模型**（取 `defaults.model`），**不能**用 agent 名——否则用户在该会话里直接发消息时会被当成 chat 模型，导致 `unknown provider for model codex` 502。渠道归类由 `source` 表达，与 model 解耦。
- **best-effort**：写库/注册任何一步失败都吞掉异常，绝不影响主委派流程
- 可用 `delegate(mirror=False)` 关闭

### 实时推送

镜像会话在 `start()` 时同步注册一个 `RunManager` 的 `ChatRun`，使委派过程可被 web 实时 attach：

- Coding Agent 跑动过程中，每个工具步骤（step）和 agent 文本块（text）经 `on_event` 回调实时 emit 进 ChatRun 缓冲
- 前端用现成的 `GET /chat/{session_id}/stream` SSE 端点 attach，边跑边看；断线重连可回放完整缓冲
- `finish()` 时 emit `done` 并安排清理（宽限期内仍可重连回放）

事件映射到 chat SSE 词表：`text → {"content": ...}`，`step → 工具事件`（用 `id(step)` 作稳定 id 配对）。

### 在镜像会话里直接续接对话

用户**直接在某条镜像会话里发新消息**时，这条消息不走普通 chat 模型，而是被当作新 prompt **续接对应的 coding agent**（`resume=True`）：

- 反向映射 `mirrorinfo::{session_id} → {agent, cwd}` 在每次委派时写入 `acp_sessions.json`
- `POST /api/chat` 检测到 `session_id` 命中 `get_mirror_info()` 时，改走 `_run_delegate_generation`，调用 `delegate(prefer=agent, cwd=cwd, resume=True, mirror=False, on_event=...)`
- `mirror=False` 避免为同一 session 重复注册 ChatRun（双 writer）；过程的 step/text 经 `on_event` 实时推回这条会话
- 效果：这条会话名副其实是「能持续对话的 coding agent 会话」——发一句它就接着让 codex/claude/opencode 干，而不是切回 Ethan 默认模型

### 沉浸式工具模式（codex / claude_code / opencode）

除了「临时委派 + 镜像会话」，还有一条对偶路径：**沉浸式工具模式**。在 `ethan/core/modes.py` 里，这三个模式带 `delegate_agent`（`codex` / `claude` / `opencode`）字段：

- 用户在 web 把对话 **mode 切到 Codex / Claude Code / OpenCode** 后，**整条会话的每句话**都直接续接该 coding agent（同一工具 session 多轮），而不是走 Ethan 的 chat 模型。
- `POST /api/chat` 在 stream 分支最前面解析 `resolve_mode(req.mode).delegate_agent`：非空且有 `session_id` 时，走 `_run_delegate_generation`。
- **工作目录按会话隔离**：`~/.ethan/agent-sessions/<会话id>/`（`user_agent_session_dir`）。同一会话连续消息复用同一目录 → 复用同一工具 session；不同会话互不干扰。
- 三段路由优先级：(1) 沉浸式模式 → (2) 镜像会话续接（临时委派会话） → (3) 普通 chat。
- 两条路径的取舍：临时 `delegate_coding`（主对话里随手让工具干一件事，产出镜像会话）vs 沉浸式（明确切进某工具，持续对话）。

> cwd 不存在时（临时目录被删等）`_run_delegate_generation` 会给出「工作目录已不存在」的清晰提示，而不是抛 `[Errno 2] No such file or directory`；子进程在 emit 任何文本前就失败时，会把最终结果补推一次，避免 live 流空返回。

---

## 结构化输出（sub_steps）

三套 Coding Agent 的 JSON 事件流都解析为统一的结构化子步骤：

**Claude Code**（`--output-format stream-json`）：

| 事件类型 | 解析结果 |
|---------|---------|
| `assistant` + `tool_use` | 新增 sub_step（state=running） |
| `user` + `tool_result` | 关闭 sub_step（state=done/error，填 duration_ms + result_preview） |
| `system/init` | 提取 session_id |
| `result` | 最终文本结果 + success/error |

**Codex**（`--json`）：

| 事件类型 | 解析结果 |
|---------|---------|
| `thread.started` | 提取 thread_id 作 session_id |
| `item.completed` (command_execution) | shell 步骤 |
| `item.completed` (file_change/patch) | edit 步骤 |
| `item.completed` (agent_message) | 最终文本（取末条） |
| `item.completed` (error) | error 步骤（弃用/配置警告类自动过滤，不显示成 error） |
| `turn.failed` / `error` | 标记失败 |

**OpenCode**（`--format json`）：

| 事件类型 | 解析结果 |
|---------|---------|
| 含 `sessionID` 的事件 | 提取 sessionID |
| `text` part | 累积最终文本 |
| `tool` part | 工具步骤（按 state.status 判 done/error） |
| `error` | error 步骤 |

`delegate()` 返回的 `ACPResult.sub_steps` 经 `ToolResult` → `ToolEvent` 流到主对话 Web UI，在工具时间轴里折叠展示（见下）。

---

## DelegateCodingTool

文件：`ethan/tools/builtin/acp.py`

LLM 可以直接调用的 tool：

```python
delegate_coding(
    task="Implement a user authentication system with JWT tokens...",
    working_dir="/path/to/project",   # optional，默认当前目录
    reset_session=False,              # True 则不复用该目录的历史会话
)
```

- `cacheable=False`（有副作用，不可缓存）
- `fast_path=False`（只在 medium/full path 加载）
- timeout 默认 180 秒
- 输出超 12000 字符自动截断
- 返回 `[agent](session=xxxxxxxx) output` 格式，并携带 `sub_steps`

---

## Web UI 展示

`delegate_coding` 的工具调用在主对话 Web UI 时间轴里有专门处理（`web/components/tool-timeline.tsx`）：

- **子步骤折叠**：点击「N/总 步」展开 Coding Agent 内部的每次工具调用（如 Bash / Edit / Write），显示工具名、参数摘要、耗时、结果预览
- **最终结果高亮**：`delegate_coding` 的 `result_preview` 用绿色高亮卡片展示，区别于普通工具的灰字预览
- 历史会话重载时，`sub_steps` 从 `tool_steps` 字段反序列化还原

除主对话时间轴外，**镜像会话**（见上）让委派过程本身成为一条可在侧边栏打开、可实时 attach 的独立 Ethan 会话。

REPL 模式下也会打印子步骤计数摘要：`↳ N 步工具调用（M 成功）`。

---

## 未来改进

- **更精准的复杂度判断**：通过 LLM 预判是否需要委托（替代启发式）
- **双向通信**：让 Coding Agent 在执行中回调 Ethan 澄清需求
- **上下文传递**：把 Ethan 的记忆（用户偏好、项目信息）传给 Coding Agent
- **结果审查**：Ethan 自动 review Coding Agent 的输出，提出改进建议
- **镜像会话前端区分**：侧边栏对 `source="delegate"` 的会话做分组/标记，与普通对话区分
