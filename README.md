# Ethan Agent v2

> 个人 AI Agent —— 多内核驱动、可插拔工具、跨端（Web / Desktop / Android）

[![Version](https://img.shields.io/badge/version-1.0.0b6-orange)](https://pypi.org/project/ethan-agent/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)

---

## 🚀 快速开始

```bash
# 安装
pip install ethan-agent

# 交互式 REPL
ethan

# 单轮对话
ethan -p "帮我看下这个仓库的结构"

# 启动 Web/API 服务（前台）
ethan serve

# 装成开机自启的后台服务（macOS launchd）
ethan server install

# 服务管理
ethan server status      # 查看状态
ethan server restart     # 重启
ethan server stop        # 停止
ethan server uninstall   # 卸载开机自启
```

服务默认监听 `8900`。启动后浏览器打开 `http://localhost:8900` 即可使用 Web 界面。

### Docker 部署（服务器 / NAS）

```bash
# 从 release 下载部署文件，或用仓库里的 deploy/ 目录
curl -LO https://github.com/llm011/ethan-agent/releases/latest/download/docker-compose.yml
curl -LO https://github.com/llm011/ethan-agent/releases/latest/download/.env.example
cp .env.example .env    # 按需改端口、数据目录

docker compose up -d
```

镜像：`ghcr.io/llm011/ethan-agent:latest`（linux/amd64 + linux/arm64）。
`deploy/` 下还有 `docker-compose.nas.yml`（群晖等 NAS）与 `docker-compose.searxng.yml`（自带搜索后端）。

> **`ethan serve` 与 `ethan server` 是两件事**：
> `serve` 在前台跑 API 服务（子命令只有 `stop`）；
> `server` 管理 macOS launchd 后台服务（`install` / `uninstall` / `restart` / `stop` / `status`）。

---

## 🧠 多内核

内核决定「由谁执行这一轮对话」。原生内核用 Ethan 的全部能力；外部内核把执行权
交给对应 CLI（Claude Code / Codex / OpenCode / Antigravity / DSH / Pi），各有自己的模型与工具。

| 内核 | 需要 | 可用 Ethan 的工具 |
|---|---|---|
| `ethan` | 内置 | ✅ 原生 |
| `claude_code` | `claude` CLI | ✅ 经 MCP 注入 |
| `dsh` | `dsh` CLI | ✅ 经 ACP `mcp_servers` 注入 |
| `opencode` | `opencode` CLI | ✅ 经 ACP `mcp_servers` 注入 |
| `antigravity` | `agy` CLI | ✅ 经 ACP `mcp_servers` 注入 |
| `codex` | `codex` CLI | ❌ 仅自带工具 |
| `pi` | `pi` CLI | ❌ 仅自带工具 |

**「可用 Ethan 的工具」是什么意思**：外部内核保留自己的大脑（规划/推理），但通过
`/kernel-tools` 这个 MCP 端点拿到 Ethan 的 58 个工具——搜索、知识库、文件、OCR、
技能与记忆（`skill_list` / `skill_read` / `recall_memory` / `memory_write`）等。
于是它既能用自己擅长的能力，又能用 Ethan 的手脚干活。

光把工具挂上去还不够：外部内核看不到 Ethan 的系统提示词，不知道「有这些技能」
「该在什么时候召回记忆」。所以派发时还会前置一张**简报表**——技能索引 +
「涉及个人上下文先调 `ethan_recall_memory`」+「值得长期记住的事调
`ethan_memory_write`」。人格与用户画像**不注入**（两份人格会打架），这是
`ethan_context=False` 的取舍。没共享工具的内核（Codex / Pi）不带简报，
免得教它们调不存在的工具。

注入不污染用户环境：`mcp_servers` 是 ACP `new_session()` 的每次调用参数，
不写入 `~/.dsh` / `~/.claude`。DSH 自带的工具全部保留，只多出 `mcp__ethan__*` 前缀的那批。

**切换内核**：设置页「AI 内核」标签，或

```bash
curl -X POST localhost:8900/api/kernels/select \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind": "dsh"}'
```

依赖缺失时**自动安装**；装不上则拒绝切换并保留原内核（返回 409）。

详见 [内核架构](docs/kernel-architecture.md)。

---

## 🧬 记忆体系

`memory.db` 是用户事实的唯一事实源，不是简单向量库：

- **增量提取**：短会话（<3 轮）即时提取；之后每 3 轮提取带 **原文 quote 佐证**的候选
  （quote 必须是用户消息的精确子串，防止模型臆造）
- **确定性准入**：`explicit`（用户明说）立即生效；`observed`（观察推断）需
  ≥2 个独立 session 复证才晋升
- **分层维度**：`preference.tools` / `decision.chosen` / `activity.project` /
  `methodology.execution_workflow` 这类点分维度（实测在用 80+ 个），带置信度与重要度
- **可回溯**：`evidence_level` 区分 explicit / inferred / corrected；
  支持 TTL 过期、`supersede` 纠正链（改了哪条、什么时候改的）、遗忘脱敏

记忆不是塞进 prompt 就完事——召回经过语义路由，只取当前问题相关的部分。

详见 [记忆](docs/memory.md) · [语义路由](docs/semantic-router.md)。

---

## 🎭 模式

模式是**人格/语气**切换，与内核正交：

- 工作助手（默认）
- 精简模式
- 法律专家
- 苏念 · 陪伴倾听

---

## 🛠️ 工具

内置 60+ 工具，按需广播（fast / full 路由档）。

| 类别 | 工具 |
|---|---|
| 搜索 | `web_search`（searxng → deepseek → tavily → duckduckgo → bing）、`web_fetch`、`image_search` |
| 文件 | `file_read` / `file_write` / `file_edit` / `file_list` / `deliver_file` |
| 文档 | `doc_save` / `doc_list` / `doc_read` |
| 知识库 | `knowledge_search` / `knowledge_add` / `knowledge_update` |
| 记忆 | `memory_write` / `memory_search` / `profile_update` |
| 日程 | `schedule_create` / `schedule_list` / `dida_*` |
| 编程 | `code_read` / `code_write` / `code_analyze` / `code_run` / `code_assistant` |
| 浏览器 | `browser_session` / `browser_tab` / `browser_page` / `browser_client` |
| 桌面 | `computer_use` / `desktop_notify` / `desktop_countdown` |
| 多模态 | `ocr_extract_text` / `generate_chart` / `read_image` |
| 其他 | `get_weather` / `lunar_calendar` / `ui_card` / `ask_user` |

工具输出超过 4000 字符会自动压缩，但含 ID/路径/结构化数据的工具（`no_compress`）
原样透传——压缩会把 ID 搅成散文，模型就没法用了。

详见 [工具系统](docs/tools.md)。

---

## 🗣️ 语音

TTS / ASR 后端可配置：

- **edge-tts** — 在线，零安装，跨平台
- **ethan-tts** — 本地，离线、可克隆音色，需要 Apple Silicon + MLX

选本地后端时会**先做系统预检**：非 Apple Silicon 直接拒绝，零安装动作。
服务启动由选择动作触发，不需要敲命令。

详见 [语音](docs/tts.md)。

---

## 🔌 渠道

- **Web** — 内置，浏览器直接访问
- **Desktop** — Tauri 2 应用，支持自动更新
- **Android** — APK，与 Web/Desktop 共享后端
- **飞书** — 机器人，需 `lark-cli`
- **微信** — iLink 协议
- **CLI** — REPL 交互
- **ACP** — stdio JSON-RPC，供编辑器/IDE 拉起

---

## 📡 API

所有接口在 `/api` 下（表中的路径需加此前缀）：

```bash
GET  /health                      # 健康检查
GET  /models                      # 可用模型列表
POST /chat                        # 对话（stream: true 开启 SSE 流式）
GET  /sessions                    # 会话列表
GET  /sessions/{session_id}       # 会话详情（含消息历史）
GET  /memory/facts                # 记忆列表，分页（limit/offset/total）
GET  /memory/records              # 结构化记忆，分页（可按 type/domain/status 过滤）
GET  /memory/records/search       # 结构化记忆检索
GET  /skills                      # Skill 列表
POST /skills                      # 创建 Skill
POST /skills/evolve               # 手动触发 Skill 自动更新
GET  /schedule                    # 定时任务列表
GET  /system-prompt-preview       # 当前 system prompt 预览
GET  /channels                    # 渠道列表
GET  /knowledge/search            # 语义检索
GET  /ui-resources                # MCP Apps UI 资源：列出
GET  /ui-resources/read?uri=      # MCP Apps UI 资源：读取 HTML + _meta
GET  /kernels                     # 内核列表与可用性
POST /kernels/select              # 切换内核
GET  /tts/backends                # 语音后端可用性
POST /tts/select                  # 切换语音后端
```

交互式文档：服务启动后访问 `/docs`。

---

## ⚙️ 配置

全部在 `~/.ethan/config.yaml`，也可用 `ethan setup` 交互式配置。

```yaml
defaults:
  model: provider/model-id
  kernel:
    default: ""            # "" = 原生 Ethan；可选 dsh / claude_code / opencode / antigravity / codex / pi
    task_rules: {}         # {"coding": "claude_code"} 按任务类型选内核
    share_tools: all       # all | readonly | off —— 外部内核能用多少 Ethan 的工具

network:
  auth_token: "..."        # Web/API 认证
  base_url: ""             # 对外可达地址（内核注入工具时用）

tts:
  backend: edge-tts        # edge-tts | ethan-tts
```

数据目录 `~/.ethan/`：

```
config.yaml          配置文件
db/sessions.db       会话与消息
db/memory.db         长期记忆
system/              tools.md / soul.md / agent.md 等提示词文件
memory/              user_profile.md / playbook.json
skills/              自定义技能
knowledge/           知识库
```

---

## 🧪 开发

```bash
git clone https://github.com/llm011/ethan-agent
cd ethan-agent
uv sync --extra dev

pytest tests/ -q          # 1880+ 测试
ruff check .              # lint
python -m tests.bench_prompt_size   # prompt 体积护栏
```

前端（Web / Desktop 双端必须同步）：

```bash
pnpm install
pnpm build:web            # Next.js 静态导出 → ethan/web_dist
pnpm --dir desktop build  # Desktop 前端
pnpm --dir desktop tauri build   # 打桌面安装包
```

Android：

```bash
cd app/android
./gradlew assembleDebug   # 产物：app/build/outputs/apk/debug/
```

详见 [贡献与开发](docs/quickstart.md)。

---

## 🗺️ Roadmap

### 已完成

- 多模型 Provider（Anthropic + OpenAI 兼容：DeepSeek、Gemini、Ollama、聚合网关等）
- ReAct agent loop + 流式输出 + 工具时间线
- 两档路由 fast / full；工具结果超长自动压缩；轮次内去重缓存
- Prompt Caching（Anthropic 稳定层 `cache_control`，命中部分成本 0.1×）
- 分层记忆（工作记忆压缩 → 结构化 fact → 叙事画像）+ 语义召回
- Skill 系统（内置 + 用户自定义 + 渠道过滤）
- 多内核运行时（7 个内核，DSH / Claude Code / OpenCode / Antigravity 可共享 Ethan 工具）
- 定时任务、心跳、后台任务
- 多渠道（Web / Desktop / Android / 飞书 / 微信 / CLI / ACP）
- TTS / ASR 可配置后端（在线 edge-tts / 本地 ethan-tts）

### 待办

- `tools.md` 结构性拆分（当前全文注入，占 prompt 六成）
- Codex / Pi 的 Ethan 工具共享（各自有硬阻碍，详见内核文档）
- Android 端真机验证

---

## 📖 文档

- [架构](docs/architecture.md) · [agent loop](docs/agent-loop.md) · [缓存](docs/caching.md)
- [内核架构](docs/kernel-architecture.md) · [ACP](docs/acp.md) · [ACP server](docs/acp-server.md)
- [工具](docs/tools.md) · [技能](docs/skills.md) · [语义路由](docs/semantic-router.md)
- [记忆](docs/memory.md) · [知识库](docs/knowledge.md) · [定时任务](docs/scheduler.md)
- [渠道与接口](docs/interface.md) · [安装](docs/installation.md) · [快速上手](docs/quickstart.md)

---

## 📄 License

MIT License - 详见 [LICENSE](LICENSE)

---

**版本**: 1.0.0b6
**维护**: Ethan Team
