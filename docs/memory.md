# 记忆系统设计文档

## 概述

Ethan 的记忆系统分为两个维度：

1. **Session（会话管理）** — 每次对话的完整消息持久化
2. **分层记忆（WorkingMemory）** — 控制发送给 LLM 的 context，避免 token 爆炸

---

## Session 管理

文件：`ethan/memory/session.py`

### 核心概念

每次 `ethan` 启动时自动创建一个 Session。Session 包含：
- `id`: 格式 `s_YYYYMMDD_HHMM_xxxx`
- `title`: 自动从第一条用户消息生成（前 40 字）
- `model`: 创建时使用的模型
- `messages`: 完整消息历史

### 存储

SQLite（`~/.ethan/sessions.db`），两张表：
- `sessions`: 元信息（id, title, model, created_at, updated_at）
- `messages`: 消息记录（session_id, role, content, tool_calls, tool_call_id）

### 恢复会话

```bash
ethan -r last                    # 恢复最近的
ethan -r s_20260611_1753_d139    # 恢复指定 ID
```

REPL 内斜杠命令：
```
/sessions          列出最近会话
/resume <id>       恢复指定会话（支持短 ID 尾部匹配）
/new               新建会话
```

---

## 分层记忆（WorkingMemory）

文件：`ethan/memory/working.py`

### 三层架构

```
┌─────────────────────────────────────────────┐
│ 冷区 (cold)                                 │
│ 跨 session 的 key facts，如用户偏好          │
│ 存储：~/.ethan/memory/persistent.md         │
├─────────────────────────────────────────────┤
│ 温区 (warm)                                 │
│ 当前 session 较早对话的 rolling summary      │
│ 存储：内存中                                 │
├─────────────────────────────────────────────┤
│ 热区 (hot)                                  │
│ 最近 N 轮完整消息                            │
│ 存储：内存中                                 │
└─────────────────────────────────────────────┘
```

### 滑动窗口机制

```
每轮对话结束 → add_turn(user_msg, assistant_msg)
    │
    ├─ 热区是否超过 hot_size？
    │   └─ 是 → 最老一轮移入"压缩缓冲区"
    │
    ├─ 缓冲区是否攒够 compress_batch 轮？
    │   └─ 是 → 调用小模型做 summary → 合并进温区
    │
    └─ 温区是否累积够 warm_capacity 轮？
        └─ 是 → 调用小模型提取 key facts → 写入冷区
                                          → 温区精简
```

### 发给 LLM 的 context 组成

```python
memory.build_context() 返回:
[
    Message(user, "[长期记忆] 用户是开发者，偏好中文..."),
    Message(assistant, "好的，我已记住这些信息。"),
    Message(user, "[之前的对话摘要] 讨论了 X、决定了 Y..."),
    Message(assistant, "好的，我了解了之前的对话内容。"),
    # 热区完整消息（最近 N 轮）
    Message(user, "..."),
    Message(assistant, "..."),
]
```

### 配置

```python
MemoryConfig(
    hot_size=5,          # 热区保留轮数
    compress_batch=5,    # 攒够多少轮再压缩一次
    warm_capacity=20,    # 温区累积多少轮后提取冷区
)
```

未来计划写入 `~/.ethan/config.yaml`。

---

## 记忆压缩器（Consolidator）

文件：`ethan/memory/consolidator.py`

### 廉价模型自动推断

| 主模型 | 压缩用模型 |
|--------|-----------|
| claude-opus-* | claude-haiku-4-5 |
| claude-sonnet-* | claude-haiku-4-5 |
| gemini-*-pro | gemini-*-flash-lite |
| gemini-*-flash | gemini-*-flash-lite |
| gpt-4o / gpt-5* | gpt-4o-mini |

用户也可在 config 里手动指定 `summary_model`。

### 两个操作

1. **compress(messages, existing_summary)** → 生成/追加温区 summary
2. **extract_cold(warm_summary, existing_facts)** → 提取 key facts + 精简 summary

---

## 持久记忆

文件：`ethan/memory/persistent.py`

纯文件存储：`~/.ethan/memory/persistent.md`

冷区 key facts 写入此文件，跨所有 session 共享。每次启动时加载。

---

## 数据流全景

```
用户输入
    │
    ▼
Session Store (SQLite) ← 持久化每条消息
    │
    ▼
WorkingMemory.add_turn()
    │
    ├─ 热区满 → 溢出到缓冲区
    │               │
    │               └─ 缓冲满 → Consolidator.compress() [小模型]
    │                               │
    │                               └─ summary → 温区
    │                                               │
    │                                               └─ 温区满 → Consolidator.extract_cold() [小模型]
    │                                                               │
    │                                                               └─ key facts → persistent.md
    │
    ▼
WorkingMemory.build_context() → [冷区 + 温区 + 热区 + 当前输入]
    │
    ▼
Agent.stream_chat(context) → LLM 回复
```
