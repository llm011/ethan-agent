# 记忆系统设计文档

## 概述

Ethan 的记忆系统由四个独立层次构成，覆盖「短期上下文」到「长期知识」。系统遵循**确定性与概率性分离**原则（借鉴 Palantir AIP）：记忆的写入触发和召回由系统规则确定性保证，LLM 只在"记什么内容"上做概率性判断。

![记忆系统四层架构](./images/memory-overview.jpg)
<!-- diagram-source
```
┌──────────────────────────────────────────────────────────┐
│  第四层：情节记忆（Episodic Memory）                      │
│  每次 session 结束时写入一条摘要 + 关键词                 │
│  心跳任务定期扫描，挖掘 ≥3 次的重复模式 → 主动建议        │
│  存储：~/.ethan/memory/episodes.json                     │
├──────────────────────────────────────────────────────────┤
│  第三层：用户画像（User Profile）                         │
│  结构化叙述性信息（目标、沟通方式、约定等）               │
│  存储：~/.ethan/memory/user_profile.md                   │
├──────────────────────────────────────────────────────────┤
│  第二层：分层工作记忆（Working Memory）                   │
│  cold facts ← warm summary ← hot 最近 N 轮               │
│  冷区 facts 带 tags，支持按当前对话关键词语义召回          │
│  存储：~/.ethan/memory/facts.json（冷区）+ 内存           │
├──────────────────────────────────────────────────────────┤
│  第一层：Session（对话历史）                              │
│  完整消息历史，永久保留                                   │
│  存储：~/.ethan/sessions.db（SQLite）                    │
└──────────────────────────────────────────────────────────┘
-->

---

## 信号检测与主动召回

这是记忆系统的"神经系统"，解决"用户不说'记住'就不记忆"的问题。

### 设计哲学

| 层面 | 职责 | 实现方式 |
|------|------|----------|
| 确定性层 | **何时**写入/召回记忆 | 规则驱动，100% 命中 |
| 概率性层 | **记什么**内容 | LLM 判断 |

### 信号检测器（Signal Detector）

文件：`ethan/memory/signals.py`

`detect_memory_signal(text)` 用确定性规则检测用户消息中的记忆信号，命中时注入 `<memory_signal>` hint 并激活 `memory_write` 工具——不再依赖 LLM 自觉调用。

```
用户消息
    │
    ▼
detect_memory_signal(text)
    │
    ├─ preference  (喜欢/偏好/习惯/always/never...)
    ├─ correction  (不对/错了/应该是...)
    ├─ decision    (决定/打算/计划...)
    └─ fact        (我叫/我在/我是...)
    │
    ▼
命中 → 注入 <memory_signal> hint + 激活 memory_write 工具
未命中 → 不注入，LLM 正常处理
```

优先级：`preference > correction > decision > fact`（偏好和纠正最重要）

### 关键词提取与语义召回

`extract_keywords(text)` 支持 CJK 2-4 字滑窗 + Latin 分词，用于：
- Fact 写入时自动提取 `tags`（系统确定性保证，不依赖调用方）
- 召回时提取当前对话关键词，与 fact tags 做相关性匹配

`score_relevance(query_keywords, tags)` 计算交集分数，用于 fact 召回排序。

### 召回流程

```
当前用户消息
    │
    ▼
extract_keywords(query) → query_keywords
    │
    ▼
FactStore.build_context_with_recall(query, max_facts)
    │
    ├─ 有 tag 交集的 fact → relevance × 0.6 + confidence × 0.4 排序
    └─ 无交集的 fact → 按 confidence 降序补齐
    │
    ▼
注入 <memory_context>（命中的 fact 更新 last_accessed）
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
│ 每个 fact 带 tags，支持按关键词语义召回      │
│ 存储：~/.ethan/memory/facts.json            │
│ 结构：[{content, confidence, category,      │
│          source, created_at, superseded,    │
│          tags}]                             │
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

CLI、Web API (`/chat`)、Lark、WeChat 四路接口均使用相同的 `WorkingMemory(hot_size=10)` 配置，且都在对话结束后触发后台记忆抽取（`_maybe_consolidate`），不再存在截断策略不一致的问题。

### 配置

```python
MemoryConfig(
    hot_size=10,         # 热区保留轮数（CLI / API / Lark / WeChat 统一）
    compress_batch=5,    # 攒够多少轮再压缩一次
    warm_capacity=10,    # 温区累积多少轮后提取冷区（原值 20，已降低以减少短对话记忆丢失）
)
```

### 后台抽取触发条件

| 渠道 | 触发条件 |
|------|----------|
| Web API | `user_turns % 5 != 0` 时跳过（原值 `% 10`，已降低） |
| CLI (REPL) | session 退出时 |
| Lark | 正常结束路径 `store.close()` 后 |
| WeChat | `store.close()` 后 |

### 压缩模型路由（Consolidator）

