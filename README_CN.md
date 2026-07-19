# Ethan Agent

一个轻量、可扩展的个人 AI Agent，用 Python 构建。设计为在自有硬件上持久运行，具备随时间增长的记忆、定时任务和可插拔的工具/技能系统。

Ethan 融合了 [OpenClaw](https://github.com/openclaw/openclaw)（结构化 agent loop、分层记忆）、[Hermes Agent](https://github.com/NousResearch/hermes-agent)（自我进化技能、记忆整合）和 [nanobot](https://github.com/HKUDS/nanobot)（极简内核、可读代码）的设计理念。

---

## 特性

**记忆体系（五层）**
- 热区/温区/冷区三层滑动窗口维持长对话上下文，廉价模型自动压缩较早内容
- 结构化 Facts：带置信度的条目，有矛盾检测和自动去重（`~/.ethan/memory/facts.json`）
- 行为准则 Procedures：从用户纠正中自动学习，每次对话加载（`playbook.json`）
- 会话 Episodes：对话结束后自动生成摘要存档，支持关键词检索（`episodes.json`）
- 用户画像 Profile：叙事型文档，按章节存储个人语言、目标、约定等（`user_profile.md`）；含「基础特征」「心理与情绪」等章节
- **主动写记忆**：Agent 在对话中识别到可记忆信息时，主动调用工具即时写入，无需批量处理

**做梦——夜间记忆沉淀（"做梦" / dream）**
- 每晚 0 点 Ethan 会"做梦"：用廉价模型把白天跨 session 采集的信号（重复需求 ≥3 次、错误、成功路径）精炼成永久洞察，再用 sqlite-vec 做 L2 去重（阈值 1.1）后写入 `memory.db`
- **结构化记忆层**：在五层模型之上，新增一套 typed `MemoryRecord` 体系（person / preference / methodology / activity / decision / relationship / companion），每 5 轮对话提取有原文佐证的候选，确定性准入（explicit 直接生效；observed 需 ≥2 个独立 session 才晋升），召回注入 prompt，并每日跑一次压缩（general/companion 分域）。苏念（companion）情感记忆隔离在苏念模式，其他模式绝不召回。
- **反写机制**：沉淀的洞察按类型分流反写到 `facts.json`（repetition/error）和 `playbook.json`（success_path），让洞察在未来对话召回时自然生效，无需单独的读取链路
- **fact_sync 镜像**：每次做梦前，把 facts.json/playbook.json 的 active 内容全量镜像到 `memory.db`（type=`fact_sync`），让 insight 的 L2 去重天然覆盖已有 fact，无需手动遍历；镜像每次全量重建
- **永久保留**：第五层是真正的长期记忆——洞察不会被自动删除；`last_accessed` 仅作活跃度观察，不作为淘汰依据（memory.db 体量天然可控，每条洞察约 15KB）
- **sessions.db 轮转**：完整消息历史增长快，sessions.db 超 10 MB 时用 `VACUUM INTO` 原子快照到 `~/.ethan/archive/sessions.{start}~{end}.db`（文件名带日期跨度），保持 active db 轻量，旧会话仍可按日期查归档

**陪伴倾听模式 · 苏念（《臣服实验》心理咨询师）**
- 可加载插件：在聊天界面一键切换「苏念 · 陪伴倾听」，从工作助手变成一位年轻温柔的女性陪伴者，熟读《臣服实验》、深谙道法自然
- 该模式下 Agent 先赞许安抚、深度倾听、陪伴而非急于解决问题——说话像真人、温柔口语，拒绝 AI 腔
- 陪伴模式下，后台自动把「心理与情绪」（情绪/压力源/什么能安抚你/内心感受）整理进画像；基础特征由你在设置页「我的画像」里填写

**法律专家模式 · legal-assistant（按需安装）**
- 切换到「法律专家」模式后，单个 `legal-assistant` 技能即覆盖案件研判、诉讼分析、合同审查、法律文书/方案生成、商标专利知产、案件流程管理、法律检索与可视化——按「任务动词 + 业务条线」路由到对应 playbook，不堆几十个子技能
- **零污染**：法律技能用 `modes: [法律]` 标记，仅在法律模式生效；正常工作模式下完全不进上下文
- **自动安装（按需）**：首次切到法律模式若未安装，Agent 会**自动从仓库拉取并安装** `legal-assistant`（会先告知「正在安装」，不静默联网；装失败则提示手动 `ethan skill add legal`）。法律内容不随主仓库分发，遵循上游 CC-BY-NC 非商用许可
- **手动安装**：命令行直接 `ethan skill add legal` 一键装（= `llm011/ethan-legal-skill/skills/legal-assistant`）
- **`/mode` 切换**：CLI（REPL）和飞书等渠道均可用 `/mode 法律` 切入、`/mode default` 切回默认；模式名无法识别时保持当前模式不变。模式持久化在会话上，恢复会话自动还原

**Skill 技能系统**
- 触发词匹配，自动注入 system prompt 引导行为
- 可选语义路由器（BGE INT8 + LR 头）在关键词之上补召回，换个说法也能命中（`pip install 'ethan-agent[embedding]'`，不装则纯关键词，详见安装段）
- `fast_path: true` 触发后走毫秒级快速路径，适合全屋智能等高频控制
- `channels: [lark, web]` 按渠道过滤，Skill 只在指定场景下生效
- `modes: [法律]` 按对话模式过滤，Skill 只在指定模式下生效（空 = 所有模式）
- Skill 命中统计与纠正收集，积累后 Heartbeat 自动用廉价模型更新 Skill 内容
- Agent 可在对话中即时创建新 Skill（`skill_create` 工具）

**三档智能路由**
- **fast**：短命令 + 关键词匹配 → 极简 prompt + 仅限 fast_path 工具 + 2 次迭代
- **medium**：中等消息 → 完整 prompt + 全部工具 + 4 次迭代
- **full**：复杂任务 → 完整 prompt + 全部工具 + 10 次迭代

**Loop 控制**
- 卡死检测：连续 3 轮调用相同工具+参数（或连续 2 轮同一报错）时，注入强制反思提示（要求 `<diagnosis>` 诊断并换路），而不是一路空转到迭代上限
- 优雅收尾：反思 2 次仍卡住、或跑满迭代上限时，最后一轮禁用工具，让模型生成「已完成 / 卡点 / 需你提供什么」的收尾报告——不再返回 `[max tool iterations reached]` 死字符串

**定时任务与后台任务**
- 对话中创建 cron 或 interval 任务，SQLite 持久化，重启自动恢复
- `heartbeat.md`：写入自然语言任务，系统定期自动执行
- 后台任务：把耗时长任务丢到后台独立会话异步执行，不阻塞当前对话；完成后结果回灌（飞书推回原会话，web 在侧边栏会话浮现）。在 `/background-tasks` 页查看/终止，侧边栏带运行中数量角标

**工具系统**
- Shell 执行、Web 搜索（默认 DuckDuckGo，可配置切换 Tavily 或自建 SearXNG，见 `deploy/docker-compose.searxng.yml`）、Web 抓取、文件读写、知识库检索
- 敏感/副作用操作（shell、写文件、读密钥）执行前请求授权；Web 弹授权卡片、REPL 走 y/N，同一会话授权过一次后不再重复询问
- 工具结果超 4000 字自动用廉价模型压缩摘要
- 同参数重复调用自动命中轮次内缓存，不重复执行

**Prompt Caching**
- system prompt 分稳定层/动态层，稳定层缓存 5 分钟，token 成本降至 0.1×

**多渠道**
- CLI REPL、Web UI（Next.js）、**Android App**（Kotlin/Compose）、飞书（WebSocket 长连接，无需公网 IP）
- 飞书鉴权自动引导：当依赖用户身份的调用（如 `--as user` 读群背景上下文）遇到鉴权类错误（99991663 / 99991661 / `need_user_authorization`）时，机器人会向该会话发一张红色引导卡片，指引用户执行 `lark-cli auth login --domain im` 重新授权。同一群 5 分钟内只发一次；网络/参数/not-found 等非鉴权错误不触发。
- 飞书多事件订阅 + 卡片按钮回调：每个 EventKey（收消息 / 已读回执 / reaction / `card.action.trigger`）各跑一个 `lark-cli event consume` 子进程，独立断线重连；交互卡片按钮点击通过 `_handle_card_action` 回路，支持按钮驱动的工作流。

**浏览器控制（真实 Chrome）**
- 在任意渠道（Web / 飞书 / CLI）对话中，操作 ethan 所在机器上的真实 Chrome —— 安装内置的 `browser-extension`，填上 ethan 的 WebSocket 地址，agent 即获得 `browser_session` / `browser_tab` / `browser_page` 三个工具
- agent-browser 风格：可访问性树 snapshot + ref map，click/fill/type/press/select/scroll/hover、截图、键鼠事件、页面 `eval`，全部经 Chrome DevTools Protocol 执行
- session 绑定对话（按对话隔离）；同一 session 内页面操作串行、不同 session 并行；闲置 30 分钟后 release（保留用户 tab）
- 会话级一次性授权：本对话第一次调用 browser 工具询问一次，批准后该对话所有操作（含 `eval`）放行
- 传输仅用 WebSocket（扩展 → ethan），无需 native messaging host；详见 [docs/browser-control-plan.md](docs/browser-control-plan.md)

**桌面控制（macOS，基于 cua-driver）**
- 在任意渠道（Web / 飞书 / CLI）控制本机 macOS 桌面——截图、点击、输入、拖拽、滚动、启动应用、打开 URL
- 基于 [trycua/cua](https://github.com/trycua/cua)；连接本地后台服务 `cua-driver`（监听 `localhost:8000`），无需虚拟机
- 截图结果直接传给视觉模型，agent 看到屏幕后决定下一步操作
- `ethan server install` 自动安装并注册 `cua-driver` 为 launchd 服务；也可手动安装：`curl -fsSL .../install.sh | bash && cua-driver install`
- 可选 Python SDK：`pip install 'ethan-agent[computer]'`（cua-computer）；未安装时工具自动不可见，不影响其他功能

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

> **一键装法律专家模式**：在 `docker compose up` 前设 `ETHAN_INSTALL_SKILLS=legal`（或起容器后 `docker compose exec ethan-agent ethan skill add legal`），即可装好 `legal-assistant` 技能；Web 端模式下拉切到「⚖️ 法律专家」即生效。

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

### 可选：语义路由器（让技能匹配更聪明，新手可跳过）

默认情况下，Ethan 用关键词匹配来决定启用哪个技能。这对大多数场景已经够用，**不装也能正常跑**。

如果你希望换个说法也能命中技能（比如不说「发飞书」而说「给客户带句话」也能触发飞书技能），可以开启可选的语义路由器：

```bash
# 1. 装可选依赖（一个轻量推理运行时，约几十 MB）
pip install 'ethan-agent[embedding]'      # PyPI 安装
# 从源码则： uv sync --extra embedding

# 2. 拉模型（约 24MB，仅首次；不手动跑也行，首条消息会自动下载）
ethan router pull

# 3. 确认状态
ethan router status                    # 显示「✓ 路由器就绪」即可
```

- **完全可选**：没装依赖、没下模型或离线时，自动退回关键词匹配，不影响任何功能。
- 模型托管在 GitHub，首次用到时自动下载并缓存到本地，之后离线可用。
- 想关掉：删掉可选依赖即可，无需改配置。

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
│       ├── skill_create.py    # 对话中创建 Skill
│       └── lark_tools.py      # 飞书 CLI 封装（日历 / 群消息 / 消息发送）
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
| 行为准则 | 从用户纠正中学习的规则 | `~/.ethan/memory/playbook.json` |
| 用户画像 | 叙事型个人信息（目标、短语、约定） | `~/.ethan/memory/user_profile.md` |
| 永久记忆（第五层） | "做梦"沉淀的跨 session 洞察（重复/错误/成功路径） | `~/.ethan/memory/memory.db`（sqlite-vec） |

压缩是**批量触发**的（而非逐轮），使用自动推断的廉价模型（Claude 用户用 Haiku，Gemini 用户用 Flash Lite）。

Agent 通过 `memory_write`、`procedure_write`、`profile_update` 工具在对话中主动写入各层，无需等待下一个压缩周期。

第五层"做梦"（dream）在每晚 0 点自动运行：采集白天跨 session 信号 → 廉价模型精炼 → sqlite-vec L2 去重 → 写入 `memory.db`，并反写到 `facts.json`/`playbook.json` 让洞察在召回时自然生效。详见 [记忆系统设计文档](docs/memory.md)。

---

## Skill 技能系统

Skill 从 `~/.ethan/skills/` 加载。首次运行时，包内默认技能（channels、deepwiki、lark-im、lark-shared、skills-manager、use-browser、agent-browser、dev-browser）会自动复制到该目录。

支持目录格式（`<name>/SKILL.md` + `references/` 子目录）和旧版单文件 `.md` 格式。命中目录格式 skill 时，注入的 context 会附上 `references/*.md` 的文件名 + 一行摘要清单，让模型知道有哪些细节文档可查——再用 `skill_read(name=..., file="references/<name>.md")` 按需拉具体内容（pull-based，不全量灌入正文）。

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
    no_compress = False # 若输出含需原样回传的 ID/ref/结构化数据，置 True

    parameters = {"type": "object", "properties": {...}, "required": [...]}

    async def run(self, **kwargs) -> str:
        return "结果"
```

在 `cli.py` 注册后，LLM 会在合适时机自动调用。

> **`no_compress`**：工具输出超过 4000 字会先被廉价模型压成摘要再喂给主模型。输出是给模型「读」的散文（网页、日志）就保持关闭；若输出里含模型需要**原样回传**的数据——ID、ref、路径、结构化 JSON——则置 `True`，否则摘要会丢掉这些 token，模型拿到结果却无法操作。

内置工具还包括 `ui_card`：把结构化信息渲染成卡片，比纯文字更直观。高频类型（对比 / 排行 / 统计 / 时间轴）走后端固定模板——模型只填结构化数据，样式稳定一致；自定义卡片仍可手写。渲染按渠道分叉、共享同一套结构化 `card` 数据：Web 端用 `@a2ui/react` 渲染 [A2UI](https://a2ui.org/)、REPL 走文本降级、飞书则渲染成原生 interactive 卡片（在「工具用 post、结果用流式卡片」的基础输出之上的增量美化）。格式细节放在按需读取的 `ui-card` skill 里，system prompt 保持精简。

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

ethan model list|add|remove|default
ethan provider list|set
ethan session list|show|delete
ethan skill list|show|add|create
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
GET  /ui-resources              # MCP Apps UI 资源（SEP-1865）：列出
GET  /ui-resources/read?uri=    # MCP Apps UI 资源：读取 HTML + _meta
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
│   ├── playbook.json  # 行为准则
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
验证：cat ~/.ethan/memory/playbook.json | python3 -m json.tool

# 3. 用户画像
发送："你可以用 Roots run deep 这个短语来激励我坚持"
验证：cat ~/.ethan/memory/user_profile.md

# 4. 纠正学习
发送一段回复 → "不对，应该用 XXX 方式"
验证：cat ~/.ethan/memory/playbook.json

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
- [x] 可选语义路由器（BGE INT8 + LR 头，macro F1 0.851）在关键词之上补召回；缺失时静默退回关键词。同一套 `[embedding]` 依赖也驱动 memory.db 的语义去重
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
- [x] **ACP 持续对话优化**：`delegate_coding` 按「Coding Agent × 工作目录」持久化 session_id。三套后端（Claude Code / OpenCode / Codex）现都走 JSON 事件流 + 会话续接，解析为 sub_steps，Web UI 时间轴折叠展示、最终结果高亮。Codex 复用 Ethan 的 cliproxy provider；超时优雅终止并清掉会话，避免续接到卡住的 thread
- [x] **镜像会话**：每次 `delegate()` 落成一条真正的 Ethan 会话（`source` 用真实工具名 codex/claude/opencode），记录下发的 query + Coding Agent 回复 + 步骤，并注册为 RunManager run，委派过程可经 SSE 实时观看
- [x] **沉浸式工具模式**：对话 mode 可切到 Codex / Claude Code / OpenCode；切入后整条会话每句话都直接续接该工具（同一工具 session、按会话隔离工作目录），既能临时 delegate，也能沉浸式持续对话。在镜像会话里直接发消息也会自动续接对应工具
- [ ] **MCP client 完善**：连接外部 MCP server，自动注册工具

**长期**
- [ ] **域隔离（Space）**：生活 / 工作 / 项目记忆独立，防止混杂
- [ ] **异步中断**：长任务执行中感知新消息，在工具调用间隙响应
- [ ] **Obsidian 接入**：读写 Obsidian vault 作为知识库

---

## 文档

完整文档站：**[llm011.github.io/ethan-agent](https://llm011.github.io/ethan-agent/)**（与 Ethan Web UI 内置"文档"页面一致）

核心文档：
- [记忆系统](docs/memory.md) — 五层架构、做梦沉淀、fact_sync
- [Agent Loop](docs/agent-loop.md) — 双轨路由、记忆注入
- [架构总览](docs/architecture.md) — 系统组件、数据流
- [心跳机制](docs/heartbeat.md) — 后台维护、午夜循环

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
