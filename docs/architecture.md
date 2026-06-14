# 架构总览

## 设计目标

Ethan 是一个运行在 Mac mini 上的个人 AI Agent，全程异步（`asyncio` + `uvloop`），长期常驻。核心目标：

- **多模型**：同时支持 Claude（Anthropic 原生协议）和 GPT/本地模型（OpenAI 兼容协议）
- **记忆**：跨会话的持久记忆 + 自动压缩
- **Skill**：可手写、可从经验自动生成的知识模块
- **调度**：定时任务、心跳机制
- **工具**：Shell、文件、Web、MCP 协议扩展

---

## 模块全景

```
┌──────────────────────────────────────────────────────────────────┐
│                          Interface 层                             │
│  CLI (REPL)  │  FastAPI (HTTP/SSE)  │  Web UI (Next.js 16)  │ Lark │
└────────────┴──────────┬──────────┴──────────────────────── ┴──────┘
                        │ 用户输入 / 定时触发
                        ▼
             ┌──────────────────────┐
             │   Fast-path Router   │  ← 简单命令在此短路，不进 Agent Loop
             └──────────┬───────────┘
                        │ 复杂请求
                        ▼
┌─────────────────────────────────────────────────────────┐
│                    Core Agent Loop                       │
│         ReAct：Thought → Action → Observation → …       │
└──┬─────────────┬──────────────┬──────────────┬──────────┘
   │             │              │              │
   ▼             ▼              ▼              ▼
┌──────┐   ┌─────────┐   ┌──────────┐   ┌──────────┐
│Memory│   │ Skills  │   │  Tools   │   │Scheduler │
│ 系统  │   │  系统   │   │   系统   │   │  调度器  │
└──────┘   └─────────┘   └────┬─────┘   └──────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
         ┌──────────┐  ┌────────────┐  ┌──────────────┐
         │ Provider │  │ Knowledge  │  │ Search Tools │
         │ 层       │  │ Base       │  │ (rg / fd)    │
         │Anthropic │  │(sqlite-vec)│  └──────────────┘
         │OpenAI    │  └────────────┘
         └──────────┘
```

---

## 各模块职责

### Provider 层 (`ethan/providers/`)
负责与 LLM API 通信，屏蔽不同厂商协议的差异。对上层只暴露统一的 `BaseProvider` 接口。
→ 详见 [providers.md](./providers.md)

### Core Agent Loop (`ethan/core/agent.py`)
系统的心脏。接收消息列表，驱动 ReAct 循环，协调 Provider、Tools、Memory、Skills。
→ 详见 [agent-loop.md](./agent-loop.md)

### 工具系统 (`ethan/tools/`)
定义 `BaseTool` 抽象，通过 `ToolRegistry` 注册，由 `ToolExecutor` 并发执行。
→ 详见 [tools.md](./tools.md)

### 记忆系统 (`ethan/memory/`)
三层结构：工作记忆（当前 context）、情节记忆（历史对话 SQLite）、持久记忆（用户画像 KV）。
→ 详见 [memory.md](./memory.md)

### Skill 系统 (`ethan/skills/`)
从 Markdown 文件加载 Skill，注入 system prompt。支持从经验自动生成新 Skill（Hermes 风格）。
→ 详见 [skills.md](./skills.md)

### 调度器 (`ethan/scheduler/`)
基于 APScheduler，支持 cron 表达式和 interval。Job 持久化到 SQLite，重启后自动恢复。
→ 详见 [scheduler.md](./scheduler.md)

### Web UI (`web/`)
Next.js 16 App Router 构建的浏览器界面，通过 FastAPI SSE 与后端通信。路由包括 `/chat`、`/chat/[id]`、`/memory`、`/knowledge`、`/schedule`、`/skills`、`/sessions`、`/settings`、`/channels`。消息气泡显示 TTFT 耗时，流式工具调用过程实时渲染。

### 飞书 / Lark 集成 (`ethan/interface/lark.py`)
基于 HTTP Webhook 方案，通过 `ethan serve` 暴露的 `/lark/webhook` 端点接收事件。收到消息后先加 THINKING 表情确认收到，Agent 处理完毕后发送单条完整回复。`chat_id` → `session_id` 映射持久化到 SQLite。
→ 详见 [interface.md](./interface.md)

### Fast-path Router
每轮对话开始时对用户输入做意图分类，决定走快轨（极简 prompt + 仅 fast_path 工具，最多 2 次迭代）还是慢轨（完整 prompt + 全量工具）。`fast_path: true` 的 Skill 的 trigger 关键词自动注入路由，无需手动配置。
→ 详见 [routing.md](./routing.md)

### 心跳系统 (`ethan/core/heartbeat.py`)
系统内部维护任务，启动时作为后台 asyncio 任务运行，每 N 分钟执行一次：对 `facts.json` 做 LLM 去重合并，并执行 `~/.ethan/system/heartbeat.md` 中定义的周期性任务。与用户管理的 Scheduler（APScheduler）独立运行。
→ 详见 [heartbeat.md](./heartbeat.md)

### 知识库 (`ethan/memory/knowledge.py`)
基于 `sqlite-vec` 的向量检索，文档写入时生成 embedding，查询时做余弦相似度检索。支持从 Web UI 上传、删除文档，Agent 可通过 `knowledge_search` 工具主动检索，也可通过 `/knowledge/search` HTTP 端点被外部服务调用。

