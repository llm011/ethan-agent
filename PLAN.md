# Ethan Agent 开发计划

## 当前已完成的核心功能

- Provider 层：Claude / Gemini / OpenAI 兼容协议，按 model id 路由，流式输出 + tool_use
- Agent Loop：ReAct 模式，完整工具调用链路
- 三层记忆：热/温/冷滑动窗口 + 结构化 Facts + Episodic memory + 记忆防污染
- Skill 系统：从 `~/.ethan/skills/*.md` 加载，关键词匹配自动注入 system prompt
- APScheduler 定时任务：cron + interval，SQLite 持久化，对话中创建
- Web UI：Next.js App Router 路径路由（/chat、/memory、/knowledge、/schedule、/skills、/settings），流式渲染，深色/浅橙主题，移动端基础适配
- 飞书/Lark WebSocket 集成：无需公网 IP，Markdown 渲染，流式占位回复，onboarding
- Fast Path 路由：轻量意图分类，简单命令跳过完整 Agent Loop
- 内置工具：shell、web_search、web_fetch、file、rg（ripgrep）、fd
- ACP 集成：`ethan code` 通过 PTY 会话委派 Claude Code / OpenCode
- 知识库：本地 Markdown + sqlite-vec embedding 语义检索
- REPL：会话管理、斜杠命令、来源标签、自动标题、新用户 onboarding

---

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
├── memory/
├── skills/
├── tools/
│   ├── base.py                # BaseTool 抽象
│   ├── registry.py            # ToolRegistry + 并发 ToolExecutor
│   └── builtin/
│       ├── shell.py
│       ├── file.py
│       └── web.py
├── scheduler/
├── knowledge/
├── lark/
└── interface/
    ├── cli.py                 # 主入口（typer）
    ├── repl.py                # 交互式 REPL
    ├── api.py                 # FastAPI
    └── commands/
