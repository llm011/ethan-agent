# Ethan Agent

一个轻量、可扩展的个人 AI Agent，用 Python 构建。设计为在自有硬件上持久运行，具备随时间增长的记忆、定时任务和可插拔的工具/技能系统。

Ethan 融合了 [OpenClaw](https://github.com/openclaw/openclaw)（结构化 agent loop、分层记忆）、[Hermes Agent](https://github.com/NousResearch/hermes-agent)（自我进化技能、记忆整合）和 [nanobot](https://github.com/HKUDS/nanobot)（极简内核、可读代码）的设计理念。

## 特性

- **多模型支持** — 接入 Claude、GPT、Gemini 或任何 OpenAI 兼容 API（Ollama、LM Studio、OpenRouter）。对话中随时通过斜杠命令切换模型，内置 Provider 级代理和别名支持。

- **持久记忆** — 三层记忆架构（热区/温区/冷区）在不爆 token 的前提下维持长对话上下文。最近几轮完整保留；较早内容由廉价模型批量压缩为摘要（自动从主模型推断）；核心要点跨 Session 永久存储。

- **会话管理** — 每次对话自动保存到 SQLite。用 `ethan -r last` 恢复上次会话，或用 `/sessions` 浏览历史。支持完整消息回放和元数据。

- **技能系统** — 将 Markdown 文件放入 `~/.ethan/skills/`，Ethan 即刻识别。技能通过关键词触发匹配，相关时自动注入 system prompt。Agent 还能从复杂问题的解决过程中自动生成新技能（Hermes 风格自我进化）。

- **工具系统** — 完全可插拔：实现 `BaseTool`，注册即用。内置 shell 执行、网页搜索（DuckDuckGo，无需 API key）、网页抓取和文件读写。新增能力永远不需要改动 agent loop。

- **定时任务** — 创建 cron 或 interval 任务，跨重启持久化（APScheduler + SQLite）。适用于定期提醒、数据检查或心跳任务。

- **HTTP API** — FastAPI 服务（`ethan serve`）提供 `/chat`（支持 SSE 流式）、`/models` 和 `/health` 接口。随时对接 Web 前端或移动应用。

- **快速 CLI** — 基于 prompt_toolkit 的轻量 REPL，正确处理中文宽字符编辑，底部状态栏显示模型/token/路径，斜杠命令控制会话，流式输出第一个 token 到达即开始打印。

## 快速开始

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
uv sync
```

### 配置

首次运行会自动生成 `~/.ethan/config.yaml`，也可通过环境变量配置：

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

或使用 CLI 命令：

```bash
# 配置 Provider
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1

# 添加模型
ethan model add gpt-4o -p openai_compat -d "GPT-4o"

# 设置默认模型
ethan model default gpt-4o
```

### 运行

```bash
# 交互式 REPL
uv run python -m ethan.interface.cli

# 单轮对话
uv run python -m ethan.interface.cli -p "东京今天天气怎么样？"

# 指定模型
uv run python -m ethan.interface.cli -m claude-sonnet-4-6

# 恢复上次会话
uv run python -m ethan.interface.cli -r last

# 启动 HTTP API 服务
uv run python -m ethan.interface.cli serve
```

### 全局安装（可选）

```bash
chmod +x bin/ethan
ln -s $(pwd)/bin/ethan ~/bin/ethan
# 之后直接用: ethan "你好"
```

## 架构

```
ethan/
├── core/
│   ├── agent.py               # ReAct agent loop
│   └── config.py              # YAML 配置 (~/.ethan/config.yaml)
├── providers/
│   ├── base.py                # 统一接口 (Message, ToolCall, BaseProvider)
│   ├── anthropic.py           # Claude 原生协议
│   ├── openai_compat.py       # OpenAI 兼容协议
│   └── manager.py             # Model ID → Provider 路由
├── memory/
│   ├── session.py             # 会话持久化 (SQLite)
│   ├── working.py             # 三层滑动窗口记忆
│   ├── consolidator.py        # 廉价模型压缩
│   └── persistent.py          # 跨会话持久记忆
├── skills/
│   ├── loader.py              # 从磁盘加载 .md 技能
│   ├── registry.py            # 匹配 & 注入技能到上下文
│   └── generator.py           # 从经验自动生成技能
├── tools/
│   ├── base.py                # BaseTool 抽象类
│   ├── registry.py            # 注册表 + 并发执行器
│   └── builtin/
│       ├── shell.py           # 执行 shell 命令
│       ├── web_search.py      # DuckDuckGo 搜索
│       ├── web.py             # 获取网页文本
│       └── file.py            # 文件读写/列表
├── scheduler/
│   └── cron.py                # APScheduler + SQLite 持久化
└── interface/
    ├── cli.py                 # Typer CLI 入口
    ├── repl.py                # prompt_toolkit 交互式 REPL
    ├── api.py                 # FastAPI HTTP + SSE 流式
    └── commands/              # 子命令 (model, provider, session, skill, schedule)
```

## 记忆系统

三层记忆架构在维持上下文的同时控制 token 成本：

| 层级 | 内容 | 存储 |
|------|------|------|
| 热区 | 最近 N 轮完整消息 | 内存 |
| 温区 | 较早对话的滚动摘要 | 内存 |
| 冷区 | 跨会话提取的关键要点 | `~/.ethan/memory/persistent.md` |

压缩是**批量的**（非逐轮），使用自动推断的廉价模型（如 Claude 用户自动用 Haiku，Gemini 用户用 Flash Lite）。

## 技能

技能是 `~/.ethan/skills/` 目录下带 YAML frontmatter 的 Markdown 文件：

```markdown
---
name: deploy-checklist
trigger: deploy|部署|发布|上线
description: 部署前检查清单
---

部署前步骤：
1. 运行测试
2. 检查未提交的改动
3. ...
```

当用户输入匹配到技能的触发关键词时，技能内容会被注入 system prompt 来引导 agent 行为。

## CLI 命令

```
ethan                              启动交互式 REPL
ethan -p "..."                     单轮对话
ethan -m MODEL                     指定模型
ethan -r last                      恢复上次会话
ethan serve                        启动 HTTP API 服务

ethan model list|add|remove|default
ethan provider list|set
ethan session list|show|delete
ethan skill list|show|create
ethan schedule list|remove|pause|resume
```

## HTTP API

```bash
# 健康检查
curl http://localhost:8900/health

# 列出模型
curl http://localhost:8900/models

# 对话
curl -X POST http://localhost:8900/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好"}]}'

# 流式对话 (SSE)
curl -X POST http://localhost:8900/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好"}], "stream": true}'
```

## 路线图

- [x] 多模型 Provider 系统（Anthropic + OpenAI 兼容）
- [x] ReAct agent loop + 流式输出
- [x] 会话持久化 & 恢复
- [x] 三层记忆 + 自动压缩
- [x] 技能系统（加载 + 匹配 + 自动生成）
- [x] 调度器（cron + interval）
- [x] 内置工具（shell、搜索、文件、网页）
- [x] HTTP API + SSE 流式
- [ ] MCP 协议 client
- [ ] ACP 协议（委托 Claude Code / Codex）
- [ ] 知识库 + Obsidian 集成
- [ ] Web UI
- [ ] 结构化记忆 + Embedding 检索
- [ ] 过程记忆（从纠正中学习）

## 文档

每个模块的详细设计文档在 [`docs/`](./docs/) 目录下：

- [架构总览](docs/architecture.md)
- [Agent Loop](docs/agent-loop.md)
- [Provider 层](docs/providers.md)
- [工具系统](docs/tools.md)
- [记忆系统](docs/memory.md)
- [技能系统](docs/skills.md)
- [调度器](docs/scheduler.md)
- [接口层](docs/interface.md)

## 许可证

MIT
