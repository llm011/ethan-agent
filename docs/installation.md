# 安装指南

## 方式一：桌面端安装（最适合普通用户）

到 [GitHub Releases](https://github.com/llm011/ethan-agent/releases) 下载对应平台的安装包：

| 平台 | 文件 | 说明 |
|------|------|------|
| macOS Apple Silicon | `Ethan.Agent_<ver>_aarch64.dmg` | M1/M2/M3/M4 系列 |
| macOS Intel | `Ethan.Agent_<ver>_x64.dmg` | Intel Mac |
| Windows | `Ethan.Agent_<ver>_x64-setup.exe` 或 `.msi` | Windows 10/11 x64 |

桌面端内嵌完整的 Web UI，启动后自动打开窗口，无需额外配置 Python 环境。

### macOS 首次打开

由于目前未做 Apple Developer 签名公证，双击 dmg 安装后首次打开会被 Gatekeeper 拦截，提示"已损坏，无法打开"。这是误导文案，应用本身没有损坏。打开终端执行：

```bash
xattr -dr com.apple.quarantine "/Applications/Ethan Agent.app"
```

执行后再双击应用图标即可打开。之后不再需要重复此操作。

> 如果"隐私与安全性"里没有"仍要打开"按钮，说明就是这个问题——按钮只给有签名但未公证的应用，未签名应用需要用上面的 xattr 命令解除隔离。

### 配置

桌面端启动后会在 `~/.ethan/` 自动初始化配置目录。首次启动进入 Onboarding 流程，引导填写 API Key 和选择默认模型。

---

## 方式二：pip 安装

仅需 Python 3.12+，无需克隆仓库：

```bash
pip3 install ethan-agent
```

安装后 `ethan` 命令即可使用：

```bash
# 设置 API Key
ethan provider set anthropic --api-key sk-ant-xxx
# 或 OpenAI 兼容 API（Gemini / OpenRouter / Ollama 等）
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1

# 启动
ethan

# 或直接拉起/打开 Web 页面控制台
ethan web

# 查看你的 Web 登录 Token (登录 Web 时需要)
ethan web token
```

> 💡 **小贴士**：运行 `ethan` 启动对话 REPL 时，系统会自动检测 8900 端口（API 服务）是否已启动，如果已启动则自动用默认浏览器打开 Web UI 控制台页面。Web UI 由 `ethan serve` 内置托管，无需额外启动前端服务。

首次运行会自动初始化 `~/.ethan/`，写入默认技能和系统文件。

---

## 方式三：Docker（推荐用于服务器）

Docker 方式最省事，Backend 和 Web UI 各自独立容器，数据持久化到本地卷。

无需克隆仓库，直接下载 `docker-compose.yml` 并启动。

### 系统要求

- Docker 20.10+
- Docker Compose v2

### 1. 下载配置文件

创建一个空目录并下载官方的 `docker-compose.yml`：

```bash
mkdir ethan-agent && cd ethan-agent
curl -O https://raw.githubusercontent.com/llm011/ethan-agent/main/docker-compose.yml
```

### 2. 配置环境变量

创建一个 `.env` 文件填入你的 API Key：

```bash
cat > .env << 'EOF'
# Anthropic（推荐，支持 Prompt Caching）
ANTHROPIC_API_KEY=sk-ant-xxx

# 或者 OpenAI 兼容 API（GPT / Gemini / Ollama / OpenRouter 等）
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.example.com/v1

# 默认使用的模型
AGENT_DEFAULT_MODEL=claude-sonnet-4-6

# Web UI 访问鉴权 Token（留空则不鉴权，局域网部署可留空）
ETHAN_AUTH_TOKEN=

# 全局代理（可选）
# ETHAN_PROXY=http://127.0.0.1:7890
EOF
```

### 3. 拉取镜像并启动

```bash
docker compose up -d
```

镜像会自动从 GitHub Container Registry 拉取并启动。

### 4. 访问

| 服务 | 地址 |
|------|------|
| Web UI | http://localhost:3000 |
| API | http://localhost:8900 |
| 健康检查 | http://localhost:8900/health |

### 5. 常用命令

```bash
docker compose logs -f ethan-backend   # 查看后端日志
docker compose logs -f ethan-web       # 查看前端日志
docker compose restart ethan-backend   # 重启后端
docker compose down                    # 停止所有服务
docker compose pull && docker compose up -d  # 更新到最新版本
```

---

## 方式四：从源码安装（开发者）

适合需要修改代码或调试的场景。

### 系统要求

| 依赖 | 版本 |
|------|------|
| Python | 3.12+ |
| [uv](https://docs.astral.sh/uv/) | 最新版 |
| Node.js | 20+（仅 Web UI） |

### 1. 克隆仓库

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
```

### 2. 安装 Python 依赖

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### 3. 配置

```bash
ethan provider set anthropic --api-key sk-ant-xxx
```

### 4. 启动后端

```bash
# 交互式 REPL
ethan

# 启动 HTTP API 服务（Web UI 需要）
ethan serve
```

### 5. 启动前端（Web UI）

新开一个终端：

```bash
cd web
npm install
npm run dev
```

访问 http://localhost:3000。

### 6. 构建桌面端（可选）

如需本地构建桌面 app（开发调试用），见 `desktop/` 目录：

```bash
cd desktop
pnpm install
pnpm tauri dev    # 开发模式
pnpm tauri build  # 产出 dmg/exe
```

需要预装 Rust、Node.js 20+ 和 pnpm。CI 产出的官方包见 [Releases](https://github.com/llm011/ethan-agent/releases)。

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
│   ├── memory.db        # 结构化记忆 + 证据链 + 洞察 + 向量索引
│   ├── playbook.json  # 行为规则（从纠正中学习）
│   ├── episodes.json    # 会话摘要归档
│   └── user_profile.md  # 用户画像（叙述式文档）
├── skills/              # 用户自定义技能（首次运行自动写入默认技能）
│   └── <name>/
│       └── SKILL.md
└── sessions.db          # 会话历史（SQLite）
```

Docker 部署时，此目录通过 named volume `ethan-data` 挂载到容器内的 `/root/.ethan`，数据在容器重建后仍然保留。

---

## 首次访问

首次打开 Web UI（http://localhost:3000）会进入 **Onboarding 流程**，引导你：

1. 填写 API Key（如果还没通过 CLI 配置）
2. 选择默认模型
3. 设置 Agent 名称和基本偏好

完成后即可开始对话。之后也可以在 **设置（Settings）** 页随时修改这些配置。