```

---

## 阶段一：Provider 层 + 基础 Agent Loop ✅

- [x] `ethan/providers/base.py` — 统一接口（Message、ToolCall、BaseProvider）
- [x] `ethan/providers/anthropic.py` — Claude 原生协议，支持流式 + tool_use
- [x] `ethan/providers/openai_compat.py` — OpenAI 兼容协议，支持流式 + tool_calling
- [x] `ethan/providers/manager.py` — 按 model id 从配置路由到对应 Provider
- [x] `ethan/core/config.py` — YAML 配置（~/.ethan/config.yaml），env 可覆盖
- [x] `ethan/core/agent.py` — ReAct Loop（非流式 + 流式）
- [x] `ethan/tools/base.py` — BaseTool 抽象
- [x] `ethan/tools/registry.py` — ToolRegistry + 并发 ToolExecutor
- [x] `ethan/tools/builtin/shell.py` — Shell 工具（带超时 + 输出截断）
- [x] `ethan/interface/tui.py` — Textual 全屏 TUI，流式渲染
- [x] `ethan/interface/cli.py` — 主入口，`ethan` / `ethan -m MODEL` / `ethan -p PROMPT`
- [x] `ethan/interface/commands/model.py` — `ethan model list/add/remove/default`
- [x] `ethan/interface/commands/provider.py` — `ethan provider list/set`
- [x] `bin/ethan` — shell 脚本，已链接到 `~/bin`

---

## 阶段二：记忆系统 ✅

- [x] `ethan/memory/session.py` — Session 持久化（SQLite）
- [x] `ethan/memory/working.py` — 工作记忆（三层滑动窗口：热/温/冷）
- [x] `ethan/memory/consolidator.py` — 压缩器（廉价模型自动推断）
- [x] `ethan/memory/persistent.py` — 持久记忆（~/.ethan/memory/persistent.md）
- [x] `ethan/interface/commands/session.py` — `ethan session list/show/delete`
- [x] REPL 内斜杠命令：/sessions、/resume、/new、/help
- [x] `ethan -r last` / `ethan -r <id>` 恢复会话
- [x] `docs/memory.md` — 三层记忆架构设计文档
- [x] Phase 2a：冷区升级为结构化 facts（JSON，带 confidence / timestamp / source）
- [x] Phase 2b：embedding 索引，支持语义检索（sqlite-vec）
- [x] Phase 2c：重要性评分 — 决策/偏好/纠正 > 闲聊，影响压缩策略
- [x] Phase 2d：Episodic memory — 每个 session summary 独立存储，按时间和相关性检索
- [x] Phase 2e：Procedural memory — agent 从纠正中学习，维护行为准则文件
- [x] Phase 2f：记忆防污染 — contradiction detection + confidence scoring
- [ ] 验证：压缩触发后持久记忆写入（需长对话测试）

---

## 阶段三：Skill 系统 ✅

- [x] `ethan/skills/loader.py` — 从 ~/.ethan/skills/*.md 加载，解析 YAML frontmatter
- [x] `ethan/skills/registry.py` — Skill 注册表，关键词匹配，构建 context 注入
- [x] `ethan/skills/generator.py` — 从对话经验自动生成 Skill（Hermes 风格）
- [x] Agent 集成 — 每次 LLM 调用前匹配并注入 Skill 到 system prompt
- [x] `ethan/interface/commands/skill.py` — `ethan skill list/show/create`
- [x] 示例 Skill：weather-query.md
- [x] `docs/skills.md` — Skill 系统设计文档
- [ ] 验证：完成复杂任务后自动生成新 Skill 文件（需实际长对话触发）

---

## 阶段四：调度器 ✅

- [x] `ethan/scheduler/cron.py` — APScheduler 封装（cron + interval，SQLite 持久化）
- [x] `ethan/interface/commands/schedule.py` — `ethan schedule list/remove/pause/resume`
- [x] `ethan/scheduler/heartbeat.py` — 定期心跳（回顾待办）
- [x] REPL 内通过对话创建任务（agent 自己调 schedule tool）
- [x] `docs/scheduler.md` — 调度器设计文档

---

## 阶段五：工具系统完善 + MCP ✅

- [x] `ethan/tools/builtin/web_search.py` — Web Search（DuckDuckGo，免费无需 key）
- [x] `ethan/tools/builtin/web.py` — Web Fetch（获取网页内容提取文本）
- [x] `ethan/tools/builtin/file.py` — 文件读写 + 目录列表
- [x] `ethan/tools/builtin/rg.py` / `fd.py` — rg/fd 内置搜索工具
- [x] `ethan/tools/mcp_client.py` — MCP client（连接外部 MCP server，自动注册工具）
- [x] 更新 `docs/tools.md` — 补充 MCP 接入说明
- [ ] 验证：连接实际 MCP server 调用工具（需要具体 server）

---

## 阶段六：Interface 层（API + 流式）✅

- [x] `ethan/interface/api.py` — FastAPI，`/chat`（POST）+ `/health` + `/models`
- [x] SSE 流式输出（`stream: true`）
- [x] `ethan serve` 命令启动 API 服务（默认端口 8900）
- [x] `launchd` plist 配置 — Mac mini 开机自启
- [x] `docs/interface.md` — API 接口文档

---

## 阶段七：ACP 协议 + 外部 Coding Agent 集成 ✅

- [x] ACP（Agent Communication Protocol）客户端实现
- [x] 支持调用本地 Claude Code / OpenCode / Codex CLI
- [x] `ethan code` 命令：PTY 终端会话持久化（通过 pexpect 维持 Claude Code 交互流）
- [x] 自动判断任务复杂度 — 简单代码自己写，复杂任务转交
- [x] 结果回收 — 拿回 coding agent 的输出，整合进对话
- [x] `docs/acp.md` — ACP 集成设计文档
- [ ] 验证：用户问代码问题时，Ethan 自动拉起 Claude Code 完成，结果返回对话

---

## 阶段八：知识库系统

- [x] 知识库抽象层设计（`ethan/knowledge/base.py`）
- [x] 默认实现：本地 Markdown 文件目录（`~/.ethan/knowledge/`）
- [x] 引入 `sqlite-vec`，知识库条目入库时同步生成 embedding
- [x] `ethan knowledge` 子命令（list/search/add）
- [x] `docs/knowledge.md` — 知识库设计文档
- [ ] `/knowledge/search` 语义检索 API 端点
- [ ] Obsidian 接入（官方插件）：读写 Obsidian vault
- [ ] 标准接口设计：第三方笔记系统通过 adapter 接入

---

## 阶段九：Web UI ✅

- [x] 前端框架选型 — Next.js 14 + shadcn/ui + Tailwind
- [x] 对话界面 — 流式渲染、Markdown 支持、代码高亮
- [x] 暗色主题 + 日间模式（浅橙主题）切换，localStorage 持久化
- [x] Session 管理 — 侧边栏列出历史会话 + 全文搜索（防抖 300ms）
- [x] 模型切换 — 顶部快速切换
- [x] 文件上传 — 📎 按钮 + 与 query 一起发送
- [x] Token 用量显示
- [x] 登录鉴权（Bearer token）+ 前端自动重试机制
- [x] Tool 状态可视化 — 显示 agent 正在调用什么工具
- [x] 响应式布局 — 移动端基础适配

---

## 阶段十：Web 全功能面板 ✅

### 路由架构
- [x] App Router 路径路由：`/chat`、`/chat/[id]`、`/memory`、`/knowledge`、`/schedule`、`/skills`、`/settings`（废除 query 参数形式）
- [x] 重构 layout：左侧 icon 导航栏 + 内容区

### 后端 API
- [x] `GET /memory/facts` — 返回 facts.json 内容
- [x] `GET /memory/episodes` — 返回 episodes.json 内容
- [x] `GET /skills` / `GET /skills/:name` / `POST /skills`
- [x] `GET /schedule` / `DELETE /schedule/:id` / `PATCH /schedule/:id`
- [x] `GET /knowledge` / `POST /knowledge` / `DELETE /knowledge/:source`
- [x] `GET /logs?page=&q=` — 读取 backend.log，分页+关键词搜索

### 前端面板
- [x] Memory 页面：Facts 卡片（含 confidence/category）+ Episodes 列表
- [x] Skills 页面：列表 + 内容预览 + 创建表单
- [x] Schedule 页面：任务列表 + pause/resume/delete + 创建对话框
- [x] Knowledge 页面：列表 + 搜索 + 添加 + 删除
- [x] Logs 页面：日志列表、分页（每页 100 行）、关键词高亮搜索
- [x] Settings 页面：双栏结构，支持通用设置、模型 Provider 配置、identity.md / soul.md / format.md 内核文件编辑

---

## 飞书/Lark 集成 ✅

- [x] 基础飞书 WebSocket 长连接（无需公网 IP）
- [x] 收到消息时添加 THINKING 表情，回复后自动移除
- [x] 消息使用 post 格式 Markdown 渲染
- [x] 流式回复体验：先发占位消息，buffer 积累后 patch
- [x] 新用户完成飞书授权后自动发欢迎消息（onboarding 集成）

---

## Agent 体验优化 ✅

- [x] Fast Path 任务分类路由：简单命令（智能家居等）→ 最快模型 + 极简 Prompt，跳过 Agent Loop
- [x] 最小化 System Prompt：按任务类型动态裁剪
- [x] 模块化系统提示词引擎：`~/.ethan/system/`（identity.md、soul.md），XML 标签化拼接
- [x] Agent 系统提示中注入实时时间
- [x] 不保存空 session：仅在第一条消息发送后才持久化
- [x] 对话来源渠道标签（source）展示在侧边栏（web/repl/lark）
- [x] 对话标题为 query 摘要，禁止内部前缀
- [x] First-Time Onboarding：首次使用时 Agent 主动打招呼，引导设置名字
- [x] 工具调用返回空时的 fallback 机制
- [x] CJK markdown 加粗渲染修复（零宽空格）

---

## 阶段十一：Agent 体验深化 ✅（部分）

### Prompt 工程
- [x] **Prompt Caching**：anthropic.py 按 `Current time:` 分割稳定/动态部分，稳定层加 `cache_control: ephemeral`，每轮对话节省 ~80% 输入 token
- [x] **format.md 合并**：输出格式规则并入 soul.md，减少 XML 块拼接
- [x] **tools.md 支持**：用户可自定义工具描述，注入为 `<tools_reference>`；设置页可编辑
- [x] **System Prompt 预览**：设置页实时展示每轮拼接内容及 token 估算
- [x] **定时任务摘要**：不再把完整任务列表注入 prompt，改为 "You have N active tasks, call schedule_list to view"
- [x] **max_tokens 读 config**：不再硬编码 4096，从 `config.defaults.max_tokens` 读取

### Fast Path 修复与增强
- [x] **Fast Path tools 修复**：之前 fast path 传 `tools=None` 导致无法执行动作，现在 fast/full 共用工具列表，只有 system prompt 不同
- [x] **Fast Path + Skill 关联**：Skill frontmatter 支持 `fast_path: true`，config 支持 `fast_skill_triggers`（不受长度限制），Web 设置页可配置
- [ ] **Home Assistant 集成**：`home-assistant` skill + Fast Path 确定性管道，真正实现 ≤2s 智能家居控制

### Skill 系统重构
- [x] **双来源加载**：内置技能 `ethan/skills/<name>/SKILL.md`（随代码发布），用户技能 `~/.ethan/skills/<name>/SKILL.md`，同名用户覆盖内置
- [x] **目录格式**：每个 skill 是子目录，含 `SKILL.md` + `references/`（与 lark-cli 官方格式一致）
- [x] **内置技能**：`channels`（渠道接入配置）、`lark-im`（官方完整版，含 24 个 reference 文档）
- [ ] **Skill 匹配升级**：当前为 trigger 子串匹配，考虑改为 embedding 语义匹配（低优先级，等 skill 数量 > 20 再做）

### 记忆系统
- [x] **Web 端记忆沉淀**：`_stream_response` 完成后 `asyncio.create_task` 后台跑 `_maybe_consolidate()`，每 10 轮触发一次 facts 整理
- [x] **Heartbeat 心跳**：系统级定时任务（默认 10min），facts 去重整理 + 执行 `heartbeat.md` 中的周期任务；设置页可配置开关和间隔
- [x] **Memory 页面完善**：Facts/Episodes/Procedures 三 Tab，支持 Markdown 渲染、编辑（分栏预览）、删除

### Web UI
- [x] **渠道页面** `/channels`：飞书配置卡片，可扩展架构，侧边栏入口
- [x] **设置页完善**：代理、max_tokens、max_tool_iterations、Fast-path 关键词、Fast-path Skill 触发词、心跳配置
- [x] **TTFT 显示**：消息气泡底部展示首字耗时（Web + REPL）

---

## 待完成（按优先级）

### P0 架构问题（需讨论后动手）
- [ ] **域隔离（Space 概念）**：当前 FactStore / SkillRegistry / 知识库是全局单例，生活/工作/项目记忆混在一起。需在 config 和各 Store 引入 `space` 维度（life/work/proj-xxx），路由时带上下文。这是防止系统变"乱"的核心屏障
- [ ] **异步中断与连续对话**：用户在 Agent 执行漫长任务时连续发送多条消息，缓冲进上下文队列，在合适中断点感知新指令

### P1 功能完善
- [ ] **Home Assistant 集成**：用户已有 HA skill，放入 `~/.ethan/skills/` 后即可生效；如需 Fast Path 确定性管道（完全绕过 LLM），后续在 skill frontmatter 加 `fast_path: true` 并配置触发词
- [ ] **REPL 与 API 记忆一致性**：REPL 有完整 WorkingMemory 滑动窗口，Web/Lark 没有，长对话 token 会膨胀。Web/Lark 需要加同等的 hot/warm 窗口管理
- [ ] **facts 矛盾检测升级**：当前是字符重叠 + 否定词启发式，误杀率高。改为 LLM 判断（在 heartbeat consolidation 时处理）
- [ ] **SystemSettingsPatch 验证**：检查 api.py 中 SystemSettingsPatch 是否有悬空字段，确保可以正常 PATCH

### P2 体验优化
- [ ] **H5/移动端完整适配**：对话区气泡宽度、侧边栏底部 Tab、触摸手势、输入法键盘弹起
- [ ] `/knowledge/search` 语义检索 API 端点
- [ ] Obsidian vault 接入
- [ ] **Tools on demand**：按 Fast/Full Path 按需加载工具，减少 Full Path tool schema token

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
| 定时任务 | `APScheduler` | 3.x | ✅ |
| 数据持久化 | `aiosqlite` | — | ✅ |
| HTTP API | `FastAPI` + `uvicorn` | — | ✅ |
| 向量检索 | `sqlite-vec` | — | ✅ |
| Web UI | `Next.js` + `shadcn/ui` | 14+ | ✅ |
| Lark SDK | `lark-oapi` | — | ✅ |
