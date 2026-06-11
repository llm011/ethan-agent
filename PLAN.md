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
- [ ] `docs/skills.md` — Skill 系统设计文档

---

## 阶段四：调度器

- [x] `uv add apscheduler sqlalchemy` — 依赖已安装
- [x] `ethan/scheduler/cron.py` — APScheduler 封装（cron + interval，SQLite 持久化）
- [x] `ethan/interface/commands/schedule.py` — `ethan schedule list/remove/pause/resume`
- [x] 验证：创建定时任务 + 列出 + 删除 ✅
- [ ] `ethan/scheduler/heartbeat.py` — 定期心跳（回顾待办）
- [ ] REPL 内通过对话创建任务（agent 自己调 schedule tool）
- [ ] `docs/scheduler.md` — 调度器设计文档

---

## 阶段五：工具系统完善 + MCP

- [x] `ethan/tools/builtin/web_search.py` — Web Search（DuckDuckGo，免费无需 key）
- [x] `ethan/tools/builtin/web.py` — Web Fetch（获取网页内容提取文本）
- [x] `ethan/tools/builtin/file.py` — 文件读写 + 目录列表
- [x] `ethan/tools/mcp_client.py` — MCP client（连接外部 MCP server，自动注册工具）
- [x] 验证：agent 读取本地文件并总结 ✅
- [x] 验证：MCP 模块导入正常 ✅
- [ ] 更新 `docs/tools.md` — 补充 MCP 接入说明
- [ ] 验证：连接实际 MCP server 调用工具（需要具体 server）

---

## 阶段六：Interface 层（API + 流式）

- [x] `uv add fastapi uvicorn` — 依赖已安装
- [x] `ethan/interface/api.py` — FastAPI，`/chat`（POST）+ `/health` + `/models`
- [x] SSE 流式输出（`stream: true`）
- [x] `ethan serve` 命令启动 API 服务（默认端口 8900）
- [x] 验证：/health、/models、/chat 全部通过 ✅
- [ ] `launchd` plist 配置 — Mac mini 开机自启
- [ ] `docs/interface.md` — API 接口文档

---

## 阶段七：ACP 协议 + 外部 Coding Agent 集成

> Ethan 自身不擅长复杂编码，遇到代码任务时委托给专业 coding agent。

- [ ] ACP（Agent Communication Protocol）客户端实现
- [ ] 支持调用本地 Claude Code / OpenCode / Codex CLI
- [ ] 自动判断任务复杂度 — 简单代码自己写，复杂任务转交
- [ ] 结果回收 — 拿回 coding agent 的输出，整合进对话
- [ ] `docs/acp.md` — ACP 集成设计文档
- [ ] 验证：用户问代码问题时，Ethan 自动拉起 Claude Code 完成，结果返回对话

---

## 阶段八：知识库系统 + 插件化接入

> 让 Ethan 拥有可扩展的外部知识来源。

- [ ] 知识库抽象层设计（`ethan/knowledge/base.py`）
- [ ] 默认实现：本地 Markdown 文件目录（`~/.ethan/knowledge/`）
- [ ] Obsidian 接入（官方插件）：读写 Obsidian vault
- [ ] 标准接口设计：第三方笔记系统通过 adapter 接入
- [ ] Embedding 索引 + 语义检索
- [ ] `ethan knowledge` 子命令（add/search/list/sync）
- [ ] `docs/knowledge.md` — 知识库设计文档
- [ ] 验证：用户添加 Markdown 到知识库后，agent 能在对话中检索并引用

---

## 记忆系统演进计划（阶段二增强）

> 在当前三层记忆基础上渐进增强。

- [x] Phase 2a：冷区升级为结构化 facts（JSON，带 confidence / timestamp / source）
- [ ] Phase 2b：加 embedding 索引，支持语义检索（chromadb 或 sqlite-vec）
- [x] Phase 2c：重要性评分 — 决策/偏好/纠正 > 闲聊，影响压缩策略
- [ ] Phase 2d：Episodic memory — 每个 session summary 独立存储，按时间和相关性检索
- [x] Phase 2e：Procedural memory — agent 从纠正中学习，维护行为准则文件
- [ ] Phase 2f：记忆防污染 — contradiction detection + confidence scoring

---

## 阶段九：Web UI

> 好看、酷、现代的 Web 界面。

- [ ] 前端框架选型（React / Svelte / Solid）
- [ ] 对话界面 — 流式渲染、Markdown 支持、代码高亮
- [ ] 暗色主题 + 动效（打字机效果、tool call 可视化）
- [ ] Session 管理 — 侧边栏列出历史会话，可搜索
- [ ] 模型切换 — 顶部快速切换
- [ ] Tool 状态可视化 — 显示 agent 正在调用什么工具
- [ ] 响应式布局 — 桌面 + 移动端适配
- [ ] 与 FastAPI 后端对接（阶段六的 SSE/WebSocket）

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
