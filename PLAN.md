# Ethan Agent 开发计划

## 背景与目标

从零开始构建一个个人 AI Agent，运行在 Mac mini 上，长期常驻服务。  
核心诉求：**记忆系统 + 定时任务 + Skill 支持 + Agent Loop + 多模型**。  
参考 OpenClaw、Hermes Agent、nanobot 的设计，取各家精华，用 Python 全异步实现。

---

## 整体架构（实际目录）

```
ethan/
├── core/
│   ├── agent.py               # 主 Agent Loop（ReAct 模式）
│   └── config.py              # YAML 配置（~/.ethan/config.yaml）
├── providers/
│   ├── base.py                # 统一接口（Message、ToolCall、BaseProvider）
│   ├── anthropic.py           # Claude 原生 SDK
│   ├── openai_compat.py       # OpenAI 兼容协议（GPT/Ollama/OpenRouter）
│   └── manager.py             # 按 model id 路由到对应 Provider
├── memory/                    # 阶段二
├── skills/                    # 阶段三
├── tools/
│   ├── base.py                # BaseTool 抽象
│   ├── registry.py            # ToolRegistry + 并发 ToolExecutor
│   └── builtin/
│       ├── shell.py           # Shell 工具（✅ 已实现）
│       ├── file.py            # 文件工具（阶段五）
│       └── web.py             # Web 工具（阶段五）
├── scheduler/                 # 阶段四
└── interface/
    ├── cli.py                 # 主入口（typer）
    ├── tui.py                 # Textual 全屏 TUI
    └── commands/
        ├── model.py           # ethan model list/add/remove/default
        └── provider.py        # ethan provider list/set
```

---

## 阶段一：Provider 层 + 基础 Agent Loop ✅

### 核心实现
- [x] `ethan/providers/base.py` — 统一接口（Message、ToolCall、BaseProvider）
- [x] `ethan/providers/anthropic.py` — Claude 原生协议，支持流式 + tool_use
- [x] `ethan/providers/openai_compat.py` — OpenAI 兼容协议，支持流式 + tool_calling
- [x] `ethan/providers/manager.py` — 按 model id 从配置路由到对应 Provider
- [x] `ethan/core/config.py` — YAML 配置（~/.ethan/config.yaml），env 可覆盖
- [x] `ethan/core/agent.py` — ReAct Loop（非流式 + 流式）
- [x] `ethan/tools/base.py` — BaseTool 抽象
- [x] `ethan/tools/registry.py` — ToolRegistry + 并发 ToolExecutor
- [x] `ethan/tools/builtin/shell.py` — Shell 工具（带超时 + 输出截断）

### CLI 界面
- [x] `ethan/interface/tui.py` — Textual 全屏 TUI，流式渲染
- [x] `ethan/interface/cli.py` — 主入口，`ethan` / `ethan -m MODEL` / `ethan -p PROMPT`
- [x] `ethan/interface/commands/model.py` — `ethan model list/add/remove/default`
- [x] `ethan/interface/commands/provider.py` — `ethan provider list/set`
- [x] `bin/ethan` — shell 脚本，已链接到 `~/bin`

### 文档
- [x] `docs/README.md` — 文档索引
- [x] `docs/architecture.md` — 整体架构图 + 数据流
- [x] `docs/agent-loop.md` — Loop 设计 + 参考来源
- [x] `docs/providers.md` — Provider 层详解
- [x] `docs/tools.md` — 工具系统详解

### 验证
- [x] 所有模块导入通过
- [x] ShellTool 本地执行正常（`date` 命令）
- [x] API 连通（gemini-2.5-flash via OpenAI 兼容协议）
- [x] Agent Loop + Tool Call 端到端（LLM 调用 shell 返回当前时间）
- [x] `ethan model list/add/remove/default` 命令通过
- [x] `ethan provider list/set` 命令通过

---

## 阶段二：记忆系统

- [x] `ethan/memory/session.py` — Session 持久化（SQLite）
- [x] `ethan/memory/working.py` — 工作记忆（三层滑动窗口：热/温/冷）
- [x] `ethan/memory/consolidator.py` — 压缩器（廉价模型自动推断）
- [x] `ethan/memory/persistent.py` — 持久记忆（~/.ethan/memory/persistent.md）
- [x] `ethan/interface/commands/session.py` — `ethan session list/show/delete`
- [x] REPL 内斜杠命令：/sessions、/resume、/new、/help
- [x] `ethan -r last` / `ethan -r <id>` 恢复会话
- [x] `docs/memory.md` — 三层记忆架构设计文档
- [x] 验证：session 持久化 + 恢复上下文 ✅
- [ ] 验证：压缩触发后持久记忆写入（需长对话测试）

