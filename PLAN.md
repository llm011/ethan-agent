# Ethan Agent 开发计划

## 当前架构总览

```
ethan/
├── core/          # Agent Loop（ReAct，三档路由 fast/medium/full）+ config + heartbeat
├── providers/     # Claude 原生 + OpenAI 兼容（Gemini/GPT/Ollama），Prompt Caching
├── memory/        # 五层记忆：WorkingMemory + Facts + Episodes + Procedures + UserProfile
├── skills/        # 双来源加载、channel 过滤、stats 统计、自进化（updater + generator）
├── tools/         # 插件化工具 + 结果压缩 + 轮次去重
├── scheduler/     # APScheduler + SQLite 持久化定时任务
├── defaults/      # 首次安装默认配置（identity/soul/agent/tools/heartbeat）
└── interface/     # CLI REPL + FastAPI + Web UI + 飞书 + OpenAI Completions API
```

---

## ✅ 已完成功能

### 核心 Agent Loop
- [x] ReAct 模式，流式输出 + tool_use 完整链路
- [x] 三档路由：fast（极简 prompt + fast_path 工具 + 2 次迭代）/ medium / full
- [x] 工具结果智能压缩（超 4000 字调廉价模型压缩）
- [x] 工具调用轮次内去重缓存（`cacheable` 字段控制）
- [x] System prompt 内存缓存（`_system_files`，避免每轮磁盘读取）
- [x] Prompt Caching（Anthropic 按 `Current time:` 分割稳定/动态层）

### Provider 层
- [x] Claude 原生协议（Anthropic SDK，含 Prompt Caching）
- [x] OpenAI 兼容协议（Gemini、GPT、Ollama、OpenRouter 等）
- [x] 按 model id / alias 路由，Provider 级代理
- [x] `max_tokens` 从 config 读取

### 记忆系统（五层）
- [x] WorkingMemory：热/温/冷三层滑动窗口，廉价模型批量压缩
- [x] Facts：结构化条目，置信度 + 矛盾检测 + 自动去重
- [x] Episodes：会话结束后自动生成摘要存档，关键词检索
- [x] Procedures：从用户纠正中学习行为准则
- [x] UserProfile：叙事型用户画像，分章节存储（`~/.ethan/memory/user_profile.md`）
- [x] 主动写记忆：`memory_write` / `procedure_write` / `profile_update` 工具，对话中即时写入
- [x] Memory context 隔离（`<memory_context>` / `<behavioral_guidelines>` 标签防污染）
- [x] REPL 记忆压缩异步化（fire-and-forget，不阻塞输入）
- [x] Heartbeat：10 分钟周期，facts 去重整理 + heartbeat.md 任务执行

### Skill 技能系统
- [x] 双来源加载：内置（`ethan/skills/`）+ 用户（`~/.ethan/skills/`），同名覆盖
- [x] 目录格式（`<name>/SKILL.md` + `references/`）+ 旧版单文件兼容
- [x] 触发词关键词匹配 + 通配符，自动注入 system prompt
- [x] `fast_path: true`：命中时走快速路径，不受消息长度限制
- [x] `channels` 字段：按渠道（web/lark/repl）过滤 Skill
- [x] Skill 命中统计（`stats.py`）+ 纠正收集，heartbeat 自动合并纠正到 Skill 内容
- [x] `skill_create` 工具：对话中即时创建新 Skill
- [x] 自动生成（`generator.py`）：会话结束后后台分析，廉价模型提炼 Skill
- [x] 内置技能：`home-assistant`、`lark-im`、`channels`、`deepwiki`

### 工具系统
- [x] 完全可插拔：实现 `BaseTool`，注册即用
- [x] 内置：shell、web_search（DuckDuckGo）、web_fetch、file_read/write/list、rg、fd
- [x] 内置记忆工具：memory_write、procedure_write、profile_update、skill_create
- [x] knowledge_add / knowledge_search（sqlite-vec 语义检索）
- [x] schedule_create / schedule_list / schedule_remove
- [x] ACP 工具：`ethan code` 委派 Claude Code / OpenCode via PTY

### 定时任务
- [x] cron + interval 两种模式，SQLite 持久化，重启自动恢复
- [x] 对话中创建：「每天 9 点提醒我查看邮件」
- [x] `heartbeat.md`：写入自然语言任务，系统定期自动执行

### 知识库
- [x] 本地 Markdown 文件目录（`~/.ethan/knowledge/`）
- [x] sqlite-vec embedding 向量索引，支持语义检索
- [x] `knowledge_add` / `knowledge_search` 工具

