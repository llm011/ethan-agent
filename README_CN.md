# Ethan Agent

一个轻量、可扩展的个人 AI Agent，用 Python 构建。设计为在自有硬件上持久运行，具备随时间增长的记忆、定时任务和可插拔的工具/技能系统。

Ethan 融合了 [OpenClaw](https://github.com/openclaw/openclaw)（结构化 agent loop、分层记忆）、[Hermes Agent](https://github.com/NousResearch/hermes-agent)（自我进化技能、记忆整合）和 [nanobot](https://github.com/HKUDS/nanobot)（极简内核、可读代码）的设计理念。

---

## 特性

**记忆体系（五层）**
- 热区/温区/冷区三层滑动窗口维持长对话上下文，廉价模型自动压缩较早内容
- 结构化 Facts：带置信度的条目，有矛盾检测和自动去重（`~/.ethan/memory/facts.json`）
- 行为准则 Procedures：从用户纠正中自动学习，每次对话加载（`procedures.json`）
- 会话 Episodes：对话结束后自动生成摘要存档，支持关键词检索（`episodes.json`）
- 用户画像 Profile：叙事型文档，按章节存储个人语言、目标、约定等（`user_profile.md`）；含「基础特征」「心理与情绪」等章节
- **主动写记忆**：Agent 在对话中识别到可记忆信息时，主动调用工具即时写入，无需批量处理

**陪伴倾听模式 · 苏念（《臣服实验》心理咨询师）**
- 可加载插件：在聊天界面一键切换「苏念 · 陪伴倾听」，从工作助手变成一位年轻温柔的女性陪伴者，熟读《臣服实验》、深谙道法自然
- 该模式下 Agent 先赞许安抚、深度倾听、陪伴而非急于解决问题——说话像真人、温柔口语，拒绝 AI 腔
- 陪伴模式下，后台自动把「心理与情绪」（情绪/压力源/什么能安抚你/内心感受）整理进画像；基础特征由你在设置页「我的画像」里填写

**Skill 技能系统**
- 触发词匹配，自动注入 system prompt 引导行为
- `fast_path: true` 触发后走毫秒级快速路径，适合全屋智能等高频控制
- `channels: [lark, web]` 按渠道过滤，Skill 只在指定场景下生效
- Skill 命中统计与纠正收集，积累后 Heartbeat 自动用廉价模型更新 Skill 内容
- Agent 可在对话中即时创建新 Skill（`skill_create` 工具）

**三档智能路由**
- **fast**：短命令 + 关键词匹配 → 极简 prompt + 仅限 fast_path 工具 + 2 次迭代
- **medium**：中等消息 → 完整 prompt + 全部工具 + 4 次迭代
- **full**：复杂任务 → 完整 prompt + 全部工具 + 10 次迭代

**定时任务**
- 对话中创建 cron 或 interval 任务，SQLite 持久化，重启自动恢复
- `heartbeat.md`：写入自然语言任务，系统定期自动执行

**工具系统**
- Shell 执行、Web 搜索（默认 DuckDuckGo，可配置切换 Tavily）、Web 抓取、文件读写、知识库检索
- 工具结果超 4000 字自动用廉价模型压缩摘要
- 同参数重复调用自动命中轮次内缓存，不重复执行

**Prompt Caching**
- system prompt 分稳定层/动态层，稳定层缓存 5 分钟，token 成本降至 0.1×

**多渠道**
- CLI REPL、Web UI（Next.js）、**Android App**（Kotlin/Compose）、飞书（WebSocket 长连接，无需公网 IP）

---

## 安装

需要 Python 3.12+ 环境：

```bash
pip3 install ethan-agent
```

设置 API Key 后直接启动：

```bash
# Anthropic 官方接口
ethan provider set anthropic --api-key sk-ant-xxx

# 或者任意 OpenAI 兼容接口（如 DeepSeek、OpenRouter、Gemini、Ollama）
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
ethan model default <model-id>

# 或者智谱 GLM（内置预设，自动填好 base_url/type/抗缓存 + 注册 glm-5.2 等）
ethan provider set glm --api-key <你的GLM key>
ethan model default glm-5.2
# （所有内置预设见 `ethan provider presets`）

ethan
```

> 💡 **提示**: 运行 `ethan` 命令将在终端中启动交互式对话 REPL。当 `ethan serve` 运行时，Web UI 会内置托管在 `8900` 端口，运行 `ethan` 时会自动在浏览器中打开。你也可以随时运行 `ethan web` 来单独打开 Web 界面。

首次运行会自动初始化 `~/.ethan/`，写入默认技能和系统文件。

---

## 快速开始（Docker，适合服务器部署）

Docker 方式最省事，Backend 和 Web UI 各自独立容器，数据持久化到本地卷。**无需克隆代码库。**

### 前置条件

- Docker 20.10+
- Docker Compose v2

### 1. 下载配置并启动

```bash
mkdir ethan-agent && cd ethan-agent
curl -O https://raw.githubusercontent.com/llm011/ethan-agent/main/docker-compose.yml
```

### 2. 配置环境变量

创建 `.env` 文件，填入你的 API Key：

```bash
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-xxx
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.example.com/v1
AGENT_DEFAULT_MODEL=claude-sonnet-4-6
EOF
```

### 3. 启动

```bash
docker compose up -d
```

镜像会自动从 GitHub 下载。

### 4. 访问

- **Web UI**：http://localhost:3000
- **API**：http://localhost:8900
- **健康检查**：http://localhost:8900/health

### 5. 常用命令

```bash
docker compose logs -f ethan-backend   # 查看日志
docker compose restart ethan-backend   # 重启服务
docker compose pull && docker compose up -d  # 更新到最新版本
docker compose down                    # 停止
```

### 6. 多用户（可选）

Ethan 支持多用户共享一个实例，记忆（facts / procedures / episodes / sessions）、skills、知识库按用户完全隔离，互不可见。System prompt 和 provider 配置全局共享。

在 `config.yaml` 中预置用户（每个用户绑定一个 `web_token` 用于浏览器登录，和 `api_keys` 用于 `/v1/chat/completions` API 调用 —— 两者都解析到同一个 `user_id`）：

```yaml
users:
  - id: admin              # 稳定标识符，同时是数据目录名（建议用纯英文）
    name: Admin
    web_token: admin_pass  # 浏览器登录
    api_keys: [sk-ethan-admin-key]  # 程序调用 API
    is_admin: true
  - id: alice
    name: Alice
    web_token: alice_pass
    api_keys: [sk-ethan-alice-key]
    is_admin: false
```

若 `users` 为空（或缺失），Ethan 会自动生成一个 `admin` 用户，其 `web_token` 复用 `network.auth_token` —— 现有单用户部署零配置即可升级。首次启动时，现有全局数据会迁移到 admin 用户目录（原文件保留作备份，迁移幂等）。

---

## 本地开发 / 从源码安装

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Node.js 20+（仅 Web UI 需要）

### 安装

```bash
# PyPI 安装
pip install ethan-agent

# 或从源码
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
uv sync
```

### 配置

```bash
ethan provider set anthropic --api-key sk-ant-xxx
# 或者 OpenAI 兼容 API
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
```

### 运行

```bash
# 交互式 REPL
ethan

# 启动 Web 界面并在浏览器打开
ethan web
# (支持用 `--port 8900` 指定自定义端口，用 `--url` 快速打开指定页面)

# 管理 Web 界面登录凭证
ethan web token          # 查看当前 token
ethan web token --rotate # 重新生成并覆盖 token

# 单轮对话
ethan -p "今天有什么提醒？"

# 指定模型
ethan -m claude-opus-4-6

# 恢复上次会话
ethan -r last

# 启动 API + Web 服务
ethan serve
```

### Web UI 开发模式

```bash
cd web
npm install
npm run dev   # http://localhost:3000 (开发模式，API 仍在 8900 端口)
```

### Android App

原生移动端客户端，位于 `app/android/`。需要 Android SDK 35 和 JDK 17+。

```bash
cd app/android
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

首次启动时配置服务器地址（如 `http://<你的NAS>:8900`）和 Access Token（`~/.ethan/config.yaml` 中的 `network.auth_token`）。完整功能清单见 [app/android/PRD.md](./app/android/PRD.md)。

### macOS 开机自启（launchd）

```bash
./deploy/install.sh
```

---

## 架构

```
ethan/
├── core/
│   ├── agent.py          # ReAct loop，三档路由（fast/medium/full）
│   ├── config.py         # YAML 配置（~/.ethan/config.yaml）
│   └── heartbeat.py      # 心跳系统，定期维护任务
├── providers/
│   ├── anthropic.py      # Claude 原生协议 + Prompt Caching
│   └── openai_compat.py  # OpenAI 兼容协议
├── memory/
│   ├── working.py        # 热/温/冷三层滑动窗口
│   ├── facts.py          # 结构化 Facts（矛盾检测 + 置信度）
│   ├── procedures.py     # 行为准则（从纠正中学习）
│   ├── episodic.py       # 会话 Episode 摘要存档
│   └── consolidator.py   # 廉价模型压缩器
├── skills/
│   ├── loader.py         # 加载（目录格式 + 旧格式兼容）
│   ├── registry.py       # 匹配（含 channel 过滤）+ stats
│   ├── stats.py          # 命中统计 + 纠正记录
│   ├── updater.py        # 用廉价模型自动更新 Skill 内容
│   └── generator.py      # 从会话自动生成新 Skill
├── tools/
│   ├── registry.py           # 注册表 + 并发执行 + 轮次缓存
│   ├── result_compressor.py  # 超长结果摘要压缩
│   └── builtin/
│       ├── memory_write.py   # 主动写 Facts
│       ├── procedure_write.py # 主动写行为准则
│       ├── profile_update.py  # 更新用户画像
│       └── skill_create.py    # 对话中创建 Skill
├── scheduler/
│   └── cron.py           # APScheduler + SQLite
└── interface/
    ├── api.py            # FastAPI + SSE 流式
    ├── repl.py           # CLI REPL
    └── lark_events.py    # 飞书 WebSocket
```

---

## 记忆体系

五层架构：

| 层 | 内容 | 存储 |
|----|------|------|
| 热区 | 最近 N 轮完整消息 | 内存 |
| 温区 | 较早对话的滚动摘要 | 内存 |
| 冷区（Facts） | 跨 session 提炼的关键事实 | `~/.ethan/memory/facts.json` |
| 行为准则 | 从用户纠正中学习的规则 | `~/.ethan/memory/procedures.json` |
| 用户画像 | 叙事型个人信息（目标、短语、约定） | `~/.ethan/memory/user_profile.md` |

压缩是**批量触发**的（而非逐轮），使用自动推断的廉价模型（Claude 用户用 Haiku，Gemini 用户用 Flash Lite）。

Agent 通过 `memory_write`、`procedure_write`、`profile_update` 工具在对话中主动写入各层，无需等待下一个压缩周期。

---

## Skill 技能系统

Skill 从 `~/.ethan/skills/` 加载。首次运行时，包内默认技能（channels、deepwiki、lark-im、lark-shared、skills-manager）会自动复制到该目录。

支持目录格式（`<name>/SKILL.md` + `references/` 子目录）和旧版单文件 `.md` 格式。

```markdown
---
name: deploy-checklist
trigger: deploy|ship|发布
description: 发布前检查清单
fast_path: true       # 命中 trigger 时走 fast 轨
channels:             # 空 = 所有渠道；列表 = 限制渠道
  - web
version: "1.0"
---

发布前步骤：
1. 运行测试
2. 检查未提交的改动
3. ...
```

Skill 会累积命中次数和用户纠正记录。当纠正达到阈值（默认 2 条），Heartbeat 任务用廉价模型将纠正合并进 Skill 文件。

---

## 工具扩展

工具完全可插拔，无需修改 agent loop：

```python
from ethan.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "执行某些有用操作"
    fast_path = False   # True 则在 fast 轨下也可用
    cacheable = False   # True 则同参数调用命中轮次内缓存

    parameters = {"type": "object", "properties": {...}, "required": [...]}

    async def run(self, **kwargs) -> str:
        return "结果"
```

在 `cli.py` 注册后，LLM 会在合适时机自动调用。

---

## CLI 命令

```
ethan                              启动交互式 REPL
ethan -p "..."                     单轮对话
ethan -m MODEL                     指定模型
ethan -r last                      恢复上次会话
ethan serve                        启动 HTTP API 服务（前台运行）
ethan serve stop                   停止后台运行的 serve 进程
ethan serve restart                重启后台 serve 进程

ethan model list|add|remove|default
ethan provider list|set
ethan session list|show|delete
ethan skill list|show|create
ethan schedule list|remove|pause|resume
```

---

## HTTP API

```bash
GET  /health                    # 健康检查
GET  /models                    # 可用模型列表
POST /chat                      # 对话（stream: true 开启 SSE 流式）
GET  /sessions                  # 会话列表
GET  /sessions/{id}             # 会话详情（含消息历史）
GET  /memory/facts              # Facts 列表
GET  /memory/episodes           # Episode 摘要列表
GET  /skills                    # Skill 列表
POST /skills                    # 创建 Skill
POST /skills/evolve             # 手动触发 Skill 自动更新
GET  /schedule                  # 定时任务列表
GET  /system-prompt-preview     # 当前 system prompt 预览
GET  /channels                  # 渠道列表
GET  /knowledge/search          # 语义检索
```

---

## 配置

所有配置存储在 `~/.ethan/config.yaml`：

```yaml
providers:
  anthropic:
    api_key: sk-ant-xxx
    base_url: https://api.anthropic.com   # 可选
    proxy: null                           # provider 级别代理
  openai_compat:
    api_key: sk-xxx
    base_url: https://api.openai.com/v1

models:
  - id: claude-sonnet-4-6
    provider: anthropic
    description: Claude Sonnet 4.6
    alias: [sonnet]
  - id: gpt-4o
    provider: openai_compat
    alias: [gpt]

network:
  proxy: http://127.0.0.1:7890           # 全局代理

defaults:
  model: claude-sonnet-4-6
  agent_name: Ethan
  max_tokens: 4096
  max_tool_iterations: 10
  routing:
    fast_max_length: 12        # 超过此字数不走 fast 轨
    medium_max_length: 80      # 超过 fast 阈值、不超过此值走 medium 轨
    medium_max_iters: 15       # medium 轨最多迭代次数（可按需调大）
    fast_keywords:
      - "关*灯"
      - "开*灯"
      - "播放音乐"
    fast_skill_triggers:       # 命中后走 fast 轨（不受长度限制）
      - "home assistant"
      - "发飞书消息"
```

`.env` 中的环境变量会覆盖 config 文件中的值（适合管理密钥）。

### 配置目录结构

```
~/.ethan/
├── config.yaml          # 主配置（Provider、模型、路由）
├── system/
│   ├── identity.md      # Agent 身份（名字、角色）
│   ├── soul.md          # 行为原则（主动写记忆的指令在这里）
│   └── heartbeat.md     # 心跳任务（自然语言定义）
├── memory/
│   ├── facts.json       # 结构化 Facts
│   ├── procedures.json  # 行为准则
│   ├── episodes.json    # 会话摘要存档
│   └── user_profile.md  # 用户画像（叙事型）
├── skills/              # 用户自定义 Skill
│   └── <name>/
│       └── SKILL.md
└── sessions.db          # 会话历史（SQLite）
```

---

## 特色功能测试清单

以下功能可以逐一测试验证：

### 记忆体系

```bash
# 1. 主动写 Fact：Agent 自动识别并记录
发送："我叫 Alex，是一名 iOS 工程师"
验证：cat ~/.ethan/memory/facts.json | python3 -m json.tool | grep -A3 "Alex"

# 2. 主动写行为准则
发送："以后你回复我，请用简短的语气，不要废话"
验证：cat ~/.ethan/memory/procedures.json | python3 -m json.tool

# 3. 用户画像
发送："你可以用 Roots run deep 这个短语来激励我坚持"
验证：cat ~/.ethan/memory/user_profile.md

# 4. 纠正学习
发送一段回复 → "不对，应该用 XXX 方式"
验证：cat ~/.ethan/memory/procedures.json

# 5. 跨会话记忆（Facts 是否被加载）
重启 Agent，询问："你还记得我叫什么名字吗？"
```

### Skill 系统

```bash
# 1. 手动创建 Skill，验证触发
cat > ~/.ethan/skills/test-skill/SKILL.md << 'EOF'
---
name: test-skill
trigger: 测试技能|test skill
description: 这是一个测试技能
---
当用户触发这个技能时，回复：「技能已激活」
EOF
发送："测试技能"，观察回复

# 2. Fast Path Skill（加 fast_path: true）
在 Skill frontmatter 加 fast_path: true，然后发送触发词
比较响应速度与普通对话的差异（TTFT 应 < 1s）

# 3. Agent 自动创建 Skill
发送："我经常需要查询 HA 里的设备状态，帮我把这个查询流程保存为一个技能"
验证：ls ~/.ethan/skills/
```

### 定时任务

```bash
# 1. 创建定时提醒
发送："每天早上 9 点提醒我查看今日任务"
验证：ethan schedule list  # 或 Web UI 的 Schedule 页面

# 2. Heartbeat 任务
编辑 ~/.ethan/system/heartbeat.md，写入：
"每次运行时，检查今天是否有未完成的重要任务并汇总"
等待 10 分钟后查看是否有执行记录
```

### 工具调用

```bash
# 1. Web 搜索
发送："今天人民币对美元汇率是多少"
验证：工具调用时间轴应显示 web_search

# 2. Shell 执行
发送："查看当前目录下有哪些文件"
验证：shell 工具被调用，返回文件列表

# 3. 工具结果压缩（需要大量输出的命令）
发送："执行 find / -name '*.log' 2>/dev/null | head -100"
验证：回复开头应有 [摘要，原始输出 N 字] 前缀
```

### 路由与缓存

```bash
# 1. Fast Path 速度测试
发送："关灯"（或其他在 fast_keywords 里的词）
观察 REPL 状态栏或 Web UI 的 TTFT 数值，应 < 500ms

# 2. Prompt Caching 验证
连续发 2 条消息，查看第 2 条的 ⚡cache 数字
若 >0 则缓存命中
```

### 知识库

```bash
# 添加条目
发送："帮我记录：HA 的 REST API 地址是 http://192.168.1.x:8123"

# 语义检索
发送："我之前记录的 HA 地址是什么？"
```

---

## Roadmap

### ✅ 已完成

**核心 Agent**
- [x] 多模型 Provider（Anthropic + OpenAI 兼容：Gemini、GPT、Ollama 等）
- [x] ReAct agent loop + 流式输出
- [x] 三档路由：fast / medium / full，工具结果压缩，轮次内去重缓存
- [x] Prompt Caching（Anthropic 稳定层 cache_control，成本降至 0.1×）

**记忆体系（五层）**
- [x] 热/温/冷三层滑动窗口 + 廉价模型批量压缩
- [x] 结构化 Facts（置信度 + 矛盾检测）
- [x] 行为准则 Procedures（从用户纠正中学习）
- [x] 会话 Episode 存档（自动摘要，关键词检索）
- [x] 用户画像 UserProfile（叙事型，五章节文档）
- [x] 主动写记忆（`memory_write`、`procedure_write`、`profile_update`、`skill_create`）
- [x] Memory context 隔离（防污染标签）

**Skill 系统**
- [x] 双来源加载（内置 + 用户自定义）+ 渠道过滤（channels 字段）
- [x] fast_path 标记、Skill 命中统计、纠正收集、自动更新（Updater）
- [x] 会话结束后后台自动生成 Skill（Hermes 风格）
- [x] 内置技能：home-assistant、lark-im、channels、deepwiki

**工具**
- [x] shell、web_search、web_fetch、file_read/write/list、rg、fd
- [x] 知识库（sqlite-vec 语义检索）、定时任务管理、ACP 委派 Claude Code

**定时任务**
- [x] cron + interval，SQLite 持久化，重启自动恢复
- [x] heartbeat.md：自然语言定义周期任务，系统自动执行

**渠道与 API**
- [x] Web UI（Next.js）：对话时间轴、记忆管理、技能、定时、知识库、设置
- [x] Android App（Kotlin/Compose）：移动端客户端，聊天 SSE、会话、记忆、设置等
- [x] 飞书 WebSocket（无需公网 IP）
- [x] OpenAI 兼容 Completions API（`/v1/chat/completions`）+ API Key 管理
- [x] Docker 部署 + macOS launchd 自启

---

### 🚀 规划中

**体验增强**
- [x] **消息引用**：悬浮气泡显示引用按钮 → 输入框显示引用预览条；引用块以 `> [引用 ...]` 前缀注入给模型，原始消息干净入库
- [ ] **用户设置**：头像上传、显示名称，显示在对话气泡中
- [x] **定时任务引导**：Agent 识别对话中模糊的周期性需求，主动列出 1-2-3 候选定时方案让用户选（明确指令则直接创建）
- [ ] **复杂定时任务样例**：每日简报、设备巡检、定时知识整理等开箱即用模板

**渠道扩展**
- [ ] **企业微信（WeCom）**：接入企业微信应用消息，与飞书渠道并列
- [ ] **移动端适配**：底部 Tab 导航、触摸手势、键盘弹起适配

**Coding Agent 集成**
- [x] **ACP 持续对话优化**：`delegate_coding` 按「用户×工作目录」持久化 session_id，用 `--resume` 续接 Claude Code 多轮会话；stream-json 解析为 sub_steps，Web UI 时间轴折叠展示、最终结果高亮。OpenCode / Codex 也已接入（单轮）
- [ ] **MCP client 完善**：连接外部 MCP server，自动注册工具

**长期**
- [ ] **域隔离（Space）**：生活 / 工作 / 项目记忆独立，防止混杂
- [ ] **异步中断**：长任务执行中感知新消息，在工具调用间隙响应
- [ ] **Obsidian 接入**：读写 Obsidian vault 作为知识库

---

## 文档

详细设计文档在 [`docs/`](./docs/) 目录下：

- [架构总览](docs/architecture.md)
- [Agent Loop](docs/agent-loop.md)
- [三档路由](docs/routing.md)
- [Provider 层](docs/providers.md)
- [工具系统](docs/tools.md)
- [密钥管理](docs/secrets.md)
- [记忆系统](docs/memory.md)
- [Skill 系统](docs/skills.md)
- [定时任务](docs/scheduler.md)
- [接口层](docs/interface.md)

## 许可证

MIT