| 主模型 | 压缩用模型 |
|--------|-----------|
| claude-opus-* | claude-haiku-4-5 |
| claude-sonnet-* | claude-haiku-4-5 |
| gemini-*-pro | gemini-*-flash-lite |
| gemini-*-flash | gemini-*-flash-lite |
| gpt-4o / gpt-5* | gpt-4o-mini |

---

## 冷区 Facts（FactStore）

文件：`ethan/memory/facts.py`
数据文件：`~/.ethan/memory/facts.json`

### 数据结构

```python
@dataclass
class Fact:
    content: str           # 内容
    confidence: float      # 置信度 (0.0-1.0)
    source: str            # 来源 session ID
    category: str          # preference | decision | knowledge | correction
    created_at: float      # 创建时间
    last_accessed: float   # 最后访问时间
    superseded: bool       # 是否被新 fact 取代
    tags: list[str]        # 关键词标签，用于语义召回
```

### 写入

- **自动提取 tags**：`add()` 时若未传 `tags`，自动调 `extract_keywords(content)` 提取
- **矛盾检测**：新 fact 与已有 fact 矛盾时，旧 fact 标记为 `superseded`
- **相似合并**：与已有 fact 相似度 > 80% 时，合并 tags、取更高 confidence

### 召回

`build_context_with_recall(query, max_facts)` 按当前对话关键词召回相关 facts：
1. 提取 query 关键词
2. 有 tags 交集的 fact 按 `relevance × 0.6 + confidence × 0.4` 排序
3. 不足时用 confidence 降序补齐
4. 命中的 fact 更新 `last_accessed`

---

## 第三层：用户画像（User Profile）

文件：`ethan/core/profile.py`（共享读写）、`ethan/tools/builtin/profile_update.py`（工具）
数据文件：`~/.ethan/memory/user_profile.md`

### 作用

存储无法压缩为单条 fact 的叙述性信息：个人目标、沟通风格、激励语、与 agent 的约定，以及用户的基础特征与心理情绪特征。全量注入 system prompt（full/medium 路径），不参与置信度排名。

### 章节结构

| 章节 | 用途 |
|------|------|
| `基础特征` | 名字、年龄、性格、兴趣等稳定身份信息（建议用户在「我的画像」设置页填写，避免后台抽错） |
| `身份与背景` | 职业、地区、角色等 |
| `目标与方向` | 长期目标、当前专注 |
| `工作与沟通方式` | 偏好的沟通风格、工作节奏 |
| `心理与情绪` | 情绪模式、压力源、什么能安抚 ta、重要内心感受、价值观 |
| `个人语言与激励` | 用户自创词汇、激励短语 |
| `与 Agent 的约定` | 特定场景下的行为约定 |

### 写入方式

Agent 通过 `profile_update` 工具主动更新，支持三种模式：

- `append`（默认）：在对应章节下追加一条 bullet
- `overwrite`：替换整个章节内容
- `merge`：与已有 bullet 相似/矛盾则替换该条（UPDATE），否则追加（ADD）——后台自动抽取用此模式，避免堆砌重复

### 后台自动抽取（心理画像）

`consolidator.extract_cold()` 除了抽取 `key_facts`，还会在**苏念·陪伴倾听模式**下额外抽取 `[PROFILE_PSYCH]`——用户的情绪/困扰/压力源/安抚方式/内心感受/价值观，经 `profile.apply_extraction()` 以 merge 方式写入「心理与情绪」章节。工作助手模式不抽取心理画像。基础特征不靠后台推断，由用户在设置页填写或对话中明确告知后由 agent 写入。

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

### FDE 需求挖掘

心跳任务 `_mine_recurring_needs()` 定期扫描近 30 个 episodes，用 lite 模型识别 ≥3 次的重复模式，写入 `~/.ethan/memory/suggestions.json`。下次对话首轮注入 `<proactive_suggestion>` 提醒 Agent 自然提起。用户拒绝后标记 `rejected`，不再重复。

---

## 过程记忆（ProcedureStore）

文件：`ethan/memory/procedures.py`
数据文件：`~/.ethan/memory/procedures.json`

### 作用

存储 Agent 从用户纠正中学习的行为准则，以及从历史会话中抽取的成功路径，注入 `<behavioral_guidelines>` 作为正反馈。

### 两类内容

**纠正准则**（Procedures）：用户纠正 Agent 时写入，记"不要做什么"。

**成功路径**（Success Patterns）：心跳任务从历史 session 的 tool_steps 中抽取高频成功路径，记"这么做效果好"。

```python
@dataclass
class SuccessPattern:
    scenario: str           # 场景描述（如"查京东订单"）
    tool_sequence: list[str]  # 工具调用序列
    success_count: int      # 成功次数（相同 scenario 累加）
    last_used: float        # 最后使用时间
```

### 注入格式

