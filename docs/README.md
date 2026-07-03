# Ethan Agent 文档索引

> 本文档体系随代码同步更新。每个模块都有对应的设计文档，记录架构决策和使用方式。

---

## 当前能力

- **多模型支持**：Claude、Gemini、OpenAI 兼容协议（OpenRouter、Ollama 等），通过配置文件按 model id 路由，支持流式输出与 tool_use
- **三层记忆系统**：热/温/冷滑动窗口 + 结构化 Facts（含 confidence/category/timestamp）+ 用户画像 + Episodic memory（会话摘要，按时间和相关性检索）
- **Skill 系统**：从 `~/.ethan/skills/*.md` 加载，YAML frontmatter 声明触发关键词，自动注入 system prompt；内置 lark-cli 系列技能
- **定时任务**：APScheduler（cron + interval），SQLite 持久化，支持通过对话创建任务，Web/CLI 均可管理
- **Web UI**：基于 Next.js App Router 的路径路由（`/chat`、`/memory`、`/knowledge`、`/schedule`、`/skills`、`/settings`），流式渲染、Markdown 高亮、深色/浅橙主题切换、移动端适配
- **飞书/Lark 集成**：WebSocket 长连接接入（无需公网 IP），支持 Markdown post 格式渲染、流式占位回复（buffer 积累再 patch）、THINKING 表情、新用户 onboarding
- **Fast Path 路由**：轻量意图检测，简单命令（智能家居控制等）走极简 Prompt + 最快模型，跳过完整 Agent Loop
- **网络搜索工具**：内置 `web_search`（DuckDuckGo 搜索，免费无需 API Key）和 `web_fetch`（抓取网页正文），让 Agent 随时获取互联网实时信息
- **浏览器自动化**：三层能力——`use-browser`（主技能，经 Ethan Browser 扩展操作本机真实 Chrome，复用用户 cookie/登录态）、`agent-browser`（兜底，零依赖 Rust CLI + 内置独立 Chrome，`snapshot` 输出省 token，适合单步操作）、`dev-browser`（沙箱 JS + 完整 Playwright API，适合复杂多步流程），均按需安装、用户装完即有
- **文件系统搜索**：rg（ripgrep）和 fd 作为内置工具，供 Agent 在本地文件系统中高效检索代码和文件
- **ACP 集成**：`delegate_coding` 工具 / `ethan code` 命令将复杂编码任务委派给 Claude Code / OpenCode / Codex；Claude Code 支持按工作目录续接多轮会话，工具调用过程解析为 sub_steps 在 Web UI 折叠展示
- **知识库**：本地 Markdown 知识库 + sqlite-vec 语义检索（embedding 索引），支持 search/read/add/edit（追加+替换）/delete
- **CLI (REPL)**：交互式会话管理，支持 `/sessions`、`/resume`、`/new` 等斜杠命令；会话来源标签（web/repl/lark）；自动生成标题；新用户 onboarding

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
| [对话模式](./modes.md) | Mode 机制、身份覆盖、按对话模式过滤技能、法律专家模式按需安装 |
| [法律专家模式](./legal-mode.md) | legal-assistant 技能详解：能力范围、架构链路、按需安装、来源许可 |
| [调度器](./scheduler.md) | 定时任务、cron + interval、SQLite 持久化 |
| [后台任务](./background-tasks.md) | 即时长任务异步执行、独立会话、按渠道回灌、终止、任务中心 Web 交互 |
| [接口层](./interface.md) | CLI (REPL)、HTTP API (SSE)、命令行工具、Web UI 路由 |
| [ACP 集成](./acp.md) | 外部 Coding Agent 委派协议、Claude Code / OpenCode / Codex 接入、多轮会话、sub_steps 解析 |
| [浏览器控制 · 总览与架构](./browser/overview.md) | 调用链总览、三段链路职责、端到端时序、代码地图 |
| [浏览器控制 · 传输层与协议](./browser/transport-protocol.md) | WebSocket 选型、JSON-RPC 信封、method/error 表、req-id 配对、超时/断连、last-wins |
| [浏览器控制 · 扩展内核 (CDP/AX)](./browser/extension-internals.md) | SW 保活、CDP attach 缓存、AX 快照算法、ref 生命周期、各动作 CDP 实现 |
| [浏览器控制 · 会话/并发/安全](./browser/session-security.md) | 会话绑定隔离、per-session 锁、idle release、鉴权/授权/归属、截图清理、eval 边界 |
| [浏览器控制 · 设计决策记录](./browser-control-plan.md) | grill 阶段确定的 10 项关键决策(Q1–Q10)及其理由 |
| Feishu/Lark 集成 | WebSocket 长连接、消息格式、onboarding 流程（见 `ethan/interface/lark_events.py`） |
