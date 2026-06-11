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
┌─────────────────────────────────────────────────────────┐
│                      Interface 层                        │
│              CLI（开发用）  /  FastAPI（生产用）           │
└────────────────────────┬────────────────────────────────┘
                         │ 用户输入 / 定时触发
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
                               ▼
                    ┌─────────────────────┐
                    │    Provider 层       │
                    │  Anthropic │ OpenAI  │
                    └─────────────────────┘
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
│   │   ├── agent.py          # 主 Agent Loop
│   │   ├── session.py        # 会话管理（待实现）
│   │   └── config.py         # 全局配置
│   ├── providers/
│   │   ├── base.py           # 抽象 Provider 接口
│   │   ├── anthropic.py      # Claude 原生 SDK
│   │   ├── openai_compat.py  # OpenAI 兼容协议
│   │   └── manager.py        # Provider 路由
│   ├── memory/               # 记忆系统（阶段二）
│   ├── skills/               # Skill 系统（阶段三）
│   ├── tools/
│   │   ├── base.py           # BaseTool 抽象
│   │   ├── registry.py       # ToolRegistry + ToolExecutor
│   │   └── builtin/
│   │       ├── shell.py      # Shell 工具
│   │       ├── file.py       # 文件工具（待实现）
│   │       └── web.py        # Web 工具（待实现）
│   ├── scheduler/            # 调度器（阶段四）
│   └── interface/
│       ├── cli.py            # CLI REPL
│       └── api.py            # FastAPI（阶段六）
├── docs/                     # 本文档体系
├── skills/                   # 用户 Skill 文件目录
├── .env                      # API Key 配置（不入 git）
├── config.yaml               # 可选的 YAML 配置
└── PLAN.md                   # 开发计划
```