### Interface 层
- [x] CLI REPL：prompt_toolkit 底部状态栏、斜杠命令、流式输出
- [x] FastAPI HTTP API（`/chat` SSE 流式、session 管理、记忆、技能、调度等）
- [x] OpenAI 兼容 Completions API（`/v1/chat/completions`）+ API Key 管理
- [x] 飞书 WebSocket 长连接（无需公网 IP，THINKING 表情，markdown 渲染）

### Web UI（Next.js）
- [x] 对话页：流式渲染、工具调用时间轴（可折叠）、TTFT 展示
- [x] 工具调用时间轴：icon + 名称 + 参数 + 状态（running/done/error）+ 耗时，完成后自动折叠
- [x] Session 管理：侧边栏历史、全文搜索、会话重命名
- [x] Memory 页：Facts/Episodes/Procedures 三 Tab，Markdown 渲染、编辑、删除
- [x] Skills 页：列表 + 内容预览 + 创建
- [x] Schedule 页：任务列表 + pause/resume/delete
- [x] Knowledge 页：列表 + 语义搜索 + 添加 + 删除
- [x] Settings 页：双栏结构，Agent 设置 / Provider 配置 / 系统提示词编辑（identity/soul/agent/tools/heartbeat）
- [x] Prompt 预览：system prompt + 工具 schema token 估算，工具 schema 只读展示
- [x] 暗色/浅橙主题切换

### 部署
- [x] Docker + docker-compose（backend + web 独立容器，数据卷持久化）
- [x] macOS launchd 自启（`deploy/install.sh` 自动替换路径）
- [x] 首次安装默认配置文件自动释放（`ethan/defaults/system/`）

---

## 🚧 待完成（按优先级）

### P0 核心体验
- [ ] **`agent.md` 加入 system prompt 加载**：`_load_system_files()` 需加入 `"agent"`，`_build_system()` 注入为 `<agent_protocols>`，使主动写记忆指令生效
- [ ] **ACP 持续对话优化**：跑通 Claude Code / OpenCode / Codex 的多轮对话，优化回复内容展示（工具调用过程折叠，最终结果高亮）
- [ ] **定时任务引导**：Agent 在对话中识别到可能需要创建定时任务的场景，主动列出 1-2-3 问用户是否创建（soul.md 指令 + schedule_create 工具配合）

### P1 功能完善
- [ ] **消息引用**：Web UI 支持引用某条消息进行对话（气泡右键菜单 → 引用，输入框显示引用预览）
- [ ] **用户设置**：头像上传、显示名称，头像显示在对话气泡中
- [ ] **企业微信渠道**：参考 `lark_events.py`，接入企业微信 WebHook（WeCom）
- [ ] **复杂定时任务样例**：提供几个开箱即用的实用定时任务模板（每日简报、定时检查 HA 设备、定时知识库整理）
- [ ] **Home Assistant 完整集成**：fast_path Skill + HA REST API 工具，实现 ≤2s 智能家居控制

### P2 体验优化
- [ ] **移动端适配**：对话气泡宽度、底部 Tab 导航、触摸手势、键盘弹起适配
- [ ] **Skill 语义匹配**：当 skill 数量 > 20 时，考虑改 trigger 子串匹配为 embedding 语义匹配
- [ ] **知识库 Obsidian 接入**：读写 Obsidian vault（官方插件 + REST API）
- [ ] **facts 矛盾检测升级**：当前启发式误杀率较高，改为 heartbeat 时 LLM 判断

### P3 长期规划
- [ ] **域隔离（Space）**：FactStore / SkillRegistry / 知识库引入 `space` 维度（life/work/proj-xxx），防止记忆混杂
- [ ] **异步中断**：Agent 执行长任务时，感知新消息并在工具调用间隙响应
- [ ] **MCP client 完善**：连接外部 MCP server，自动注册工具

---

## 技术选型

| 用途 | 库 | 版本 | 状态 |
|------|----|------|------|
| 异步运行时 | `asyncio` + `uvloop` | 0.22+ | ✅ |
| Claude API | `anthropic` | 0.109+ | ✅ |
| OpenAI 兼容 | `openai` | 2.41+ | ✅ |
| CLI 框架 | `typer` | 0.26+ | ✅ |
| TUI / REPL | `prompt_toolkit` + `rich` | — | ✅ |
| 配置管理 | `pydantic` + `pyyaml` | 2.x | ✅ |
| 定时任务 | `APScheduler` | 3.x | ✅ |
| 数据持久化 | `aiosqlite` | — | ✅ |
| HTTP API | `FastAPI` + `uvicorn` | — | ✅ |
| 向量检索 | `sqlite-vec` | — | ✅ |
| Web UI | `Next.js` + `shadcn/ui` | 16+ | ✅ |
| 飞书 SDK | `lark-oapi` | — | ✅ |
