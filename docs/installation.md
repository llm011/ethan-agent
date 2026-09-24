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
# 设置 API Key —— OpenAI 兼容接口（OpenAI / Gemini / OpenRouter / Ollama 等）
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.openai.com/v1
ethan model default gpt-5.4   # 或 gemini-2.5-flash 等

# 或 Anthropic 官方接口
ethan provider set anthropic --api-key sk-ant-xxx

# 启动（若未配置 provider，会进入交互式向导，依次填 base_url / api_key / 默认模型）
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
# OpenAI 兼容接口（默认推荐）
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.openai.com/v1
ethan model default gpt-5.4

# 或 Anthropic 官方
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

或使用内置命令（生成 `~/Library/LaunchAgents/com.ethan.agent.plist`）：

```bash
ethan server install     # 安装并启动
ethan server status      # 查看运行状态（会提示多实例冲突）
ethan server restart     # 重启
ethan server stop        # 停止
ethan server uninstall   # 卸载
```

> ⚠️ **不要同时用 launchd 和内置 watchdog 守护同一个服务。** launchd 的 `KeepAlive`
> 已经是守护者，plist 里因此带了 `ETHAN_NO_WATCHDOG=1` 关掉 serve 内置的 watchdog。
> 两个守护者盯同一个端口时，谁先抢到端口，另一个就会一直绑定失败并重启（实测可刷出
> 上千次 `address already in use`），每次重启都会踢断桌面端 WebSocket——表现为
> **「桌面端反复失联」**。

### 服务反复失联 / 起不来？先查多实例

同一时间只应有一个 ethan 实例在跑。**判据是「谁打开了同一个 `sessions.db`」，不是
端口**——两个实例用不同端口照样会互锁。`sessions.db` 是 DELETE journal 模式，写锁
**全库排他**，两个实例并发写会：

- 日志里刷出大量 `database is locked`；
- 严重时一个写事务卡住不提交，`sessions.db-journal` 一直不释放，**连纯 SELECT 都
  `database is locked`**；
- 用户侧表现为**「打开某个会话一直加载」**（读被长事务堵住，`busy_timeout=30s`
  才会失败）。

```bash
ethan server status                    # 有冲突会直接列出来
lsof -p <pid> | grep sessions.db       # 确认某进程是否持有同一个库
ls -la ~/.ethan/db/sessions.db-journal # 存在且长时间不消失 = 有卡死的写事务
cat /tmp/ethan/watchdog.log            # watchdog 的重启决策日志
tail -f ~/.ethan/logs/api.err.log      # 服务启动/绑定错误
```

重复实例会被**立刻拒绝**（退出码 1，不会跑完 lifespan 才失败，也不会挂成僵尸）：

- 端口上已有健康实例 → 拒绝；
- **另一个实例（哪怕端口不同）开着同一个 `sessions.db` → 同样拒绝**；
- 开发/测试要绕过（worktree 跑测试时库和常驻服务是同一个文件）→ 设
  `ETHAN_NO_WATCHDOG=1`；
- 确认要强行启动 → `ethan serve --force`（**不推荐**，真的会锁冲突）。

> `ETHAN_NO_WATCHDOG` **只认 `1`**。写 `=0` 不算关闭（早期 cli 与 api 两处判法
> 不一致，`=0` 会「过了 cli 检测却被 api 守卫拦下」，现已统一）。

保留唯一实例：`ethan server stop` 后重新启动，或 `ethan server uninstall` 卸掉
launchd 服务再手动 `ethan serve`。

> **watchdog 会退役。** 非 launchd 启动的实例会留下一个独立的 watchdog 进程，它只认
> 端口、不认主人。若拉起它的那个 serve 已退出（典型：换成 launchd 托管在别的端口），
> watchdog 会一直 ping 旧端口、判定「server 死亡」并无限复活幽灵实例。退役判据分两种：
>
> - **孤儿 watchdog**（自己启动时端口上就没有任何监听者）：只要一次「拉起来但在 30s
>   内没健康」就**主动退出**（`ORPHAN_RESURRECT_ATTEMPTS`，默认 1）。这是幽灵场景的
>   根治点——注意幽灵实例其实**能起来**（它只是和主实例抢同一个 `sessions.db`），
>   所以「拉起失败次数」在这里恒为 0，必须靠「孤儿」这个判据才退得掉。
> - **正常服役的 watchdog**（启动时端口上有主实例）：**连续** `MAX_RESURRECT_ATTEMPTS`
>   （默认 5）次拉起失败才退役，且**复活成功会清零计数**，所以偶发崩溃的正常实例不会
>   被误退役——真正的崩溃仍由上层 supervisor（launchd `KeepAlive` / 手动 `ethan serve`）
>   或它自己继续重启。

> **launchd 的 `maxfiles` 默认只有 256，对 ethan 偏低。** ethan 要同时持有 Lark
> 事件监听、微信轮询、浏览器插件 WebSocket、多个 SQLite 连接等。fd 耗尽会报
> `OSError: [Errno 24] Too many open files`，且可能发生在 SQLite 提交路径上，
> 表现为写事务卡住。检查与调高：
>
> ```bash
> launchctl limit maxfiles              # 看当前软/硬上限
> sudo launchctl limit maxfiles 65536 unlimited   # 重启后仍生效需写 /etc/launchd.conf 或 plist
> ```
>
> plist 里也可用 `SoftResourceLimits` / `HardResourceLimits` 单独给这个服务放行。

---

## 数据目录

所有运行时数据存放在 `~/.ethan/`：

```
~/.ethan/
├── config.yaml          # 主配置（Provider、模型、路由参数）
├── system/
│   ├── identity.md      # Agent 身份设定
│   ├── soul.md          # 行为原则
│   ├── agent.md         # 工具路由优先级
│   ├── tools.md         # 工具说明补充
│   ├── naming.md        # 对话命名规则（注入标题生成 prompt）
│   └── heartbeat.md     # 心跳任务（自然语言描述的定期任务）
├── memory/
│   ├── memory.db        # 结构化记忆 + 证据链 + 洞察 + 向量索引
│   ├── playbook.json  # 行为规则（从纠正中学习）
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

