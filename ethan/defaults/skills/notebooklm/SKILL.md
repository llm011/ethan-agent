---
name: notebooklm
description: >
  TRIGGER WHEN: 用户提到“NotebookLM”、“询问我的文档”、“查询笔记本”、“添加文档到库”或提供 NotebookLM URL 时。
  利用浏览器自动化技术直接从 Google NotebookLM 获取基于源文档、带引用的回答，有效减少幻觉。
version: 1.3.0
source: https://github.com/PleasePrompto/notebooklm-skill
license: MIT
upstream_commit: eea5cb28ba79ab8b078a1eaa44ce9ec44f75dbf8
---

# NotebookLM 调研助手 (NotebookLM Assistant)

本技能通过自动化操作 Google NotebookLM，实现基于您自有文档的高保真问答。

## 🔐 密钥配置 (Secrets)

本技能不写死任何 Google 账号、cookie 或 token 值，所有敏感信息从用户级环境配置 `~/.ethan/.env` 读取。

支持的环境变量（未设置时使用默认值，不影响首次 `setup` 流程）：

| 变量名 | 用途 | 默认值 |
|--------|------|--------|
| `NOTEBOOKLM_BROWSER_STATE_DIR` | 浏览器 profile / cookie 持久化目录 | `<skill>/data/browser_state` |
| `NOTEBOOKLM_STATE_FILE` | 已登录会话 state.json 路径 | `<NOTEBOOKLM_BROWSER_STATE_DIR>/state.json` |
| `NOTEBOOKLM_AUTH_INFO_FILE` | 账号元信息（邮箱/最后登录时间）存放路径 | `<skill>/data/auth_info.json` |
| `NOTEBOOKLM_LIBRARY_FILE` | 本地笔记本索引缓存路径 | `<skill>/data/library.json` |
| `NOTEBOOKLM_HEADLESS` | 常规查询是否使用 Headless 模式（`1`/`0`） | `1` |

> 首次使用时，若 `~/.ethan/.env` 不存在或上述变量未设置，技能会自动回落到 `<skill>/data/` 默认目录，并由 `auth_manager.py setup` 弹出可见浏览器引导用户手动登录 Google。**严禁在 SKILL.md 或脚本中硬编码任何账号、cookie、token 值。**

## 🛡️ 核心工作流 (Workflow)

依赖通过 `uv run --with` 临时注入，无需维护本地 `.venv`：

```bash
# 一次性安装浏览器内核（仅首次需要）
uv run --with patchright==1.55.2 --with python-dotenv==1.0.0 \
  python -m patchright install chrome
```

### 1. 认证管理 (Authentication)
- **状态检查**: `uv run --with patchright --with python-dotenv python scripts/auth_manager.py status`。
- **首次登录**: 若未登录，运行 `uv run --with patchright --with python-dotenv python scripts/auth_manager.py setup` (此步骤会弹出可见浏览器，需用户手动扫码/登录)。

### 2. 笔记本管理 (Library)
- **列出列表**: `uv run --with patchright --with python-dotenv python scripts/notebook_manager.py list`。
- **智能添加**: 提供 URL 后，先询问笔记本内容，再使用 `notebook_manager.py add` 入库。

### 3. 提问与追问 (Ask & Follow-up)
- **执行提问**: `uv run --with patchright --with python-dotenv python scripts/ask_question.py --question "问题" --notebook-id ID`。
- **追问铁律**: 每个回答后必须分析是否存在信息差，若有则自动发起追问，直至信息完整。

> 💡 也可通过 `scripts/run.py` 包装器统一调用：`uv run --with patchright --with python-dotenv python scripts/run.py <script>.py [args]`。

## 避坑指南 (Gotchas)

- **Wrapper 铁律**: **严禁直接运行脚本**。必须通过 `uv run --with patchright --with python-dotenv python scripts/<script>.py` 或 `scripts/run.py` 包装器调用，以确保依赖隔离。
- **可见性**: 仅在 `setup` 认证时需要可见浏览器，常规查询建议使用 Headless 模式。
- **额度限制**: 免费账号每日约 50 次查询限制。
- **追问机制**: 回答末尾出现“Is that ALL you need?”时，Agent 必须进行补漏追问。

## 渐进式参考 (References)
- **API 详述**: 阅读 `references/api_reference.md` 获取完整的脚本参数表。
- **故障排查**: 查阅 `references/troubleshooting.md` 解决 ModuleNotFoundError 或浏览器崩溃。
- **进阶模式**: 参考 `references/usage_patterns.md` 学习复杂调研工作流。
