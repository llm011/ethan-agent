# 安装指南

## 系统要求

| 方式 | 依赖 |
|------|------|
| Docker 部署（推荐） | Docker 20.10+、Docker Compose v2 |
| 本地开发 | Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 20+（Web UI） |

---

## Docker 安装（推荐）

Docker 方式最省事，后端和 Web UI 分别跑在独立容器里，数据通过 volume 持久化到本地，适合长期运行。

### 1. 克隆仓库

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
```

### 2. 配置环境变量

```bash
cp deploy/.env.example deploy/.env
# 用编辑器打开 deploy/.env，填入 API Key
```

至少填写一个 Provider：

```bash
# Anthropic（推荐，支持 Prompt Caching）
ANTHROPIC_API_KEY=sk-ant-xxx

# 或者 OpenAI 兼容 API（GPT / Gemini / Ollama / OpenRouter 等）
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.example.com/v1

# 默认使用的模型
AGENT_DEFAULT_MODEL=claude-sonnet-4-6

# Web UI 访问鉴权 Token（留空则不鉴权，局域网部署可留空）
ETHAN_AUTH_TOKEN=

# 全局代理（可选）
ETHAN_PROXY=http://127.0.0.1:7890
```

### 3. 构建并启动

```bash
cd deploy
docker compose up -d --build
```

首次构建需要 3–5 分钟（安装 Python 依赖 + 编译 Next.js）。

### 4. 访问

| 服务 | 地址 |
|------|------|
| Web UI | http://localhost:3000 |
| API | http://localhost:8900 |
| 健康检查 | http://localhost:8900/health |

### 5. 常用命令

```bash
docker compose logs -f ethan        # 查看后端日志
docker compose logs -f ethan-web    # 查看前端日志
docker compose restart ethan        # 重启后端
docker compose down                 # 停止所有服务
docker compose up -d                # 重新启动（不重新构建）
docker compose up -d --build        # 拉取最新代码后重新构建启动
```

---

## 本地开发安装

适合需要修改代码或调试的场景。

### 1. 克隆仓库

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
```

### 2. 安装 Python 依赖

需要先安装 [uv](https://docs.astral.sh/uv/)：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

然后安装项目依赖：

```bash
uv sync
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API Key（同 Docker 配置项）
```

也可以通过 CLI 命令设置：

```bash
uv run python -m ethan.interface.cli provider set anthropic --api-key sk-ant-xxx
uv run python -m ethan.interface.cli model default claude-sonnet-4-6
```

### 4. 启动后端

```bash
# 启动 HTTP API 服务（Web UI 需要此服务）
uv run python -m ethan.interface.cli serve

# 或者直接启动交互式 REPL（不需要前端）
uv run python -m ethan.interface.cli
```

### 5. 启动前端（Web UI）

新开一个终端：

```bash
cd web
npm install
npm run dev
```

访问 http://localhost:3000。

### macOS 自动启动（launchd）

```bash
./deploy/install.sh
```

---

## 数据目录

所有运行时数据存放在 `~/.ethan/`：

```
~/.ethan/
├── config.yaml          # 主配置（Provider、模型、路由参数）
├── system/
│   ├── identity.md      # Agent 身份设定
│   ├── soul.md          # 行为原则
│   └── heartbeat.md     # 心跳任务（自然语言描述的定期任务）
├── memory/
│   ├── facts.json       # 结构化事实记忆
│   ├── procedures.json  # 行为规则（从纠正中学习）
│   ├── episodes.json    # 会话摘要归档
│   └── user_profile.md  # 用户画像（叙述式文档）
├── skills/              # 用户自定义技能
│   └── <name>/
│       └── SKILL.md
└── sessions.db          # 会话历史（SQLite）
```

Docker 部署时，此目录通过 named volume `ethan-data` 挂载到容器内的 `/root/.ethan`，数据在容器重建后仍然保留。

---

## 首次访问

首次打开 Web UI（http://localhost:3000）会进入 **Onboarding 流程**，引导你：

1. 填写 API Key（如果还没在 `.env` 里配置）
2. 选择默认模型
3. 设置 Agent 名称和基本偏好

完成后即可开始对话。之后也可以在 **设置（Settings）** 页随时修改这些配置。
