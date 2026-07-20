# Ethan Agent

[English](./README.md)

一个轻量、可扩展的个人 AI Agent，用 Python 构建。设计为在自有硬件上持久运行，具备随时间增长的记忆、定时任务和可插拔的工具/技能系统。

Ethan 融合了 [OpenClaw](https://github.com/openclaw/openclaw)（结构化 agent loop、分层记忆）、[Hermes Agent](https://github.com/NousResearch/hermes-agent)（自我进化技能、记忆整合）和 [nanobot](https://github.com/HKUDS/nanobot)（极简内核、可读代码）的设计理念。

---

## 功能总览

| 类别 | 你能得到什么 |
|------|------------|
| **记忆** | 结构化长期记忆，带原文 quote 佐证、64 个维度、语义去重、夜间"做梦"沉淀、行为准则、用户画像 |
| **路由** | 三档（fast / medium / full）意图路由，卡死检测 + 优雅收尾 |
| **技能** | 可插拔 Markdown 技能，关键词匹配 + 可选语义路由器；开箱自带 40+ 内置技能 |
| **工具** | Shell、Web 搜索、Web 抓取、文件 I/O、知识库、图表、浏览器、桌面控制、ACP 委派 |
| **渠道** | CLI REPL、Web UI（Next.js）、桌面端（Tauri）、Android App、飞书（WebSocket，无需公网 IP） |
| **调度** | Cron + interval 任务、自然语言 `heartbeat.md` 任务、异步后台任务 |
| **模式** | 可切换的对话模式——陪伴倾听（苏念）、法律专家、沉浸式 Coding Agent（Codex / Claude Code / OpenCode） |
| **缓存** | Prompt Caching（Anthropic 稳定前缀，token 成本降至 0.1×）+ 轮次内工具调用去重 |
| **多用户** | 按用户隔离的记忆 / 技能 / 知识库，共享 provider 配置 |
| **UI** | A2UI 结构化卡片、Chart.js 交互图表（MCP Apps / SEP-1865）、工具时间轴、搜索卡片轮播 |

详细能力说明见下文 [特性](#特性) 段落。

---

## 部署方式

按场景挑一种。四种方式最终都生成同一个 `~/.ethan/` 数据目录和 `ethan` 命令。

| 方式 | 适合 | 依赖 |
|------|------|------|
| [桌面端 App](#方式-1桌面端-appmacos--windows) | macOS / Windows 普通用户 | 无（一键安装） |
| [pip 安装](#方式-2pip-安装) | 本地 CLI / Python 用户 | Python 3.12+ |
| [Docker](#方式-3docker推荐用于服务器) | 服务器 / NAS 部署 | Docker 20.10+ & Compose v2 |
| [从源码](#方式-4从源码开发) | 开发 / 贡献代码 | Python 3.12+、uv、Node 20+ |

### 方式 1：桌面端 App（macOS / Windows）

从 [GitHub Releases](https://github.com/llm011/ethan-agent/releases) 下载安装包：

| 平台 | 文件 |
|------|------|
| macOS Apple Silicon | `Ethan.Agent_<ver>_aarch64.dmg` |
| macOS Intel | `Ethan.Agent_<ver>_x64.dmg` |
| Windows | `Ethan.Agent_<ver>_x64-setup.exe` 或 `.msi` |

桌面端把完整的 Web UI 包进 Tauri 原生窗口。首次启动自动初始化 `~/.ethan/`，并引导你完成 Onboarding（填 API Key、选模型、起 Agent 名字）。

> **macOS Gatekeeper 提示**：app 未签名，首次打开会显示"已损坏"。在终端执行一次，之后正常双击即可：
> ```bash
> xattr -dr com.apple.quarantine "/Applications/Ethan Agent.app"
> ```

### 方式 2：pip 安装

需要 Python 3.12+。

```bash
pip3 install ethan-agent
```

装完即可使用 `ethan` 命令。首次运行自动初始化 `~/.ethan/`，写入默认技能和系统文件。

### 方式 3：Docker（推荐用于服务器）

Backend 和 Web UI 同在一个容器，数据持久化到宿主机的 `~/.ethan/`（bind mount —— 方便查看/备份/迁移，并和本机 `pip` 装的 `ethan` 共享同一份数据目录）。**无需克隆代码库。**

```bash
mkdir ethan-agent && cd ethan-agent
# 自包含变体：容器内从 PyPI 拉最新版（无需其他文件）
curl -o docker-compose.yml https://raw.githubusercontent.com/llm011/ethan-agent/main/deploy/docker-compose.pip.yml

# 创建 .env（必填字段见下）
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-xxx
AGENT_DEFAULT_MODEL=claude-sonnet-4-6
EOF

docker compose up -d
```

想要内置 SearXNG（免费、隐私友好的自建搜索）？克隆仓库用完整 compose：

```bash
git clone --depth=1 https://github.com/llm011/ethan-agent.git
cd ethan-agent/deploy
cp .env.example .env   # 编辑 .env 填入 API Key
docker compose -f docker-compose.yml up -d   # 内置 SearXNG + 用预构建 GHCR 镜像
```

`.env` 字段（完整模板见 [`deploy/.env.example`](./deploy/.env.example)）：

```bash
ANTHROPIC_API_KEY=sk-ant-xxx        # 或 OPENAI_API_KEY + OPENAI_BASE_URL
AGENT_DEFAULT_MODEL=claude-sonnet-4-6
ETHAN_AUTH_TOKEN=                   # Web UI 登录 token（空 = 不鉴权，局域网可留空）
ETHAN_PROXY=                        # 可选 HTTP 代理
GH_TOKEN=                           # 可选，让容器内 gh 命令可用
SEARXNG_BASE_URL=                   # 可选，让 web_search 走 SearXNG
```

访问：

| 服务 | URL |
|------|-----|
| Web UI & API | http://localhost:8900 |
| 健康检查 | http://localhost:8900/health |
| SearXNG（若启用） | http://localhost:8888 |

常用命令：

```bash
docker compose logs -f ethan              # 查看日志
docker compose restart ethan              # 重启后端
docker compose pull && docker compose up -d  # 更新到最新
docker compose down                       # 停止
```

[`deploy/`](./deploy/) 里的变体：
- `docker-compose.searxng.yml` —— 自建 SearXNG 实例（免费、无 API Key、隐私友好）
- `docker-compose.pip.yml` —— 在 vanilla Python 容器里 `pip install ethan-agent` 的另一种方案
- `docker-compose.nas.yml` —— NAS 适配变体

> **一键装法律专家模式**：在 `docker compose up` 前设 `ETHAN_INSTALL_SKILLS=legal`（或起容器后 `docker compose exec ethan ethan skill add legal`），Web 端模式下拉切到「⚖️ 法律专家」即生效。

### 方式 4：从源码（开发）

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
uv sync                              # Python 依赖
cd web && npm install && cd ..       # Web UI 依赖（可选）
```

可选 —— 语义路由器（让技能匹配更聪明，新手可跳过）：

```bash
uv sync --extra embedding            # 或：pip install 'ethan-agent[embedding]'
ethan router pull                    # 约 24MB 模型，仅首次
ethan router status                  # 显示「✓ 路由器就绪」即可
```

启动：

```bash
ethan                                # 交互式 REPL（若 serve 已启动则自动打开 Web UI）
ethan serve                          # HTTP API + 内嵌 Web UI，监听 8900
ethan web                           # 在浏览器打开 Web UI
cd web && npm run dev               # http://localhost:3000（开发模式，API 仍在 8900）
```

可选扩展：

- **浏览器扩展** —— 从任意渠道操作真实 Chrome：把 [`browser-extension/`](./browser-extension) 加载到 Chrome，指向 `ws://localhost:8900/ws/browser`
- **桌面控制**（macOS）—— `ethan server install` 把 `cua-driver` 注册为 launchd 服务，或 `pip install 'ethan-agent[computer]'` 装 Python SDK
- **Android app** —— `cd app/android && ./gradlew assembleDebug`（需 Android SDK 35 + JDK 17+）；见 [`app/android/PRD.md`](./app/android/PRD.md)
- **macOS 自启** —— `./deploy/install.sh` 安装 launchd plist

---

## 配置模型

部署完后，至少配一个模型 provider：

```bash
# Anthropic Claude（推荐——支持 Prompt Caching）
ethan provider set anthropic --api-key sk-ant-xxx

# 或者任意 OpenAI 兼容 API（Gemini / OpenRouter / DeepSeek / Ollama 等）
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
ethan model default <model-id>

# 或者智谱 GLM（内置预设——自动填好 base_url/type/抗缓存 + 注册 glm-5.2 等）
ethan provider set glm --api-key <你的-GLM-key>
ethan model default glm-5.2

# 列出所有内置预设
ethan provider presets
```

Docker 用户：跳过 CLI，直接在 `.env` 里设 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `AGENT_DEFAULT_MODEL`。

> ⚠️ **已经在运行？** 改完 `ethan provider set` / `ethan model default` 后要**重启** `ethan serve` / 桌面端 / `ethan web`。运行中的服务把配置缓存在内存里，不重启不会读 `~/.ethan/config.yaml` 的新改动。

然后开始聊天：

```bash
ethan            # 交互式 REPL
ethan -p "..."   # 单轮对话
ethan -m MODEL   # 指定模型
ethan -r last    # 恢复上次会话
```

Web UI token：

```bash
ethan web token          # 查看当前 token
ethan web token --rotate # 重新生成 token
```

---

## 飞书（Lark）接入

Ethan 通过 **WebSocket 长连接**接入飞书——无需公网 IP、无需配置 Webhook URL。`ethan serve` 启动时会为每个 EventKey 各起一个 `lark-cli event consume <EventKey>` 子进程。

### 配置步骤

1. 到 [open.feishu.cn](https://open.feishu.cn) 创建飞书应用，拿到 `app_id` 和 `app_secret`。
2. 启用 **机器人** 能力并订阅事件（至少 `im.message.receive_v1`；可选：消息已读回执、表情反应、`card.action.trigger` 卡片按钮回调）。
3. 授权用户身份操作（如 `--as user` 读群背景上下文）：在宿主机上跑一次 `lark-cli auth login --domain im`。用户 token 过期时，机器人会向该会话发红色引导卡片，提示重新执行该命令。
4. 把凭证加到 `~/.ethan/config.yaml`：

```yaml
lark:
  app_id: "cli_xxxxxxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

5. 重启 `ethan serve`。每个 EventKey 各自一个子进程，独立断线重连。

### 你能拿到什么

- Markdown post 气泡 + interactive 卡片（流式 `patch` 更新）
- 多事件订阅（消息 / 已读回执 / 表情 / 卡片按钮回调）
- 收到消息即加 `THINKING_FACE` 表情反馈；自然语言中止（"停" / "取消" / "stop"）；`/` 斜杠命令（`/new` / `/stop` / `/help` 等）
- 用户身份调用失败时自动发授权引导卡片（99991663 / 99991661 / `need_user_authorization`）
- 按 chat 隔离的会话；飞书会话在 Web UI 可见，标题前缀 `lark:<chat_id>:`

完整事件流、卡片渲染细节、表格渲染 quirks 见 [docs/interface.md](docs/interface.md)。

---

## 内置技能

[`ethan/defaults/skills/`](./ethan/defaults/skills/) 下的所有技能会在首次运行时自动复制到 `~/.ethan/skills/`，升级时同步 `SKILL.md` 和 `references/`（你自己的文件绝不动）。第三方技能用 `ethan skill add <name>` 安装。

### 浏览器与桌面控制

| 技能 | 说明 |
|------|------|
| [use-browser](./ethan/defaults/skills/use-browser/SKILL.md) | 主浏览器技能——通过 Ethan Browser 扩展操作真实 Chrome（复用登录 cookie） |
| [agent-browser](./ethan/defaults/skills/agent-browser/SKILL.md) | 兜底：内置独立 Chrome + Rust CLI，AX 快照省 token |
| [dev-browser](./ethan/defaults/skills/dev-browser/SKILL.md) | 沙箱 JS + 完整 Playwright API，适合复杂多步流程 |
| [computer-use](./ethan/defaults/skills/computer-use/SKILL.md) | 通过 `cua-driver` 控制 macOS 桌面（截图 / 点击 / 输入 / 拖拽 / 启动应用） |
| [macos-automation](./ethan/defaults/skills/macos-automation/SKILL.md) | 通过 `osascript` 自动化 macOS 应用（滴答清单 / 提醒事项 / 日历 / 备忘录） |

### 飞书 / Lark

| 技能 | 说明 |
|------|------|
| [lark-im](./ethan/defaults/skills/lark-im/SKILL.md) | 发送 / 回复 / 搜索消息，管理群聊与成员，表情反应，交互卡片 |
| [lark-doc](./ethan/defaults/skills/lark-doc/SKILL.md) | 读取和编辑飞书云文档 Docx / Wiki |
| [lark-task](./ethan/defaults/skills/lark-task/SKILL.md) | 创建 / 分配 / 跟踪飞书任务与清单 |
| [lark-shared](./ethan/defaults/skills/lark-shared/SKILL.md) | lark-cli 配置、auth login、身份切换、scope 错误处理 |
| [feishu-writer](./ethan/defaults/skills/feishu-writer/SKILL.md) | 长文飞书文档生成，富文本写入与 Mermaid |
| [channels](./ethan/defaults/skills/channels/SKILL.md) | 消息渠道配置（当前飞书 WebSocket；后续接入微信 / Telegram） |

### 笔记与知识

| 技能 | 说明 |
|------|------|
| [deepwiki](./ethan/defaults/skills/deepwiki/SKILL.md) | 通过 DeepWiki 查询任意 GitHub 仓库的文档与架构分析 |
| [obsidian](./ethan/defaults/skills/obsidian/SKILL.md) | 读取 / 搜索 / 创建 / 编辑 Obsidian vault 笔记 |
| [flomo](./ethan/defaults/skills/flomo/SKILL.md) | 读取 / 搜索 / 写入 flomo（浮墨）短笔记 |
| [getnote](./ethan/defaults/skills/getnote/SKILL.md) | 得到大脑（Get笔记）——保存 / 搜索个人笔记和知识库 |
| [wechat-reading](./ethan/defaults/skills/wechat-reading/SKILL.md) | 微信读书——搜书、管理书架、查看划线 |
| [notebooklm](./ethan/defaults/skills/notebooklm/SKILL.md) | 查询 Google NotebookLM（带源文档引用） |
| [llm-wiki](./ethan/defaults/skills/llm-wiki/SKILL.md) | Karpathy LLM Wiki——构建 / 查询互联 markdown 知识库 |

### 搜索与信息

| 技能 | 说明 |
|------|------|
| [arxiv](./ethan/defaults/skills/arxiv/SKILL.md) | 按关键词 / 作者 / 类别 / ID 搜索 arXiv 论文 |
| [url-process](./ethan/defaults/skills/url-process/SKILL.md) | 链接处理入口——自动识别平台并选最快路径 |
| [blogwatcher](./ethan/defaults/skills/blogwatcher/SKILL.md) | 监控博客与 RSS / Atom feeds |
| [rss-briefing](./ethan/defaults/skills/rss-briefing/SKILL.md) | 每日 RSS 简报，飞书排版适配 |

### 编码与研究

| 技能 | 说明 |
|------|------|
| [code-review](./ethan/defaults/skills/code-review/SKILL.md) | 审查 diff —— P0 必修 / P1 建议 / P2 一句带过；行内评论 |
| [vercel-deploy](./ethan/defaults/skills/vercel-deploy/SKILL.md) | 部署静态站点 / Web 应用到 Vercel |
| [research-paper-writing](./ethan/defaults/skills/research-paper-writing/SKILL.md) | 写 ML 论文（NeurIPS / ICML / ICLR）——从设计到提交 |
| [paper-analysis](./ethan/defaults/skills/paper-analysis/SKILL.md) | 学术论文 Map-Reduce 深度精读（PDF / arXiv ID / 本地文件） |

### 生活与效率

| 技能 | 说明 |
|------|------|
| [amap-lbs](./ethan/defaults/skills/amap-lbs/SKILL.md) | 高德地图 POI 搜索、路径规划、旅游规划、热力图 |
| [didi-ride](./ethan/defaults/skills/didi-ride/SKILL.md) | 在飞书会话里叫滴滴 |
| [jd-shopping](./ethan/defaults/skills/jd-shopping/SKILL.md) | 京东订单导出、商品搜索、购物车管理 |
| [travel-query](./ethan/defaults/skills/travel-query/SKILL.md) | 12306 火车 / 高铁时刻查询 |
| [finance-query](./ethan/defaults/skills/finance-query/SKILL.md) | A 股 / 港股 / 美股行情、K 线、PE/PB、财报 |
| [xiaohongshu](./ethan/defaults/skills/xiaohongshu/SKILL.md) | 小红书自动化——搜索 / 发布 / 互动 |
| [gws-gmail](./ethan/defaults/skills/gws-gmail/SKILL.md) | 通过 gws CLI 操作 Gmail——发 / 读 / 回复 / 转发 / 整理 |

### 图像与 UI

| 技能 | 说明 |
|------|------|
| [ui-card](./ethan/defaults/skills/ui-card/SKILL.md) | 渲染结构化 UI 卡片（对比 / 排行 / 统计 / 时间轴） |
| [image-split](./ethan/defaults/skills/image-split/SKILL.md) | 长截图按网格切割（智能在空白间隙处分割） |
| [excalidraw](./ethan/defaults/skills/excalidraw/SKILL.md) | 生成可编辑的 Excalidraw 图（Obsidian 优先） |
| [upload-cdn](./ethan/defaults/skills/upload-cdn/SKILL.md) | 上传本地文件到 S3 兼容存储，返回公开 URL |

### 陪伴与模式

| 技能 | 说明 |
|------|------|
| [companion-listen](./ethan/defaults/skills/companion-listen/SKILL.md) | 苏念——熟读《臣服实验》的年轻温柔女性陪伴者 |
| [task-strategy](./ethan/defaults/skills/task-strategy/SKILL.md) | 工具不可用 / 被拒绝 / 超时时的通用降级策略 |

### 技能自管理

| 技能 | 说明 |
|------|------|
| [skill-creator](./ethan/defaults/skills/skill-creator/SKILL.md) | 起草 SKILL.md、设计触发词、组织 references / scripts |
| [skills-manager](./ethan/defaults/skills/skills-manager/SKILL.md) | 通过 `npx skills` 搜索 / 安装 / 更新 / 卸载技能 |

### 可选 / 外部

| 技能 | 说明 |
|------|------|
| [legal-assistant](https://github.com/llm011/ethan-legal-skill) | 法律专家模式——案件研判、诉讼分析、合同审查、知产、法律检索（`ethan skill add legal`） |
| [eigenflux](./ethan/defaults/skills/eigenflux/SKILL.md) | AI 信号广播网络，跨 Agent 协作（隐私优先） |

---

## 特性

### 记忆体系

- **结构化长期记忆**（`memory.db`，用户事实的唯一事实源）：每 5 轮对话提取带原文 quote 佐证的候选（quote 必须是用户消息精确子串），确定性准入——explicit 立即生效，observed 需 ≥2 个独立 session 复证才晋升。64 个维度 × 7 大类（个人信息/偏好/活动/决定/关系/方法论/陪伴），支持 TTL 过期、supersede 纠正链、遗忘脱敏。
- **语义召回与去重**：FTS5 + BGE 向量双通道（RRF 融合）供给唯一的 `<memory_context>` 注入块；准入时向量近邻配对，按确定性规则 merge/supersede（"住在深圳"和"家在深圳南山"不会各存一条）。
- **维度注册表**：提取 prompt 的维度说明与校验白名单由同一份声明式注册表生成——扩展维度不再需要手写 prompt。
- 热区/温区滑动窗口维持长对话上下文（REPL），廉价模型自动压缩较早内容。
- **行为准则 Procedures**：从用户纠正中自动学习，每次对话加载（`playbook.json`）。
- **用户画像 Profile**：叙事型文档，按章节存储个人语言、目标、约定等（`user_profile.md`）；含「基础特征」「心理与情绪」等章节。
- **主动写记忆**：Agent 在对话中识别到可记忆信息时调用 `memory_write`——写入走同一条候选→准入管道（同一个库、同样的证据语义）。

### 做梦——夜间记忆沉淀（"做梦" / dream）

- 每晚 0 点跑一次统一沉淀（`run_nightly_consolidation`）：重提取当日 session、跨 session 复评 pending 候选、过期清理、分域日摘要、重建记忆向量索引——然后"做梦"：把白天跨 session 的信号（重复需求 ≥3 次、错误、成功路径）精炼成永久洞察，与刚准入的记忆做 sqlite-vec 去重。
- 苏念（companion）情感记忆隔离在苏念模式（独立域，其他模式绝不召回）；诊断/临床标签用词表硬拒绝。
- **反写机制**：洞察按类型分流——repetition/error 反写为结构化候选走准入管道，success_path 进 `playbook.json`，无需单独的读取链路。
- **fact_sync 镜像**：每次做梦前，把 active 记忆/playbook 内容全量镜像到向量库（type=`fact_sync`），让 insight 的 L2 去重天然覆盖已有记忆；镜像每次全量重建。
- **永久保留**：洞察不会被自动删除；`last_accessed` 仅作活跃度观察，不作为淘汰依据（memory.db 体量天然可控，每条洞察约 15KB）。
- **sessions.db 轮转**：完整消息历史增长快，sessions.db 超 10 MB 时用 `VACUUM INTO` 原子快照到 `~/.ethan/archive/sessions.{start}~{end}.db`（文件名带日期跨度），保持 active db 轻量，旧会话仍可按日期查归档。

### 陪伴倾听模式 · 苏念（《臣服实验》心理咨询师）

- 可加载插件：在聊天界面一键切换「苏念 · 陪伴倾听」，从工作助手变成一位年轻温柔的女性陪伴者，熟读《臣服实验》、深谙道法自然。
- 该模式下 Agent 先赞许安抚、深度倾听、陪伴而非急于解决问题——说话像真人、温柔口语，拒绝 AI 腔。
- 陪伴模式下，后台自动把「心理与情绪」（情绪/压力源/什么能安抚你/内心感受）整理进画像；基础特征由你在设置页「我的画像」里填写。

### 法律专家模式 · legal-assistant（按需安装）

- 切换到「法律专家」模式后，单个 `legal-assistant` 技能即覆盖案件研判、诉讼分析、合同审查、法律文书/方案生成、商标专利知产、案件流程管理、法律检索与可视化——按「任务动词 + 业务条线」路由到对应 playbook，不堆几十个子技能。
- **零污染**：法律技能用 `modes: [法律]` 标记，仅在法律模式生效；正常工作模式下完全不进上下文。
- **自动安装（按需）**：首次切到法律模式若未安装，Agent 会**自动从仓库拉取并安装** `legal-assistant`（会先告知「正在安装」，不静默联网；装失败则提示手动 `ethan skill add legal`）。法律内容不随主仓库分发，遵循上游 CC-BY-NC 非商用许可。
- **手动安装**：命令行直接 `ethan skill add legal` 一键装（= `llm011/ethan-legal-skill/skills/legal-assistant`）。
- **`/mode` 切换**：CLI（REPL）和飞书等渠道均可用 `/mode 法律` 切入、`/mode default` 切回默认；模式名无法识别时保持当前模式不变。模式持久化在会话上，恢复会话自动还原。

### Skill 技能系统

- 触发词匹配，自动注入 system prompt 引导行为。
- 可选语义路由器（BGE INT8 + LR 头）在关键词之上补召回，换个说法也能命中（`pip install 'ethan-agent[embedding]'`，不装则纯关键词，详见 [部署方式](#方式-4从源码开发)）。
- `fast_path: true` 触发后走毫秒级快速路径，适合全屋智能等高频控制。
- `channels: [lark, web]` 按渠道过滤，Skill 只在指定场景下生效。
- `modes: [法律]` 按对话模式过滤，Skill 只在指定模式下生效（空 = 所有模式）。
- Skill 命中统计与纠正收集，积累后 Heartbeat 自动用廉价模型更新 Skill 内容。
- Agent 可在对话中即时创建新 Skill（`skill_create` 工具）。

### 三档智能路由

- **fast**：短命令 + 关键词匹配 → 极简 prompt + 仅限 fast_path 工具 + 2 次迭代。
- **medium**：中等消息 → 完整 prompt + 全部工具 + 4 次迭代。
- **full**：复杂任务 → 完整 prompt + 全部工具 + 10 次迭代。

### Loop 控制

- **卡死检测**：连续 3 轮调用相同工具+参数（或连续 2 轮同一报错）时，注入强制反思提示（要求 `<diagnosis>` 诊断并换路），而不是一路空转到迭代上限。
- **优雅收尾**：反思 2 次仍卡住、或跑满迭代上限时，最后一轮禁用工具，让模型生成「已完成 / 卡点 / 需你提供什么」的收尾报告——不再返回 `[max tool iterations reached]` 死字符串。

### 定时任务与后台任务

- 对话中创建 cron 或 interval 任务，SQLite 持久化，重启自动恢复。
- `heartbeat.md`：写入自然语言任务，系统定期自动执行。
- **后台任务**：把耗时长任务丢到后台独立会话异步执行，不阻塞当前对话；完成后结果回灌（飞书推回原会话，web 在侧边栏会话浮现）。在 `/background-tasks` 页查看/终止，侧边栏带运行中数量角标。

### 工具系统

- Shell 执行、Web 搜索（默认 DuckDuckGo；可配置切换 Tavily 或自建 SearXNG，见 [`deploy/docker-compose.searxng.yml`](./deploy/docker-compose.searxng.yml)）、Web 抓取、文件读写、知识库检索、图表、浏览器、桌面控制、ACP 委派。
- 敏感/副作用操作（shell、写文件、读密钥）执行前请求授权；Web 弹授权卡片、REPL 走 y/N，同一会话授权过一次后不再重复询问。
- 工具结果超 4000 字自动用廉价模型压缩摘要。
- 同参数重复调用自动命中轮次内缓存，不重复执行。
- `no_compress = True` 适用于输出含需原样回传的 ID/ref/结构化 JSON 的工具。

### Prompt Caching

- system prompt 分稳定层/动态层，稳定层缓存 5 分钟，token 成本降至 0.1×（Anthropic）。

### 多渠道

- CLI REPL、Web UI（Next.js）、**桌面端 App**（Tauri，macOS + Windows）、**Android App**（Kotlin/Compose）、飞书/Lark（WebSocket 长连接，无需公网 IP）。
- **飞书鉴权自动引导**：当依赖用户身份的调用（如 `--as user` 读群背景上下文）遇到鉴权类错误（99991663 / 99991661 / `need_user_authorization`）时，机器人会向该会话发一张红色引导卡片，指引用户执行 `lark-cli auth login --domain im` 重新授权。同一群 5 分钟内只发一次；网络/参数/not-found 等非鉴权错误不触发。
- **飞书多事件订阅 + 卡片按钮回调**：每个 EventKey（收消息 / 已读回执 / reaction / `card.action.trigger`）各跑一个 `lark-cli event consume` 子进程，独立断线重连；交互卡片按钮点击通过 `_handle_card_action` 回路，支持按钮驱动的工作流。
- **OpenAI 兼容 Completions API**（`/v1/chat/completions`）+ 按用户分配 API key——可直接当 OpenAI API 的替代品使用。

### 浏览器控制（真实 Chrome）

- 在任意渠道（Web / 飞书 / CLI）对话中，操作 ethan 所在机器上的真实 Chrome——安装内置的 [`browser-extension`](./browser-extension)，填上 ethan 的 WebSocket 地址，agent 即获得 `browser_session` / `browser_tab` / `browser_page` 三个工具。
- agent-browser 风格：可访问性树 snapshot + ref map，click/fill/type/press/select/scroll/hover、截图、键鼠事件、页面 `eval`，全部经 Chrome DevTools Protocol 执行。
- session 绑定对话（按对话隔离）；同一 session 内页面操作串行、不同 session 并行；闲置 30 分钟后 release（保留用户 tab）。
- 会话级一次性授权：本对话第一次调用 browser 工具询问一次，批准后该对话所有操作（含 `eval`）放行。
- 传输仅用 WebSocket（扩展 → ethan），无需 native messaging host；详见 [docs/browser-control-plan.md](docs/browser-control-plan.md)。

### 桌面控制（macOS，基于 cua-driver）

- 在任意渠道（Web / 飞书 / CLI）控制本机 macOS 桌面——截图、点击、输入、拖拽、滚动、启动应用、打开 URL。
- 基于 [trycua/cua](https://github.com/trycua/cua)；连接本地后台服务 `cua-driver`（监听 `localhost:8000`），无需虚拟机。
- 截图结果直接传给视觉模型，agent 看到屏幕后决定下一步操作。
- `ethan server install` 自动安装并注册 `cua-driver` 为 launchd 服务；也可手动安装。
- 可选 Python SDK：`pip install 'ethan-agent[computer]'`（cua-computer）；未安装时工具自动不可见，不影响其他功能。

### Coding Agent 集成（ACP）

- `delegate_coding` / `ethan code "query"` 把复杂编码任务委派给 **Claude Code / OpenCode / Codex**，三套后端都走 JSON 事件流 + 会话续接。
- **沉浸式工具模式**：对话 mode 可切到 Codex / Claude Code / OpenCode；切入后整条会话每句话都直接续接该工具（同一工具 session、按会话隔离工作目录）。
- **镜像会话**：每次 `delegate()` 落成一条真正的 Ethan 会话（`source` 用真实工具名 codex/claude/opencode），记录下发的 query + Coding Agent 回复 + 步骤，并注册为 RunManager run，委派过程可经 SSE 实时观看。
- 工具调用解析为可折叠 sub_steps，Web UI 时间轴展示、最终结果高亮。详见 [docs/acp.md](docs/acp.md)。

### UI 卡片与交互图表

- **`ui_card` 工具**：把结构化信息渲染成卡片，比纯文字更直观。高频类型（对比 / 排行 / 统计 / 时间轴）走后端固定模板——模型只填结构化数据，样式稳定一致；自定义卡片仍可手写。渲染按渠道分叉、共享同一套结构化 `card` 数据：Web 端用 `@a2ui/react` 渲染 [A2UI](https://a2ui.org/)、REPL 走文本降级、飞书则渲染成原生 interactive 卡片。
- **交互式图表**（`generate_chart`）：Chart.js bar / line / pie / doughnut / horizontalBar / radar，遵循 [MCP Apps](https://modelcontextprotocol.io/) UI 资源约定（SEP-1865）。工具结果只携带 `{uri, data}`——Web 前端按 URI 拉取模板一次并缓存，在 sandbox iframe 中渲染，再通过 `postMessage` 把图表数据打进去。同时保留 [quickchart.io](https://quickchart.io/) 的 PNG 作为非 Web 渠道的降级。

### 多用户

- 多个隔离用户共享一个实例。每个用户有独立的记忆（结构化记忆 / procedures / sessions）、技能和知识库，互不可见。System prompt 和 provider 配置全局共享。
- 在 `config.yaml` 中预置用户（每个用户绑定 `web_token` 用于浏览器登录，和 `api_keys` 用于 `/v1/chat/completions` API 调用——两者都解析到同一个 `user_id`）：

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

若 `users` 为空（或缺失），Ethan 会自动生成一个 `admin` 用户，其 `web_token` 复用 `network.auth_token`——现有单用户部署零配置即可升级。首次启动时，现有全局数据会迁移到 admin 用户目录（原文件保留作备份，迁移幂等）。

---

## 架构

```
ethan/
├── core/
│   ├── agent.py               # ReAct loop，三档路由（fast/medium/full）
│   ├── config.py              # YAML 配置（~/.ethan/config.yaml）
│   └── heartbeat.py           # 心跳系统，定期维护任务
├── providers/
│   ├── base.py                # 统一接口（Message, ToolCall, BaseProvider）
│   ├── anthropic.py           # Claude 原生协议 + Prompt Caching
│   ├── openai_compat.py       # OpenAI 兼容协议
│   └── manager.py             # 按 model id 路由到 provider
├── memory/
│   ├── session.py             # 会话持久化（SQLite）
│   ├── working.py             # 三层滑动窗口记忆
│   ├── store.py               # 结构化记忆存储（memories/evidence/candidates/jobs/FTS）
│   ├── extractors.py          # LLM 候选提取（quote 溯源）
│   ├── admission.py           # 确定性准入 + 语义配对
│   ├── dimensions.py          # 维度注册表（白名单 + prompt 生成）
│   ├── recall.py              # 混合召回（FTS + 向量,RRF）
│   ├── memory_vectors.py      # memories 的 BGE 向量索引
│   ├── nightly_consolidation.py # 夜间统一沉淀（结构化 + 做梦）
│   ├── procedures.py          # 行为准则（从纠正中学习）
│   └── consolidator.py        # 廉价模型压缩器
├── skills/
│   ├── loader.py              # 加载（目录格式 + 旧格式兼容）
│   ├── registry.py            # 匹配（含 channel 过滤）+ stats
│   ├── stats.py               # 命中统计 + 纠正记录
│   ├── updater.py             # 用廉价模型自动更新 Skill 内容
│   └── generator.py           # 从会话自动生成新 Skill
├── tools/
│   ├── base.py                # BaseTool 抽象类
│   ├── registry.py            # 注册表 + 并发执行 + 轮次缓存
│   ├── result_compressor.py   # 超长结果摘要压缩
│   └── builtin/
│       ├── shell.py           # 执行 shell 命令
│       ├── web_search.py      # DuckDuckGo / Tavily / SearXNG 搜索
│       ├── web.py             # 抓取网页正文
│       ├── file.py            # 文件读/写/列
│       ├── memory_write.py    # 主动写 Facts
│       ├── procedure_write.py # 主动写行为准则
│       ├── profile_update.py  # 更新用户画像
│       ├── skill_create.py    # 对话中创建 Skill
│       ├── chart.py           # 交互式 Chart.js 图表（MCP Apps）
│       ├── ui_card.py         # 结构化 A2UI 卡片
│       ├── acp.py             # 委派 Claude Code / Codex / OpenCode
│       ├── browser.py         # 真实 Chrome 控制
│       ├── computer_use.py    # macOS 桌面控制
│       └── lark_tools.py     # 飞书 CLI 封装（日历 / 群消息 / 消息发送）
├── scheduler/
│   └── cron.py                # APScheduler + SQLite 持久化
└── interface/
    ├── cli.py                 # Typer CLI 入口
    ├── repl.py                # 交互式 REPL（prompt_toolkit）
    ├── api.py                 # FastAPI + SSE 流式
    ├── lark_events.py         # 飞书 WebSocket
    └── commands/              # 子命令（model, provider, session, skill, schedule）
```

---

## 记忆体系

结构化记忆管道（提取 → 准入 → 召回 → 夜间沉淀）+ 若干卫星存储：

| 组件 | 内容 | 存储 |
|----|------|------|
| 结构化记忆 | 带原文佐证、确定性准入的用户事实 | `~/.ethan/memory/memory.db` |
| 洞察（做梦） | 跨 session 模式（重复需求/错误/成功路径） | `~/.ethan/memory/memory.db`（向量库） |
| 行为准则 | 从用户纠正中学习的规则 | `~/.ethan/memory/playbook.json` |
| 用户画像 | 叙事型个人信息（目标、短语、约定） | `~/.ethan/memory/user_profile.md` |
| 热区/温区 | 最近 N 轮 + 滚动摘要（会话内压缩） | 内存 |

提取每 5 轮一次（主模型）；会话内压缩**批量触发**（而非逐轮），使用自动推断的廉价模型（Claude 用户用 Haiku，Gemini 用户用 Flash Lite）。

Agent 通过 `memory_write`、`procedure_write`、`profile_update` 工具在对话中主动写入各层，无需等待下一个压缩周期。

完整架构见 [docs/memory.md](docs/memory.md)。

---

## Skill 技能系统

Skill 从 `~/.ethan/skills/` 加载。首次运行时，[`ethan/defaults/skills/`](./ethan/defaults/skills/) 下的所有技能会自动复制到该目录；升级时同步 `SKILL.md` 和 `references/`（你自己的文件绝不动）。

支持目录格式（`<name>/SKILL.md` + `references/` 子目录）和旧版单文件 `.md` 格式。命中目录格式 skill 时，注入的 context 会附上 `references/*.md` 的文件名 + 一行摘要清单，让模型知道有哪些细节文档可查——再用 `skill_read(name=..., file="references/<name>.md")` 按需拉具体内容（pull-based，不全量灌入正文）。

```markdown
---
name: deploy-checklist
trigger: deploy|ship|发布
description: 发布前检查清单
fast_path: true       # 命中 trigger 时走 fast 轨
channels:             # 空 = 所有渠道；列表 = 限制渠道
  - web
modes:                # 空 = 所有模式；列表 = 限制模式
  - 法律
version: "1.0"
---

发布前步骤：
1. 运行测试
2. 检查未提交的改动
3. ...
```

用户消息匹配到 skill 的 `trigger` 时，skill 内容会被注入 system prompt。开箱自带的技能见上方 [内置技能](#内置技能) 表。

Skill 会累积命中次数和用户纠正记录。当纠正达到阈值（默认 2 条），Heartbeat 任务用廉价模型将纠正合并进 Skill 文件。

第三方技能用 `ethan skill add <name>` 安装（例如 `ethan skill add legal`）。

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
    no_compress = False # 若输出含需原样回传的 ID/ref/结构化数据，置 True

    parameters = {"type": "object", "properties": {...}, "required": [...]}

    async def run(self, **kwargs) -> str:
        return "结果"
```

在 `cli.py` 注册后，LLM 会在合适时机自动调用。

> **`no_compress`**：工具输出超过 4000 字会先被廉价模型压成摘要再喂给主模型。输出是给模型「读」的散文（网页、日志）就保持关闭；若输出里含模型需要**原样回传**的数据——ID、ref、路径、结构化 JSON——则置 `True`，否则摘要会丢掉这些 token，模型拿到结果却无法操作。

### 内置工具

| 工具 | 说明 |
|------|------|
| `shell` | 执行 shell 命令 |
| `web_search` | DuckDuckGo（默认）/ Tavily / 自建 SearXNG |
| `web` | 抓取并提取网页正文 |
| `file` | 文件读 / 写 / 列 |
| `find_tools` | `rg`（ripgrep）和 `fd` 代码 / 文件搜索 |
| `knowledge` | 本地 markdown 知识库 + sqlite-vec 语义检索 |
| `schedule` | cron / interval 任务管理 |
| `memory_write` | 主动写事实（走候选→准入管道） |
| `procedure_write` | 主动写行为准则 |
| `profile_update` | 更新用户画像 |
| `skill_create` / `skill_read` | 对话中创建 / 读取技能 |
| `install_skill` | 按需安装第三方技能 |
| `secrets` | 从 `~/.ethan/.secrets/` 读密钥 |
| `config` | 读取 / 编辑运行时配置 |
| `acp` | 委派 Claude Code / Codex / OpenCode |
| `browser` | 真实 Chrome 控制（`browser_session` / `browser_tab` / `browser_page`） |
| `computer_use` | 通过 cua-driver 控制 macOS 桌面 |
| `ui_card` | 结构化 A2UI 卡片 |
| `chart` | 交互式 Chart.js 图表（MCP Apps / SEP-1865） |
| `image_search` | 图片搜索 |
| `lark_tools` | 飞书 CLI 封装（日历 / 群消息 / 消息发送） |
| `background_task` | 异步长任务执行 |
| `weather` | 天气查询 |

### 交互式图表（MCP Apps / SEP-1865）

`generate_chart` 工具在 Web 端渲染**可交互**的 Chart.js 图表（bar / line / pie / doughnut / horizontalBar / radar），遵循 [MCP Apps](https://modelcontextprotocol.io/) 的 UI 资源约定（SEP-1865）：

- UI 模板注册为 `ui://` 资源（`ethan/tools/ui_resources.py`），通过 `GET /api/ui-resources`（列出）和 `GET /api/ui-resources/read?uri=…`（读取 HTML + `_meta` CSP）对外暴露。
- 工具结果只携带 `{uri, data}`——**不内联 HTML**。Web 前端（即 MCP host）按 URI 拉取模板一次并缓存，在 sandbox iframe 中渲染，再通过 `postMessage`（JSON-RPC `init`）把图表数据打进去。模板与数据分离，正是 MCP Apps 的核心。
- 同时保留 [quickchart.io](https://quickchart.io/) 的 PNG 作为降级，非 Web 渠道（如飞书）拿到静态图片。

图表持久化在 assistant 消息上（`mcp_apps` 列），刷新页面后仍能重新渲染。

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
ethan web                          在浏览器打开 Web UI
ethan web token                    查看 / 轮换 Web 登录 token

ethan model list|add|remove|default
ethan provider list|set|presets
ethan session list|show|delete
ethan skill list|show|add|create
ethan schedule list|remove|pause|resume
ethan router pull|status           # 可选语义路由器
ethan server install              # 安装 cua-driver / launchd 服务
ethan code "query"                # ACP 委派 Coding Agent
```

---

## HTTP API

```bash
GET  /health                    # 健康检查
GET  /models                    # 可用模型列表
POST /chat                      # 对话（stream: true 开启 SSE 流式）
GET  /sessions                  # 会话列表
GET  /sessions/{id}             # 会话详情（含消息历史）
GET  /memory/facts              # 记忆列表（兼容旧格式的视图）
GET  /memory/records            # 结构化记忆（可按 type/domain/status 过滤）
GET  /memory/records/{id}       # 记忆详情 + 证据链
GET  /skills                    # Skill 列表
POST /skills                    # 创建 Skill
POST /skills/evolve             # 手动触发 Skill 自动更新
GET  /schedule                  # 定时任务列表
GET  /system-prompt-preview     # 当前 system prompt 预览
GET  /channels                  # 渠道列表
GET  /knowledge/search          # 语义检索
GET  /ui-resources              # MCP Apps UI 资源（SEP-1865）：列出
GET  /ui-resources/read?uri=    # MCP Apps UI 资源：读取 HTML + _meta
POST /v1/chat/completions       # OpenAI 兼容 API（按用户分配 API key）
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

lark:
  app_id: "cli_xxxxxxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

users:
  - id: admin
    name: Admin
    web_token: admin_pass
    api_keys: [sk-ethan-admin-key]
    is_admin: true

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

`.env` 中的环境变量会覆盖 config 文件中的值（适合管理密钥）。Docker 模板见 [`deploy/.env.example`](./deploy/.env.example)。

### 配置目录结构

```
~/.ethan/
├── config.yaml          # 主配置（Provider、模型、路由、飞书、用户）
├── system/
│   ├── identity.md      # Agent 身份（名字、角色）
│   ├── soul.md          # 行为原则（主动写记忆的指令在这里）
│   └── heartbeat.md     # 心跳任务（自然语言定义）
├── memory/
│   ├── memory.db        # 结构化记忆 + 证据链 + 洞察 + 向量索引
│   ├── playbook.json  # 行为准则
│   └── user_profile.md  # 用户画像（叙事型）
├── skills/              # 用户自定义 + 自动复制的内置技能
│   └── <name>/
│       └── SKILL.md
├── .secrets/             # 技能密钥文件（如飞书应用凭证）
└── sessions.db          # 会话历史（SQLite）
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
- [x] 用户画像 UserProfile（叙事型，五章节文档）
- [x] 主动写记忆（`memory_write`、`procedure_write`、`profile_update`、`skill_create`）
- [x] Memory context 隔离（防污染标签）

**Skill 系统**
- [x] 双来源加载（内置 + 用户自定义）+ 渠道过滤（channels 字段）
- [x] fast_path 标记、Skill 命中统计、纠正收集、自动更新（Updater）
- [x] 会话结束后后台自动生成 Skill（Hermes 风格）
- [x] 可选语义路由器（BGE INT8 + LR 头，macro F1 0.851）在关键词之上补召回；缺失时静默退回关键词。同一套 `[embedding]` 依赖也驱动 memory.db 的语义去重
- [x] 开箱自带 40+ 内置技能（见 [内置技能](#内置技能)）

**工具**
- [x] shell、web_search、web_fetch、file_read/write/list、rg、fd
- [x] 知识库（sqlite-vec 语义检索）、定时任务管理、ACP 委派 Claude Code / Codex / OpenCode
- [x] `ui_card`（A2UI 结构化卡片）、`generate_chart`（交互式 Chart.js via MCP Apps）
- [x] 浏览器控制（真实 Chrome via 扩展）+ 桌面控制（macOS via cua-driver）

**定时任务**
- [x] cron + interval，SQLite 持久化，重启自动恢复
- [x] heartbeat.md：自然语言定义周期任务，系统自动执行
- [x] 后台任务，按 chat 异步执行

**渠道与 API**
- [x] Web UI（Next.js）：对话时间轴、记忆管理、技能、定时、知识库、设置
- [x] 桌面端 App（Tauri）：macOS + Windows，原生窗口内嵌 Web UI
- [x] Android App（Kotlin/Compose）：移动端客户端，聊天 SSE、会话、记忆、设置等
- [x] 飞书 WebSocket（无需公网 IP）+ 多事件订阅 + 卡片按钮回调
- [x] OpenAI 兼容 Completions API（`/v1/chat/completions`）+ 按用户分配 API key
- [x] Docker 部署 + macOS launchd 自启
- [x] 多用户隔离（按用户隔离记忆 / 技能 / 知识库）

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
- [x] **ACP 持续对话优化**：`delegate_coding` 按「Coding Agent × 工作目录」持久化 session_id。三套后端（Claude Code / OpenCode / Codex）现都走 JSON 事件流 + 会话续接，解析为 sub_steps，Web UI 时间轴折叠展示、最终结果高亮。
- [x] **镜像会话**：每次 `delegate()` 落成一条真正的 Ethan 会话，记录下发的 query + Coding Agent 回复 + 步骤
- [x] **沉浸式工具模式**：对话 mode 可切到 Codex / Claude Code / OpenCode
- [ ] **MCP client 完善**：连接外部 MCP server，自动注册工具

**长期**
- [ ] **域隔离（Space）**：生活 / 工作 / 项目记忆独立，防止混杂
- [ ] **异步中断**：长任务执行中感知新消息，在工具调用间隙响应
- [ ] **Obsidian 接入**：读写 Obsidian vault 作为知识库

---

## 文档

完整文档站：**[llm011.github.io/ethan-agent](https://llm011.github.io/ethan-agent/)**（与 Ethan Web UI 内置"文档"页面一致）

核心文档：
- [安装指南](docs/installation.md) — pip / Docker / 源码 / 桌面端
- [记忆系统](docs/memory.md) — 五层架构、做梦沉淀、fact_sync
- [Agent Loop](docs/agent-loop.md) — 三档路由、记忆注入
- [架构总览](docs/architecture.md) — 系统组件、数据流
- [接口层](docs/interface.md) — CLI / REPL / HTTP API / Web UI / 桌面端 / 飞书渠道
- [心跳机制](docs/heartbeat.md) — 后台维护、午夜循环
- [工具系统](docs/tools.md) — 内置工具、`no_compress`、`ui_card`、MCP Apps 图表
- [ACP 集成](docs/acp.md) — Claude Code / OpenCode / Codex 委派
- [浏览器控制](docs/browser/overview.md) — 真实 Chrome 自动化
- [Web 搜索](docs/web-search.md) — DuckDuckGo / Tavily / SearXNG
- [对话模式](docs/modes.md) — 陪伴 / 法律 / Coding Agent 模式
- [法律专家模式](docs/legal-mode.md) — `legal-assistant` 技能详解

所有文档源文件在 [`docs/`](./docs/) 目录，push 到 main 后自动部署。

---

## 贡献者

<!-- ALL-CONTRIBUTORS-LIST:START -->
<a href="https://github.com/llm011/ethan-agent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=llm011/ethan-agent" />
</a>
<!-- ALL-CONTRIBUTORS-LIST:END -->

---

## 许可证

MIT