### Prompt Caching (`ethan/providers/anthropic.py`)
Anthropic Provider 在发送 system prompt 前自动将其按 `Current time:` 分界点拆分为稳定层（identity/soul/tools_reference）和动态层（时间、记忆、Skill 匹配）。稳定层打上 `cache_control: ephemeral`，5 分钟内重复调用成本降至 0.1×。
→ 详见 [caching.md](./caching.md)

---

## 数据流（一次对话）

```
用户输入
   │
   ▼
[interface/cli.py] 构造 Message(role="user", content=...)
   │
   ▼
[core/agent.py] Agent.chat(messages)
   ├─ 从 SkillRegistry 选取相关 Skill → 追加到 system prompt
   ├─ 从 Memory 加载工作记忆
   │
   ▼
[providers/manager.py] create_provider(model) 路由到对应 Provider
   │
   ▼
[providers/anthropic.py 或 openai_compat.py] 调用 LLM API
   │
   ▼
返回 Message
   ├─ 如果 is_tool_call → [tools/registry.py] ToolExecutor 并发执行
   │       └─ tool 结果追加到 messages，继续循环
   └─ 如果是普通回复 → 返回给用户
                    └─ [memory/consolidator.py] 每10轮触发记忆压缩
```

---

## 技术选型

| 用途 | 库 | 版本 | 理由 |
|------|----|------|------|
| 异步运行时 | `asyncio` + `uvloop` | 0.22+ | 性能，Mac aarch64 原生支持 |
| Claude API | `anthropic` | 0.109+ | 官方 SDK，streaming + tool_use |
| OpenAI 兼容 | `openai` | 2.41+ | base_url 可配置，覆盖 GPT/Ollama |
| 定时任务 | `APScheduler` | 3.x | 成熟，SQLite 持久化 |
| 数据持久化 | `SQLite` + `aiosqlite` | — | 零依赖，本地足够 |
| 配置管理 | `pydantic-settings` | 2.x | 类型安全，支持 `.env` 覆盖 |
| HTTP API | `FastAPI` + `uvicorn` | — | 异步，SSE/WebSocket streaming |
| 包管理 | `uv` | 0.11+ | 速度快，已安装 |

---

## 目录结构

```
ethan-ai/
├── ethan/
│   ├── core/
│   │   ├── agent.py          # 主 Agent Loop（含 fast/full path 路由）
│   │   ├── config.py         # 全局配置（Pydantic）
│   │   ├── heartbeat.py      # 系统心跳（facts 去重 + heartbeat.md 任务）
│   │   └── onboarding.py     # 新用户引导
│   ├── providers/
│   │   ├── base.py           # 抽象 Provider 接口
│   │   ├── anthropic.py      # Claude 原生 SDK（含 Prompt Caching）
│   │   ├── openai_compat.py  # OpenAI 兼容协议
│   │   └── manager.py        # Provider 路由
│   ├── memory/
│   │   ├── session.py        # Session 持久化（SQLite）
│   │   ├── working.py        # 三层工作记忆（hot/warm/cold）
│   │   ├── consolidator.py   # 记忆压缩（廉价模型）
│   │   ├── facts.py          # FactStore（跨 session 长期 facts）
│   │   ├── procedures.py     # ProcedureStore（操作规范记忆）
│   │   ├── episodic.py       # EpisodicStore（历史 session 摘要）
│   │   └── knowledge.py      # 知识库（sqlite-vec 向量检索）
│   ├── skills/
│   │   ├── loader.py         # 双来源加载（内置 + 用户）
│   │   ├── registry.py       # 关键词匹配 + 注入
│   │   ├── generator.py      # 从经验自动生成 Skill
│   │   ├── channels/         # 内置 Skill：渠道管理
│   │   ├── lark-im/          # 内置 Skill：飞书 IM 操作
│   │   └── home-assistant/   # 内置 Skill：智能家居控制
│   ├── tools/
│   │   ├── base.py           # BaseTool 抽象
│   │   ├── registry.py       # ToolRegistry + ToolExecutor
│   │   └── builtin/
│   │       ├── shell.py      # Shell 命令执行
│   │       ├── file.py       # 文件读写列出
│   │       ├── web.py        # 网页抓取
│   │       ├── web_search.py # DuckDuckGo 搜索
│   │       ├── rg_search.py  # ripgrep 全文搜索
│   │       ├── fd_find.py    # fd 文件查找
│   │       ├── schedule.py   # 定时任务管理
│   │       ├── knowledge.py  # 知识库工具
│   │       └── acp.py        # 委托 Coding Agent
│   ├── scheduler/
│   │   └── cron.py           # APScheduler（SQLite 持久化）
│   ├── acp/
│   │   └── __init__.py       # ACP 复杂度判断 + 委托执行
│   └── interface/
│       ├── cli.py            # Typer CLI（含延迟导入优化）
│       ├── repl.py           # 交互式 REPL（prompt_toolkit）
│       ├── api.py            # FastAPI HTTP + SSE
│       ├── lark.py           # 飞书 Bot（WebSocket 长连接）
│       └── commands/         # 子命令（model/provider/session/skill/schedule）
├── web/                      # Next.js 16 Web UI
├── docs/                     # 本文档体系
├── .env                      # API Key 配置（不入 git）
└── PLAN.md                   # 开发计划
```