```
Behavioral guidelines (learned from past corrections):
- 不要用浏览器模拟登录

Success patterns (similar scenarios worked well before):
- 查京东订单: shell:jd_query → file_write:save (2/2 成功)
```

### 旧格式兼容

`_load()` 兼容两种格式：
- 旧格式：纯 `list[dict]` → 加载为 procedures，success_patterns 为空
- 新格式：`{"procedures": [...], "success_patterns": [...]}`

---

## 主动写入记忆工具（Proactive Memory Write）

以上各层都依赖后台压缩提炼。三个工具让 Agent **即时、主动**将信息持久化，无需等待滑动窗口触发：

### `memory_write`

文件：`ethan/tools/builtin/memory_write.py`

将一条用户事实写入冷区（`facts.json`），置信度固定为 `0.95`，来源标记为 `agent_proactive`。写入时自动提取 tags。

```python
# 触发场景：信号检测器命中 preference/decision/fact，或 LLM 主动判断
await memory_write.run(
    content="用户在 Acme Corp 担任后端工程师",
    category="knowledge",  # preference | decision | knowledge | correction
)
```

### `procedure_write`

文件：`ethan/tools/builtin/procedure_write.py`

将一条行为规则写入 `ProcedureStore`（`procedures.json`），通过 `<behavioral_guidelines>` 注入 system prompt，每轮对话都生效。

```python
# 触发场景：信号检测器命中 correction，或 LLM 主动判断
await procedure_write.run(
    rule="Always reply in Chinese",
    context="用户明确要求",
)
```

### `profile_update`

文件：`ethan/tools/builtin/profile_update.py`

更新 `user_profile.md` 中的指定章节（见 [用户画像](#第三层用户画像user-profile)）。

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

1. 提取当前用户消息，用 `detect_memory_signal()` 检测记忆信号
2. 用 `build_context_with_recall(query=当前消息)` 召回相关 facts（按 relevance + confidence 排序）
3. 取 top-15 注入 `<memory_context>`（fast 路径取 top-5）
4. `user_profile.md` 全量注入 `<user_profile>`（仅 full/medium 路径）
5. `procedures.json` 注入 `<behavioral_guidelines>`（含纠正准则 + 成功路径）
6. 信号命中时注入 `<memory_signal>` hint + 激活 memory_write 工具
7. 有未拒绝的 FDE 建议时，首轮注入 `<proactive_suggestion>`

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
Agent._build_system()
    │
    ├─ detect_memory_signal(last_user_text) → 信号检测
    │   └─ 命中 → 注入 <memory_signal> + 激活 memory_write
    │
    ├─ FactStore.build_context_with_recall(query=当前消息)
    │   └─ 按 tags 相关性召回 facts → <memory_context>
    │
    ├─ ProcedureStore.build_context()
    │   └─ 纠正准则 + 成功路径 → <behavioral_guidelines>
    │
    ├─ _build_suggestion_hint()
    │   └─ 未拒绝的 FDE 建议 → <proactive_suggestion>（首轮）
    │
    └─ user_profile.md → <user_profile>
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
    │                                                                           └─ facts.json（冷区，自动提取 tags）
    │
    ▼
Agent.stream_chat(context) → LLM
    │
    │  LLM 调用工具（信号命中或主动判断）：
    │   ├─ memory_write    → 立即写入 facts.json（带 tags）
    │   ├─ procedure_write → 立即写入 procedures.json
    │   └─ profile_update  → 立即写入 user_profile.md
    ▼
对话结束 → _maybe_consolidate()（Web/Lark/WeChat 均触发）
    │
    ▼
CLI 退出 → EpisodeStore.add() → episodes.json
          → SessionStore.cleanup_empty()

心跳任务（定期）：
  ├─ _consolidate_facts()              # facts 去重合并
  ├─ _consolidate_profiles()           # 画像分区压缩
  ├─ _extract_decision_patterns()      # 从 tool_steps 抽取成功路径 → success_patterns
  └─ _mine_recurring_needs()           # 从 episodes 挖掘重复模式 → suggestions.json
```
-->

---

## 文件索引

| 文件 | 路径 | 说明 |
|------|------|------|
| Session DB | `~/.ethan/sessions.db` | 所有对话历史（SQLite） |
| Cold Facts | `~/.ethan/memory/facts.json` | 结构化长期 facts（含 tags） |
| Procedures | `~/.ethan/memory/procedures.json` | 行为准则 + 成功路径 |
| User Profile | `~/.ethan/memory/user_profile.md` | 用户画像（叙述性） |
| Episodes | `~/.ethan/memory/episodes.json` | 历次 session 情节摘要 |
| Suggestions | `~/.ethan/memory/suggestions.json` | FDE 主动建议 |
| Signals | `ethan/memory/signals.py` | 信号检测器 + 关键词提取 + 相关性评分 |
| Config | `~/.ethan/config.yaml` | 全局配置 |