---

## 阶段三：Skill 系统

- [x] `ethan/skills/loader.py` — 从 ~/.ethan/skills/*.md 加载，解析 YAML frontmatter
- [x] `ethan/skills/registry.py` — Skill 注册表，关键词匹配，构建 context 注入
- [x] `ethan/skills/generator.py` — 从对话经验自动生成 Skill（Hermes 风格）
- [x] Agent 集成 — 每次 LLM 调用前匹配并注入 Skill 到 system prompt
- [x] `ethan/interface/commands/skill.py` — `ethan skill list/show/create`
- [x] 示例 Skill：weather-query.md
- [x] 验证：Skill 被 agent 自动识别并影响行为 ✅
- [ ] 验证：完成复杂任务后自动生成新 Skill 文件（需实际长对话触发）
- [x] `docs/skills.md` — Skill 系统设计文档

---

## 阶段四：调度器

- [x] `uv add apscheduler sqlalchemy` — 依赖已安装
- [x] `ethan/scheduler/cron.py` — APScheduler 封装（cron + interval，SQLite 持久化）
- [x] `ethan/interface/commands/schedule.py` — `ethan schedule list/remove/pause/resume`
- [x] 验证：创建定时任务 + 列出 + 删除 ✅
- [x] `ethan/scheduler/heartbeat.py` — 定期心跳（回顾待办）
- [x] REPL 内通过对话创建任务（agent 自己调 schedule tool）
- [x] `docs/scheduler.md` — 调度器设计文档

---

## 阶段五：工具系统完善 + MCP

- [x] `ethan/tools/builtin/web_search.py` — Web Search（DuckDuckGo，免费无需 key）
- [x] `ethan/tools/builtin/web.py` — Web Fetch（获取网页内容提取文本）
- [x] `ethan/tools/builtin/file.py` — 文件读写 + 目录列表
- [x] `ethan/tools/mcp_client.py` — MCP client（连接外部 MCP server，自动注册工具）
- [x] 验证：agent 读取本地文件并总结 ✅
- [x] 验证：MCP 模块导入正常 ✅
- [x] 更新 `docs/tools.md` — 补充 MCP 接入说明
- [ ] 验证：连接实际 MCP server 调用工具（需要具体 server）

---

## 阶段六：Interface 层（API + 流式）

- [x] `uv add fastapi uvicorn` — 依赖已安装
- [x] `ethan/interface/api.py` — FastAPI，`/chat`（POST）+ `/health` + `/models`
- [x] SSE 流式输出（`stream: true`）
- [x] `ethan serve` 命令启动 API 服务（默认端口 8900）
- [x] 验证：/health、/models、/chat 全部通过 ✅
- [x] `launchd` plist 配置 — Mac mini 开机自启
- [x] `docs/interface.md` — API 接口文档

---

## 阶段七：ACP 协议 + 外部 Coding Agent 集成

> Ethan 自身不擅长复杂编码，遇到代码任务时委托给专业 coding agent。

- [x] ACP（Agent Communication Protocol）客户端实现
- [x] 支持调用本地 Claude Code / OpenCode / Codex CLI
- [x] 自动判断任务复杂度 — 简单代码自己写，复杂任务转交
- [x] 结果回收 — 拿回 coding agent 的输出，整合进对话
- [x] `docs/acp.md` — ACP 集成设计文档
- [ ] 验证：用户问代码问题时，Ethan 自动拉起 Claude Code 完成，结果返回对话

---

## 阶段八：知识库系统 + 插件化接入

> 让 Ethan 拥有可扩展的外部知识来源。

- [x] 知识库抽象层设计（`ethan/knowledge/base.py`）
- [x] 默认实现：本地 Markdown 文件目录（`~/.ethan/knowledge/`）
- [ ] Obsidian 接入（官方插件）：读写 Obsidian vault
- [ ] 标准接口设计：第三方笔记系统通过 adapter 接入
- [ ] Embedding 索引 + 语义检索
- [x] `ethan knowledge` 子命令（list/search/add）
- [x] `docs/knowledge.md` — 知识库设计文档（待补）
- [x] 验证：agent 能通过 knowledge_search/add 工具操作知识库 ✅

---

## 记忆系统演进计划（阶段二增强）

> 在当前三层记忆基础上渐进增强。

- [x] Phase 2a：冷区升级为结构化 facts（JSON，带 confidence / timestamp / source）
- [ ] Phase 2b：加 embedding 索引，支持语义检索（chromadb 或 sqlite-vec）
- [x] Phase 2c：重要性评分 — 决策/偏好/纠正 > 闲聊，影响压缩策略
- [x] Phase 2d：Episodic memory — 每个 session summary 独立存储，按时间和相关性检索
- [x] Phase 2e：Procedural memory — agent 从纠正中学习，维护行为准则文件
- [x] Phase 2f：记忆防污染 — contradiction detection + confidence scoring

---

## 阶段九：Web UI

> 好看、酷、现代的 Web 界面。

- [x] 前端框架选型 — Next.js 14 + shadcn/ui + Tailwind
- [x] 对话界面 — 流式渲染、Markdown 支持、代码高亮
- [x] 暗色主题 + 动效（打字机效果）
- [x] Session 管理 — 侧边栏列出历史会话
- [x] 模型切换 — 顶部快速切换
- [x] 文件上传 — 📎 按钮 + 与 query 一起发送
- [x] Token 用量显示
- [x] 登录鉴权（Bearer token）
- [x] Tool 状态可视化 — 显示 agent 正在调用什么工具
- [ ] 响应式布局 — 移动端适配优化
- [x] Session 搜索（仅标题）
- [ ] Session 全文搜索（搜索消息内容）
- [ ] 日间模式（浅橙主题）切换支持

---

## 阶段十：体验与质量提升

### 时间感知
- [x] Agent 系统提示中注入实时时间（每次对话都带上当前时间）
  - 在 `ethan/core/agent.py` 的 `_build_system()` 中注入 `datetime.now()` 格式化时间串

### Session 管理优化
- [x] 不保存空 session：仅在第一条消息发送后才持久化 session
  - 修改 `ethan/interface/repl.py`：延迟 `store.create()` 调用
- [x] 清理历史空 session：`SessionStore.cleanup_empty()` + 退出时自动清理

### Web UI
- [x] Session 搜索（仅标题）
- [x] Session 全文搜索（后端：同时搜标题和消息内容；前端：防抖 300ms 调 `/sessions?q=`）
- [x] 日间模式（浅橙主题）：添加 `.light` 主题变量，顶部 Sun/Moon 切换按钮，localStorage 持久化

## 阶段十：Web 全功能面板

> 把 CLI 已有的所有能力搬到 Web UI，重构为多页面导航架构。

### 导航结构（左侧 icon nav）
- Chat — 当前对话界面（已有）
- Memory — Facts / Episodes 查看
- Skills — 列表/查看/创建
- Schedule — 定时任务管理
- Knowledge — 知识库列表/搜索/添加
- Logs — 后端日志查看（分页 + 搜索）

### 后端 API 扩展
- [ ] `GET /memory/facts` — 返回 facts.json 内容
- [ ] `GET /memory/episodes` — 返回 episodes.json 内容
- [ ] `GET /skills` — 列出所有 skill（name/description/trigger）
- [ ] `GET /skills/:name` — 返回 skill 完整内容
- [ ] `POST /skills` — 创建 skill
- [ ] `GET /schedule` — 列出定时任务
- [ ] `DELETE /schedule/:id` — 删除定时任务
- [ ] `PATCH /schedule/:id` — pause/resume 定时任务
- [ ] `GET /knowledge` — 列出知识库
- [ ] `POST /knowledge` — 添加条目
- [ ] `DELETE /knowledge/:source` — 删除条目
- [ ] `GET /logs?page=&q=` — 读取 backend.log，分页+搜索

### 前端实现
- [ ] 重构 layout：左侧 icon 导航栏 + 内容区
- [ ] Memory 页面：Facts 卡片（含 confidence/category）+ Episodes 列表
- [ ] Skills 页面：列表 + 内容预览 + 创建表单
- [ ] Schedule 页面：任务列表 + pause/resume/delete + 创建对话框
- [ ] Knowledge 页面：列表 + 搜索 + 添加 + 删除
- [ ] Logs 页面：日志列表、分页（每页 100 行）、关键词高亮搜索

### 知识库向量检索（后续）
- [ ] 引入 `sqlite-vec` 或本地 embedding 接口
- [ ] 知识库条目入库时同步生成 embedding
- [ ] `/knowledge/search` 支持语义检索

---

## 技术选型

| 用途 | 库 | 版本 | 状态 |
|------|----|------|------|
| 异步运行时 | `asyncio` + `uvloop` | 0.22+ | ✅ |
| Claude API | `anthropic` | 0.109+ | ✅ |
| OpenAI 兼容 | `openai` | 2.41+ | ✅ |
| CLI 框架 | `typer` | 0.26+ | ✅ |
| TUI 框架 | `textual` | 8.2+ | ✅ |
| 配置管理 | `pydantic` + `pyyaml` | 2.x | ✅ |
| 定时任务 | `APScheduler` | 3.x | 待安装 |
| 数据持久化 | `aiosqlite` | — | 待安装 |
| HTTP API | `FastAPI` + `uvicorn` | — | 待安装 |

### Bug Fixes
- [x] Web UI 中 CJK markdown 加粗不渲染的问题修复（在 `**` 和中文字符间插入零宽空格）
- [x] Web UI 修复 AI 生成 `** text **`（内部带空格）的格式问题，通过正则转换为 `**text**`

### Web UI 进阶功能（正在进行）
- [x] Web 导航重构：去掉冗余侧边栏底色，新增两级菜单结构（普通对话 / 定时对话分离）
- [x] Memory 管理面板：从弹窗重构为全屏二级页面，采用标准 Markdown 引擎渲染
- [x] Knowledge 管理面板：支持本地文件知识库检索、添加、删除
- [x] Schedule 管理面板：支持 APScheduler 任务状态查看、暂停、恢复、删除
- [x] URL 路由同步：将当前选中的 View 和 Session ID 同步至 URL（解决刷新丢失状态问题）
- [ ] Skills 管理面板：技能列表展示、预览与创建（待开发）
- [ ] Logs 日志面板：提供 Web 端的后端日志查看与分页检索（待开发）

### CLI 与 ACP 功能（正在进行）
- [x] `ethan code` 命令：支持挂载本地 ACP（Claude Code / OpenCode）做复杂任务委派
- [x] PTY 终端会话持久化（通过 pexpect 维持 Claude Code 交互流）

### 知识库加强（计划中）
- [ ] 引入 `sqlite-vec` 扩展，替换现有的关键词搜索为本地 Embedding 语义检索

### 自动化与质量保障（正在进行）
- [ ] 引入 E2E 端到端测试（Playwright）：覆盖 Web 核心主路径（新建/切换对话、浏览记忆列表、查看记忆详情、切换标签页等），确保 UI 和 API 层的稳定性。

### Agent 认知架构升级（正在进行）
- [ ] 模块化系统提示词引擎：废除单一字符串，引入 `~/.ethan/system/` 目录化内核（基于 `identity.md` 与 `soul.md`）。采用 XML 标签化拼接，结合具体执行的 Good/Bad Case（Anti-Looping，文件读写安全）彻底规范 Agent 行为。
- [ ] 优化 Web 端设置：将原先单文本框的系统设定页拆分为多模组编辑器（针对内核文件直接渲染修改）。

### Web UI 进阶功能（正在进行）
- [ ] 设置中心重构：将原先单页面的 Settings 升级为类 IDE 的双栏结构。支持通用设置、模型 Provider 配置，以及独立的 `identity.md`, `soul.md`, `format.md` 内核文件编辑区。

### 新增优化需求（用户反馈提取）
- [ ] **First-Time Onboarding (新用户冷启动引导)**: 无论是 REPL 还是 Web 界面，如果是第一次使用，Agent 需要主动发起第一条消息打招呼，引导用户：“请为我设置一个名字，并告诉我你是谁”。这些信息将通过自动记忆系统存入 `facts.json` 和 `config.yaml`。
- [ ] **Web 端路由重构 (Path-based Routing)**: 废除 `?view=memory&session=xxx` 这种丑陋的 Query 参数形式。重构为 Next.js 原生的文件系统路由，如 `/memory`, `/settings`, `/chat/[id]`。

### Agent 认知与交互架构（正在进行）
- [ ] **异步中断与连续对话 (Asynchronous Interrupt & Batching)**: 借鉴 Claude Code 机制。允许用户在 Agent 执行漫长任务时连续发送多条消息，将其缓冲进上下文队列。在合适的中断点（如一个 Tool 执行完毕时），Agent 能够感知到新指令并调整原有规划，做到不遗忘之前的任务，同时响应新的插话。

### Web UI 进阶功能（正在进行）
- [ ] **全部对话 (All Sessions) 聚合页**: 在左侧菜单新增“全部对话”入口，点击后在右侧主区域以网格卡片（3-4列）的形式展示所有的历史对话，包含摘要与元信息，支持点击直接进入会话。
