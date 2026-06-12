# 记忆系统设计文档

## 概述

Ethan 的记忆系统由三个独立层次构成，覆盖「短期上下文」到「长期知识」：

```
┌──────────────────────────────────────────────────────────┐
│  第三层：情节记忆（Episodic Memory）                      │
│  每次 session 结束时写入一条摘要 + 关键词                 │
│  存储：~/.ethan/memory/episodes.json                     │
├──────────────────────────────────────────────────────────┤
│  第二层：分层工作记忆（Working Memory）                   │
│  cold facts ← warm summary ← hot 最近 N 轮               │
│  存储：~/.ethan/memory/facts.json（冷区）+ 内存           │
├──────────────────────────────────────────────────────────┤
│  第一层：Session（对话历史）                              │
│  完整消息历史，永久保留                                   │
│  存储：~/.ethan/sessions.db（SQLite）                    │
└──────────────────────────────────────────────────────────┘
```

---

## 第一层：Session（对话持久化）

文件：`ethan/memory/session.py`  
数据库：`~/.ethan/sessions.db`

### 数据结构

两张 SQLite 表：

```sql
sessions  (id, title, model, created_at, updated_at)
messages  (session_id, role, content, tool_calls, tool_call_id)
```

- `id`：格式 `s_YYYYMMDD_HHMM_xxxx`，启动时生成
- `title`：自动从第一条用户消息前 40 字提取
- 消息在用户发出第一条后才真正写入 DB（避免空 session 污染）

### 关键行为

- **延迟持久化**：REPL 启动时只在内存中构造 session 对象，发送第一条消息后才写入 DB
- **自动清理**：REPL 退出时调用 `cleanup_empty()` 删除没有消息的历史空 session
- **全文搜索**：`search(query)` 同时匹配 session 标题和消息内容（SQLite LIKE）

### 操作命令

```bash
ethan -r last                    # 恢复最近的 session
ethan -r s_20260611_1753_d139    # 恢复指定 ID（支持尾部短 ID）
ethan session list               # 列出最近 20 条
ethan session show <id>          # 查看消息摘要
ethan session delete <id>        # 删除
```

REPL 内斜杠命令：
```
/sessions          列出最近会话
/resume <id>       恢复指定会话
/new               新建会话
```

---

## 第二层：分层工作记忆（Working Memory）

文件：`ethan/memory/working.py`，`ethan/memory/consolidator.py`，`ethan/memory/facts.py`

### 三层架构

```
┌─────────────────────────────────────────────┐
│ 冷区 (cold)                                 │
│ 跨 session 的 key facts，如用户偏好、身份    │
│ 存储：~/.ethan/memory/facts.json            │
│ 结构：[{content, confidence, category,      │
│          source, created_at, superseded}]   │
├─────────────────────────────────────────────┤
│ 温区 (warm)                                 │
│ 当前 session 较早对话的 rolling summary      │
│ 存储：内存中（session 结束后丢弃）           │
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
    ├─ 热区超过 hot_size？
    │   └─ 是 → 最老一轮移入压缩缓冲区
    │
    ├─ 缓冲区攒够 compress_batch 轮？
    │   └─ 是 → 小模型生成 summary → 合并进温区
    │
    └─ 温区累积够 warm_capacity 轮？
        └─ 是 → 小模型提取 key facts → 写入冷区（facts.json）
                                      → 温区精简
```

### 发给 LLM 的 context 结构

```python
memory.build_context() 返回:
[
    Message(user,      "[长期记忆]\n用户是开发者，偏好中文..."),
    Message(assistant, "好的。"),
    Message(user,      "[对话摘要]\n之前讨论了 X，决定了 Y..."),
    Message(assistant, "好的。"),
    # 热区：最近 N 轮完整消息
    Message(user,      "..."),
    Message(assistant, "..."),
    # 当前输入
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

### 压缩模型路由（Consolidator）

| 主模型 | 压缩用模型 |
|--------|-----------|
| claude-opus-* | claude-haiku-4-5 |
| claude-sonnet-* | claude-haiku-4-5 |
| gemini-*-pro | gemini-*-flash-lite |
| gemini-*-flash | gemini-*-flash-lite |
| gpt-4o / gpt-5* | gpt-4o-mini |

---

## 第三层：情节记忆（Episodic Memory）

文件：`ethan/memory/episodic.py`  
数据文件：`~/.ethan/memory/episodes.json`

### 作用

每次 REPL 退出时（≥2 轮对话），自动将本次 session 的关键词 + 摘要写成一条 Episode，独立于 Working Memory 的滚动压缩保留下来。

### 数据结构

```json
{
  "session_id": "s_20260612_0151_b18c",
  "summary": "你好，我是张三，今天是来测试 多轮记忆能力...",
  "timestamp": 1749744812.3,
  "model": "gemini-2.5-flash-lite",
  "turn_count": 18,
  "keywords": ["张三", "测试", "记忆", "科幻", "苹果"]
}
```

### 检索

支持关键词搜索（对 summary + keywords 做词频打分），可按时间倒序取最近几条。目前用于日志回顾，尚未接入 LLM 上下文召回（计划中）。

---

## 完整数据流

```
用户输入
    │
    ▼
Session Store (SQLite) ←─── 第一条消息时才真正写入 DB
    │
    ▼
WorkingMemory.add_turn()
    │
    ├─ 热区满 → 溢出缓冲区
    │               │
    │               └─ 缓冲满 → Consolidator.compress() ──→ 温区 summary
    │                                                           │
    │                                                           └─ 温区满 → Consolidator.extract_cold()
    │                                                                           │
    │                                                                           └─ facts.json（冷区）
    │
    ▼
WorkingMemory.build_context()
    = [冷区 facts] + [温区 summary] + [热区完整消息] + [当前输入]
    │
    ▼
Agent.stream_chat(context) → LLM（每次都注入实时时间）
    │
    ▼
REPL 退出 → EpisodeStore.add() → episodes.json
          → SessionStore.cleanup_empty() → 清理空 session
```

---

## 文件索引

| 文件 | 路径 | 说明 |
|------|------|------|
| Session DB | `~/.ethan/sessions.db` | 所有对话历史（SQLite） |
| Cold Facts | `~/.ethan/memory/facts.json` | 结构化长期 facts |
| Episodes | `~/.ethan/memory/episodes.json` | 历次 session 情节摘要 |
| Config | `~/.ethan/config.yaml` | 全局配置 |
