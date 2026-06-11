# ACP 集成设计文档

## 概述

ACP（Agent Communication Protocol）是 Ethan 委托复杂编码任务给专业 Coding Agent 的机制。

**设计原则**：Ethan 是通用个人 AI Agent，不专注于代码。遇到复杂编码任务时，自动检测并委托给本地 Coding Agent（Claude Code / OpenCode），把结果整合回对话。

---

## 架构

```
用户输入 "帮我实现 JWT 认证的 FastAPI 应用"
    │
    ▼
delegate_coding tool (agent 自动调用)
    │
    ▼
ethan/acp/__init__.py
    ├── is_complex_coding_task() → 复杂度判断
    └── delegate() → 调用本地 Coding Agent
            ├── Claude Code CLI: claude -p "..."
            └── OpenCode CLI: opencode run --prompt "..."
    │
    ▼
Coding Agent 执行，输出代码/修改文件
    │
    ▼
结果返回给 Ethan，整合进对话
```

---

## 复杂度判断（`is_complex_coding_task`）

启发式判断，两步过滤：

1. **简单问题优先排除**：
   - "什么是"、"解释"、"how does" → 直接回答，不委托

2. **复杂度信号 + 代码关键词**：
   - implement / refactor / create / 实现 / 重构 + code / python / api 等 → 委托

| 输入 | 判断 |
|------|------|
| "什么是 asyncio" | 简单 → 自己回答 |
| "implement REST API with JWT" | 复杂 → 委托 |
| "帮我重构这个文件里的代码" | 复杂 → 委托 |
| "explain how decorators work" | 简单 → 自己回答 |

---

## 支持的 Coding Agent

| Agent | 命令 | 安装 |
|-------|------|------|
| Claude Code | `claude` | https://claude.ai/code |
| OpenCode | `opencode` | https://opencode.ai |

优先级：Claude Code > OpenCode（按系统 PATH 检测）。可通过 `prefer` 参数指定。

---

## DelegateCodingTool

文件：`ethan/tools/builtin/acp.py`

LLM 可以直接调用的 tool：

```python
delegate_coding(
    task="Implement a user authentication system with JWT tokens...",
    working_dir="/path/to/project"  # optional
)
```

- timeout 默认 180 秒（coding tasks take time）
- 输出超 12000 字符自动截断
- 返回 `[agent-name] output` 格式

---

## 未来改进

- **更精准的复杂度判断**：通过 LLM 预判是否需要委托（替代启发式）
- **双向通信**：让 Coding Agent 在执行中回调 Ethan 澄清需求
- **上下文传递**：把 Ethan 的记忆（用户偏好、项目信息）传给 Coding Agent
- **结果审查**：Ethan 自动 review Coding Agent 的输出，提出改进建议
