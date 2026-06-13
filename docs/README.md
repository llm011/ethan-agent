# Ethan Agent 文档索引

> 本文档体系随代码同步更新。每个模块都有对应的设计文档，记录架构决策和使用方式。

---

## 当前能力

- **多模型支持**：Claude、Gemini、OpenAI 兼容协议（OpenRouter、Ollama 等），通过配置文件按 model id 路由，支持流式输出与 tool_use
- **三层记忆系统**：热/温/冷滑动窗口 + 结构化 Facts（含 confidence/category/timestamp）+ Episodic memory（会话摘要，按时间和相关性检索）
- **Skill 系统**：从 `~/.ethan/skills/*.md` 加载，YAML frontmatter 声明触发关键词，自动注入 system prompt；内置 lark-cli 系列技能
- **定时任务**：APScheduler（cron + interval），SQLite 持久化，支持通过对话创建任务，Web/CLI 均可管理
- **Web UI**：基于 Next.js App Router 的路径路由（`/chat`、`/memory`、`/knowledge`、`/schedule`、`/skills`、`/settings`），流式渲染、Markdown 高亮、深色/浅橙主题切换、移动端适配
- **飞书/Lark 集成**：WebSocket 长连接接入（无需公网 IP），支持 Markdown post 格式渲染、流式占位回复（buffer 积累再 patch）、THINKING 表情、新用户 onboarding
- **Fast Path 路由**：轻量意图检测，简单命令（智能家居控制等）走极简 Prompt + 最快模型，跳过完整 Agent Loop
- **内置搜索工具**：rg（ripgrep）和 fd 作为内置工具，供 agent 在文件系统中高效检索
- **ACP 集成**：`ethan code` 命令通过 PTY 持久会话将复杂编码任务委派给 Claude Code / OpenCode，结果回收进对话
- **知识库**：本地 Markdown 知识库 + sqlite-vec 语义检索（embedding 索引），支持 add/search/delete
- **REPL**：交互式会话管理，支持 `/sessions`、`/resume`、`/new` 等斜杠命令；会话来源标签（web/repl/lark）；自动生成标题；新用户 onboarding

---

## 文档列表

| 文档 | 描述 |
|------|------|
| [架构总览](./architecture.md) | 整体系统架构、模块关系图、数据流 |
| [Agent Loop](./agent-loop.md) | 核心循环设计、参考来源、ReAct 模式详解 |
| [Provider 层](./providers.md) | 多模型接入、Anthropic / OpenAI 协议适配 |
| [工具系统](./tools.md) | Tool 抽象、注册表、执行器、内置工具（shell、web_search、web_fetch、file、rg、fd）、MCP 接入 |
| [记忆系统](./memory.md) | Session 持久化、三层记忆（热/温/冷）、Facts、Episodic memory、压缩机制 |
| [Skill 系统](./skills.md) | Skill 加载、关键词匹配注入、自动生成 |
| [调度器](./scheduler.md) | 定时任务、cron + interval、SQLite 持久化 |
| [接口层](./interface.md) | REPL、HTTP API (SSE)、CLI 命令结构、Web UI 路由 |
| [ACP 集成](./acp.md) | 外部 Coding Agent 委派协议、Claude Code / OpenCode 接入、PTY 会话 |
| Feishu/Lark 集成 | WebSocket 长连接、消息格式、onboarding 流程（见 `ethan/lark/`） |
