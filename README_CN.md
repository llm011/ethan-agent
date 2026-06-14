# Ethan Agent

一个轻量、可扩展的个人 AI Agent，用 Python 构建。设计为在自有硬件上持久运行，具备随时间增长的记忆、定时任务和可插拔的工具/技能系统。

Ethan 融合了 [OpenClaw](https://github.com/openclaw/openclaw)（结构化 agent loop、分层记忆）、[Hermes Agent](https://github.com/NousResearch/hermes-agent)（自我进化技能、记忆整合）和 [nanobot](https://github.com/HKUDS/nanobot)（极简内核、可读代码）的设计理念。

---

## 特性

**记忆体系（五层）**
- 热区/温区/冷区三层滑动窗口维持长对话上下文，廉价模型自动压缩较早内容
- 结构化 Facts：带置信度的条目，有矛盾检测和自动去重（`~/.ethan/memory/facts.json`）
- 行为准则 Procedures：从用户纠正中自动学习，每次对话加载（`procedures.json`）
- 会话 Episodes：对话结束后自动生成摘要存档，支持语义检索（`episodes.json`）
- 用户画像 Profile：叙事型文档，按章节存储个人语言、目标、约定等（`user_profile.md`）
- **主动写记忆**：Agent 在对话中识别到可记忆信息时，主动调用工具即时写入，无需批量处理

**Skill 技能系统**
- 触发词匹配，自动注入 system prompt 引导行为
- `fast_path: true` 触发后走毫秒级快速路径，适合全屋智能等高频控制
- `channels: [lark, repl]` 按渠道过滤，Skill 只在指定场景下生效
- Skill 命中统计与纠正收集，积累后 Heartbeat 自动用廉价模型更新 Skill 内容
- Agent 可在对话中即时创建新 Skill（`skill_create` 工具）

**三档智能路由**
- Fast：短命令 + 关键词匹配 → 极简 prompt + 仅限 fast_path 工具 + 2 次迭代
- Medium：中等消息 → 完整 prompt + 全部工具 + 4 次迭代
- Full：复杂任务 → 完整 prompt + 全部工具 + 10 次迭代

**定时任务**
- 对话中创建 cron 或 interval 任务，SQLite 持久化，重启自动恢复
- `heartbeat.md`：写入自然语言任务，系统定期自动执行

**工具系统**
- Shell 执行、Web 搜索（DuckDuckGo）、Web 抓取、文件读写、知识库检索
- 工具结果超 4000 字自动用廉价模型压缩摘要
- 同参数重复调用自动命中缓存，不重复执行

**Prompt Caching**
- system prompt 分稳定层/动态层，稳定层缓存 5 分钟，token 成本降至 0.1×

**多渠道**
- CLI REPL、Web UI（Next.js）、飞书（WebSocket 长连接，无需公网 IP）

---

## 快速开始（Docker，推荐）

Docker 是最简单的部署方式，Backend 和 Web UI 各自独立容器，数据持久化到本地卷。

### 前置条件

- Docker 20.10+
- Docker Compose v2

### 1. 克隆项目

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
```

### 2. 配置环境变量

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env，填入 API Key
```

至少填一个 Provider：

```bash
# Anthropic（推荐，支持 Prompt Caching）
ANTHROPIC_API_KEY=sk-ant-xxx

# 或者任意 OpenAI 兼容 API
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.example.com/v1

# 设置默认模型
AGENT_DEFAULT_MODEL=claude-sonnet-4-6
```

### 3. 构建并启动

```bash
cd deploy
docker compose up -d --build
```

首次构建约 3-5 分钟（安装依赖 + 构建 Next.js）。

### 4. 访问

- **Web UI**：http://localhost:3000
- **API**：http://localhost:8900
- **健康检查**：http://localhost:8900/health

### 5. 常用命令

```bash
# 查看日志
docker compose logs -f ethan

# 重启服务
docker compose restart ethan

# 停止
docker compose down

# 数据目录（记忆、技能、配置）
docker volume inspect deploy_ethan-data
```

---

## 本地开发安装

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Node.js 20+（Web UI）

### 安装 Backend

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
uv sync
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

或通过 CLI：

```bash
ethan provider set anthropic --api-key sk-ant-xxx
ethan model default claude-sonnet-4-6
```

### 运行

```bash
# 交互式 REPL
ethan

# 单轮对话
ethan -p "今天有什么提醒？"

# 指定模型
ethan -m claude-opus-4-6

# 恢复上次会话
ethan -r last

# 启动 API + Web 服务
ethan serve
```

### 全局安装

```bash
chmod +x bin/ethan
ln -s $(pwd)/bin/ethan ~/bin/ethan
```

### Web UI 开发模式

```bash
cd web
npm install
npm run dev   # http://localhost:3000
```

### macOS 开机自启（launchd）

```bash
./deploy/install.sh
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

## 配置文件结构

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

## HTTP API

```bash
GET  /health                    # 健康检查
GET  /models                    # 可用模型列表
POST /chat                      # 对话（支持 stream: true SSE 流式）
GET  /sessions                  # 会话列表
GET  /sessions/{id}             # 会话详情（含消息历史）
GET  /memory/facts              # Facts 列表
GET  /memory/episodes           # Episode 摘要列表
GET  /skills                    # Skill 列表
POST /skills                    # 创建 Skill
POST /skills/evolve             # 手动触发 Skill 自动更新
GET  /schedule                  # 定时任务列表
GET  /system-prompt-preview     # 当前 system prompt 预览
```

---

## 文档

详细设计文档在 [`docs/`](./docs/) 目录下。

## 许可证

MIT
