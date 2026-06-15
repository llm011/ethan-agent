# 记忆系统设计文档

## 概述

Ethan 的记忆系统由四个独立层次构成，覆盖「短期上下文」到「长期知识」：

![记忆系统四层架构](./images/memory-overview.jpg)
<!-- diagram-source
```
┌──────────────────────────────────────────────────────────┐
│  第四层：情节记忆（Episodic Memory）                      │
│  每次 session 结束时写入一条摘要 + 关键词                 │
│  存储：~/.ethan/memory/episodes.json                     │
├──────────────────────────────────────────────────────────┤
│  第三层：用户画像（User Profile）                         │
│  结构化叙述性信息（目标、沟通方式、约定等）               │
│  存储：~/.ethan/memory/user_profile.md                   │
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
-->

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

- **延迟持久化**：CLI 启动时只在内存中构造 session 对象，发送第一条消息后才写入 DB
- **自动清理**：CLI 退出时调用 `cleanup_empty()` 删除没有消息的历史空 session
- **全文搜索**：`search(query)` 同时匹配 session 标题和消息内容（SQLite LIKE）

### 操作命令

```bash
ethan -r last                    # 恢复最近的 session
ethan -r s_20260611_1753_d139    # 恢复指定 ID（支持尾部短 ID）
ethan session list               # 列出最近 20 条
ethan session show <id>          # 查看消息摘要
ethan session delete <id>        # 删除
```

CLI 斜杠命令：
```
/sessions          列出最近会话
/resume <id>       恢复指定会话
/new               新建会话
```

---

## 第二层：分层工作记忆（Working Memory）

文件：`ethan/memory/working.py`，`ethan/memory/consolidator.py`，`ethan/memory/facts.py`

### 三层架构

![工作记忆三区结构](./images/memory-three-tier.jpg)
<!-- diagram-source
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
-->

### 滑动窗口机制

![滑动窗口机制](./images/memory-sliding-window.jpg)
<!-- diagram-source
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
-->

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

### 三路接口对齐

CLI、Web API (`/chat`)、Lark 三路接口均使用相同的 `WorkingMemory(hot_size=10)` 配置，不再存在截断策略不一致的问题。

### 配置

```python
MemoryConfig(
    hot_size=10,         # 热区保留轮数（CLI / API / Lark 统一）
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

## 第三层：用户画像（User Profile）

文件：`ethan/tools/builtin/profile_update.py`  
数据文件：`~/.ethan/memory/user_profile.md`

### 作用

存储无法压缩为单条 fact 的叙述性信息：个人目标、沟通风格、激励语、与 agent 的约定等。全量注入 system prompt（full/medium 路径），不参与置信度排名。

### 章节结构

文件以 Markdown 格式，分为固定五个章节：

| 章节 | 用途 |
|------|------|
| `身份与背景` | 职业、地区、角色等 |
| `目标与方向` | 长期目标、当前专注 |
| `工作与沟通方式` | 偏好的沟通风格、工作节奏 |
| `个人语言与激励` | 用户自创词汇、激励短语 |
| `与 Agent 的约定` | 特定场景下的行为约定 |

### 写入方式

Agent 通过 `profile_update` 工具主动更新，支持两种模式：

- `append`（默认）：在对应章节下追加一条 bullet
- `overwrite`：替换整个章节内容

```python
# 示例调用
await profile_update.run(
    section="目标与方向",
    entry="2026 年底前完成独立产品上线",
    mode="append",
)
```

---

## 第四层：情节记忆（Episodic Memory）

文件：`ethan/memory/episodic.py`  
数据文件：`~/.ethan/memory/episodes.json`

### 作用

每次 CLI 退出时（≥2 轮对话），自动将本次 session 的关键词 + 摘要写成一条 Episode，独立于 Working Memory 的滚动压缩保留下来。

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

## 主动写入记忆工具（Proactive Memory Write）

以上各层都依赖后台压缩提炼。三个工具让 Agent **即时、主动**将信息持久化，无需等待滑动窗口触发：

### `memory_write`

文件：`ethan/tools/builtin/memory_write.py`

将一条用户事实写入冷区（`facts.json`），置信度固定为 `0.95`，来源标记为 `agent_proactive`。

```python
# 触发场景：用户分享姓名、职业、偏好、一次性决策
await memory_write.run(
    content="用户在 Acme Corp 担任后端工程师",
    category="knowledge",  # preference | decision | knowledge | correction
)
```

### `procedure_write`

文件：`ethan/tools/builtin/procedure_write.py`

将一条行为规则写入 `ProcedureStore`（`procedures.json`），通过 `<behavioral_guidelines>` 注入 system prompt，每轮对话都生效。

```python
# 触发场景：用户说"以后回复都用英文"、"不要用韩语"
await procedure_write.run(
    rule="Always reply in Chinese",
    context="用户明确要求",
)
```

### `profile_update`

文件：`ethan/tools/builtin/profile_update.py`

更新 `user_profile.md` 中的指定章节（见 [三层架构](#三层架构)）。

---

## 置信度与记忆注入（Confidence & Injection）

### 置信度机制（Confidence）

每个保存在冷区（`facts.json`）的 Fact 都带有一个 `confidence` 分数（0.0 ~ 1.0）。

- **默认提炼（80%）**：日常闲聊中由后台自动提炼出的信息，默认置信度通常为 `0.8`。
- **主动写入（95%）**：通过 `memory_write` 工具直接写入的 fact，置信度固定为 `0.95`。
- **强信号加权（90%~95%）**：用户使用强烈指令（"记住"、"纠正"、"偏好"）时，Consolidator 赋予更高重要性评分。
- **动态更新与淘汰**：相同 fact 被反复命中则叠加置信度；低置信度且长期未访问的 fact 在存储空间不足时优先清理。

### 记忆注入机制（Injection）

`Agent._build_system()` 在每次 LLM 调用前执行：

1. 从 `FactStore` 读取 `confidence >= 0.3` 的活跃 fact
2. 按 `confidence`（降序）和 `last_accessed`（降序）双重排序
3. 取 top-15 注入 `<memory_context>`（fast 路径取 top-5）
4. `user_profile.md` 全量注入 `<user_profile>`（仅 full/medium 路径）

---

## 完整数据流

![记忆系统完整数据流](./images/memory-dataflow.jpg)
<!-- diagram-source
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
Agent.stream_chat(context) → LLM（注入实时时间 + user_profile + procedures）
    │
    │  LLM 主动调用工具（任意时机）：
    │   ├─ memory_write    → 立即写入 facts.json
    │   ├─ procedure_write → 立即写入 procedures.json
    │   └─ profile_update  → 立即写入 user_profile.md
    ▼
CLI 退出 → EpisodeStore.add() → episodes.json
          → SessionStore.cleanup_empty() → 清理空 session
```
-->

---

## 文件索引

| 文件 | 路径 | 说明 |
|------|------|------|
| Session DB | `~/.ethan/sessions.db` | 所有对话历史（SQLite） |
| Cold Facts | `~/.ethan/memory/facts.json` | 结构化长期 facts |
| Procedures | `~/.ethan/memory/procedures.json` | 行为规则 |
| User Profile | `~/.ethan/memory/user_profile.md` | 用户画像（叙述性） |
| Episodes | `~/.ethan/memory/episodes.json` | 历次 session 情节摘要 |
| Config | `~/.ethan/config.yaml` | 全局配置 |
