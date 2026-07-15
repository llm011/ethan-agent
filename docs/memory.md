# 记忆系统设计文档

## 概述

Ethan 的记忆系统由五个层次构成：

| 层 | 名称 | 定位 |
|----|------|------|
| 1 | Session | 完整对话历史持久化（SQLite） |
| 2 | Working Memory | 分层工作记忆（hot/warm/cold facts） |
| 3 | Profile | 用户画像（叙述性信息） |
| 4 | Episode | 情节记忆（session 摘要 + 关键词） |
| 5 | Dream/做梦 | 跨 session 信号采集 + 夜间沉淀（永久记忆） |

核心设计原则——**确定性与概率性分离**（借鉴 Palantir AIP）：记忆的写入触发和召回由系统规则确定性保证，LLM 只在"记什么内容"上做概率性判断。

![记忆系统四层架构](./images/memory-overview.jpg)
<!-- diagram-source
```
┌──────────────────────────────────────────────────────────┐
│  第五层：做梦（Dream）                                    │
│  每晚 0 点精炼白天信号 → embedding 去重 → memory.db      │
├──────────────────────────────────────────────────────────┤
│  第四层：情节记忆（Episodic Memory）                      │
│  每轮对话结束（user_turns ≥ 2）写入摘要 + 关键词          │
├──────────────────────────────────────────────────────────┤
│  第三层：用户画像（User Profile）                         │
│  结构化叙述性信息（目标、沟通方式、约定等）               │
├──────────────────────────────────────────────────────────┤
│  第二层：分层工作记忆（Working Memory）                   │
│  cold facts ← warm summary ← hot 最近 N 轮               │
├──────────────────────────────────────────────────────────┤
│  第一层：Session（对话历史）                              │
│  完整消息历史，永久保留（SQLite）                         │
└──────────────────────────────────────────────────────────┘
```
-->

---

## 架构亮点

1. **五层分明**：每层职责单一——Session 存原始历史、Working Memory 做滑动压缩、Profile 存叙述性画像、Episode 记 session 摘要、Dream 沉淀跨 session 洞察
2. **闭环设计**：`memory.db ← 沉淀 ← 信号` + `memory.db → 反写 → facts/playbook`，洞察沉淀后自动回流到对话召回链路
3. **fact_sync 桥梁**：沉淀前先把 facts.json/playbook.json 同步到 memory.db（type=fact_sync），insight 的 L2 去重天然覆盖已有 fact，无需手动遍历比对
4. **Heartbeat + Midnight 双循环**：心跳定期执行 facts 去重、画像压缩、成功路径抽取；午夜"做梦"精炼白天信号写入永久记忆
5. **Session 轮转**：心跳每次 tick 检查 sessions.db 大小，超过 10 MB 时 `VACUUM INTO` 归档到 `archive/sessions.{start}~{end}.db`，然后清空 active db
6. **确定性与概率性分离**：规则决定 when（信号检测、轮次触发），LLM 决定 what（记忆内容提炼）

---

## 第一层：Session（对话持久化）

文件：`ethan/memory/session.py`
数据库：per-user `sessions.db`

两张 SQLite 表：`sessions (id, title, model, created_at, updated_at)` + `messages (session_id, role, content, tool_calls, tool_call_id)`

关键行为：
- **延迟持久化**：第一条用户消息发出后才写入 DB，避免空 session 污染
- **自动清理**：退出时 `cleanup_empty()` 删除空 session
- **轮转归档**：超 10 MB → `VACUUM INTO archive/sessions.{start}~{end}.db` → 清空 active db

---

## 第二层：分层工作记忆（Working Memory）

文件：`ethan/memory/working.py`、`ethan/memory/consolidator.py`、`ethan/memory/facts.py`

### 三区结构

![工作记忆三区结构](./images/memory-three-tier.jpg)
<!-- diagram-source
```
┌─────────────────────────────────────────────┐
│ 冷区 (cold) — facts.json                    │
│ 跨 session 的 key facts，带 tags 语义召回    │
├─────────────────────────────────────────────┤
│ 温区 (warm) — 内存                           │
│ 当前 session 较早对话的 rolling summary      │
├─────────────────────────────────────────────┤
│ 热区 (hot) — 内存                            │
│ 最近 N 轮完整消息                            │
└─────────────────────────────────────────────┘
```
-->

### 滑动窗口

![滑动窗口机制](./images/memory-sliding-window.jpg)
<!-- diagram-source
```
每轮对话结束 → add_turn(user_msg, assistant_msg)
    │
    ├─ 热区超过 hot_size？→ 最老一轮移入压缩缓冲区
    ├─ 缓冲区攒够 compress_batch？→ 小模型 summary → 温区
    └─ 温区累积够 warm_capacity？→ 小模型提取 key facts → 冷区
```
-->

配置：`hot_size=10, compress_batch=5, warm_capacity=10`（CLI/Web/Lark/WeChat 统一）

### 后台抽取触发

| 阶段 | 触发条件 | 调模型 |
|------|----------|--------|
| Episode 写入 | `user_turns ≥ 2` | 否（规则提取） |
| Working Memory 压缩/抽取 | `user_turns % 5 == 0` | 是（lite 模型） |
| 跨 session 信号采集 | `user_turns % 10 == 0` | 是（lite 模型） |

### 信号检测与语义召回

文件：`ethan/memory/signals.py`

`detect_memory_signal(text)` 用确定性规则检测记忆信号（preference / correction / decision / fact），命中时注入 `<memory_signal>` hint 并激活 `memory_write` 工具。优先级：`preference > correction > decision > fact`。

`extract_keywords(text)` 按标点/空格切分 + 去停用字，用于 fact 写入时自动提取 tags 和召回时做相关性匹配。

**召回流程**：`FactStore.build_context_with_recall(query, max_facts)` → 提取 query 关键词 → 有 tag 交集的 fact 按 `relevance × 0.6 + confidence × 0.4` 排序 → 不足时按 confidence 降序补齐 → 命中的 fact 更新 `last_accessed`。

### 冷区 Facts（FactStore）

数据文件：`memory/facts.json`

每个 Fact 含：content、confidence（0.0-1.0）、source、category、tags、superseded 等字段。

- **置信度**：后台提炼默认 0.8，`memory_write` 主动写入 0.95，强信号加权 0.90~0.95
- **自动提取 tags**：`add()` 时自动调 `extract_keywords(content)`
- **矛盾检测**：旧 fact 标记 `superseded`
- **相似合并**：相似度 > 80% 时合并 tags、取更高 confidence

### 记忆注入

`Agent._build_system()` 每次 LLM 调用前：
1. `detect_memory_signal()` → 命中注入 `<memory_signal>` + 激活工具
2. `build_context_with_recall(query)` → top-15 facts 注入 `<memory_context>`（fast 路径 top-5）
3. `user_profile.md` 全量注入 `<user_profile>`（仅 full 路径）
4. `playbook.json` → `<behavioral_guidelines>`（纠正准则 + 成功路径）
5. FDE 建议 → `<proactive_suggestion>`（首轮、未拒绝的）

---

## 第三层：用户画像（User Profile）

文件：`ethan/core/profile.py`、`ethan/tools/builtin/profile_update.py`
数据文件：`memory/user_profile.md`

存储无法压缩为单条 fact 的叙述性信息，全量注入 system prompt。

**章节**：基础特征 / 身份与背景 / 目标与方向 / 工作与沟通方式 / 心理与情绪 / 个人语言与激励 / 与 Agent 的约定

**写入模式**：
- `append`：章节下追加 bullet
- `overwrite`：替换整个章节
- `merge`：与已有 bullet 相似/矛盾则替换，否则追加（后台抽取用此模式）

**心理画像抽取**：苏念·陪伴模式下 `consolidator.extract_cold()` 额外抽取 `[PROFILE_PSYCH]`，merge 写入「心理与情绪」章节。

---

## 第四层：情节记忆（Episodic Memory）

文件：`ethan/memory/episodic.py`
数据文件：`memory/episodes.json`

每轮对话结束后（`user_turns ≥ 2`），自动将 session 关键词 + 摘要写为一条 Episode。所有渠道统一生效。

**FDE 需求挖掘**：心跳任务 `_mine_recurring_needs()` 扫描近 30 个 episodes，lite 模型识别 ≥3 次的重复模式 → `suggestions.json`。下次对话首轮注入提醒，拒绝后不再重复。

---

## 第五层：跨 Session 信号采集 + "做梦"（夜间沉淀）

文件：`ethan/memory/daily_signals.py`、`ethan/memory/daily_consolidation.py`
数据文件：`memory/daily/<YYYYMMDD>.jsonl`（信号）、`memory/memory.db`（永久记忆）

> **为什么叫"做梦"**：人脑在睡眠时整理白天碎片、固化重要洞察。Ethan 每晚 0 点做同样的事——精炼白天信号、去重、写入永久记忆。

### 两级流程

```
第一级：实时信号采集（每 10 轮触发 collect_signals()）
    ├─ 读最近 5 个 session 的 user 消息
    ├─ lite 模型分析（重复/错误/成功路径）
    └─ 有效信号 → daily/<YYYYMMDD>.jsonl

第二级：每晚 0 点"做梦"（_midnight_loop → run_daily_consolidation）
    ├─ Step 0: fact_sync — 同步 facts.json/playbook.json 到 memory.db
    ├─ 读取昨日 JSONL 信号
    ├─ LLM 精炼去重（合并相似、排除噪音、≤10 条）
    ├─ embedding 去重：BGE-small-zh 512-dim 向量 L2 < 0.7 视为重复跳过
    ├─ 通过去重 → 写入 memory.db
    └─ 按 type 反写到 facts.json / playbook.json
        ├─ repetition/error → facts.json（confidence=0.75）
        └─ success_path → playbook.json
```

> **时间错位**：0 点触发时处理 `date.today() - 1 天` 的信号。

### 过程记忆（ProcedureStore）

文件：`ethan/memory/procedures.py`，数据文件：`memory/playbook.json`

存储两类内容：
- **纠正准则**：用户纠正 Agent 时写入（"不要做什么"）
- **成功路径**：心跳从历史 tool_steps 抽取高频成功路径（"这么做效果好"）

注入格式为 `<behavioral_guidelines>`，含准则和路径。

### memory.db 结构（sqlite-vec）

```sql
-- vec_items 表
id            TEXT PRIMARY KEY    -- "insight_20260714_a1b2c3d4" 或 "fact_sync_xxxx"
text          TEXT               -- 精炼后的记忆描述
embedding     FLOAT[512]         -- BGE-small-zh 512 维归一化向量
metadata      TEXT (JSON)        -- {"type": ..., "date": ..., "reflected": true/false}
last_accessed REAL               -- 最后被 search 命中的时间
```

**条目类型**：
- `insight_*`：做梦沉淀的洞察，永久保留
- `fact_sync_*` / `playbook_sync_*`：JSON 文件镜像，每次做梦前全量重建

**Embedding 引擎**：BGE-small-zh-v1.5 INT8 ONNX（24MB，中文专项优化）。不可用时回退 char n-gram hash（同 512 维，保证 schema 不变）。装依赖：`pip install 'ethan-agent[embedding]'`。

**去重阈值**：`L2_DEDUP_THRESHOLD = 0.7`（cos ≈ 0.755）。实测分布：同义改写 L2 均值 0.69，相似但不同主题 L2 均值 0.78，完全无关 L2 均值 1.16。阈值取在两者之间偏保守一侧——漏判代价低（多存几条），误判代价高（丢独特 insight 不可恢复）。

**永久保留策略**：insight 和 fact_sync 均豁免 LRU（每条 ≈ 1.5KB，万条仅 ~15MB）。sessions.db 膨胀由独立轮转机制处理。

**反写去重三层保障**：
1. fact_sync 同步 → L2 去重天然覆盖已有 fact
2. metadata `reflected` 标记 → 同一 insight 只反写一次
3. 目标文件 `add` 方法兜底（FactStore `_find_similar` / ProcedureStore 完全匹配）

---

## 主动写入记忆工具

三个工具让 Agent 即时、主动持久化信息，无需等待滑动窗口触发：

| 工具 | 文件 | 作用 |
|------|------|------|
| `memory_write` | `ethan/tools/builtin/memory_write.py` | 写入一条 fact 到 facts.json（confidence=0.95, source=agent_proactive, 自动提取 tags） |
| `procedure_write` | `ethan/tools/builtin/procedure_write.py` | 写入行为规则到 playbook.json，通过 `<behavioral_guidelines>` 注入 |
| `profile_update` | `ethan/tools/builtin/profile_update.py` | 更新 user_profile.md 指定章节（支持 append/overwrite/merge） |

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
    │   ├─ procedure_write → 立即写入 playbook.json
    │   └─ profile_update  → 立即写入 user_profile.md
    ▼
每轮对话结束 → _maybe_consolidate()（所有渠道触发）
    │
    ├─ user_turns ≥ 2 → EpisodeStore.add() → episodes.json（纯本地，无模型调用）
    │
    └─ user_turns % 5 == 0 → Consolidator 压缩/抽取（会调 LLM）

CLI 退出 → SessionStore.cleanup_empty()

心跳任务（定期）：
  ├─ _consolidate_facts()              # facts 去重合并
  ├─ _consolidate_profiles()           # 画像分区压缩
  ├─ _extract_decision_patterns()      # 从 tool_steps 抽取成功路径 → success_patterns
  └─ _mine_recurring_needs()           # 从 episodes 挖掘重复模式 → suggestions.json

每 10 轮用户消息（跨 session 信号采集）：
  collect_signals()
    ├─ 读最近 5 个 session 的 user 消息
    ├─ lite 模型一次分析（重复/错误/成功）
    └─ 有效信号 → daily/<YYYYMMDD>.jsonl

每晚 0 点"做梦"（_midnight_loop → run_daily_consolidation）：
    ├─ 读当日 JSONL
    ├─ LLM 精炼去重（≤10 条）
    ├─ embedding 去重（BGE L2 < 0.7 跳过）
    └─ 写入 memory.db（永久）
```
-->

---

## 测试验证

手动触发完整"做梦"流程（不必等到 0 点）：

```bash
# 1. 写入模拟信号
mkdir -p ~/.ethan/memory/daily
DATE=$(date +%Y%m%d)
cat >> ~/.ethan/memory/daily/${DATE}.jsonl << 'EOF'
{"type":"repetition","pattern":"用户经常要求以表格形式对比方案","count":4,"suggestion":"默认用表格对比","ts":1720000000}
{"type":"success_path","scenario":"代码审查","method":"先给结论再展开细节","ts":1720000001}
EOF

# 2. 通过 API 触发"做梦"
curl -X POST http://127.0.0.1:8900/api/memory/consolidate \
  -H "Authorization: Bearer <token>"
# 返回 {"ok": true, "added": 2}

# 3. 再次触发，验证去重
curl -X POST http://127.0.0.1:8900/api/memory/consolidate \
  -H "Authorization: Bearer <token>"
# 返回 {"ok": true, "added": 0}  ← embedding 去重生效

# 4. 查看沉淀记忆
curl http://127.0.0.1:8900/api/memory/insights \
  -H "Authorization: Bearer <token>"
```

**关键验证点**：第二次 `added: 0` 证明 embedding 去重生效。

---

## 文件索引

> **per-user 隔离**：所有记忆数据按 profile 隔离。default profile 落在 `~/.ethan/memory/`，命名 profile 落在 `~/.ethan/profiles/<name>/memory/`。

| 文件 | 路径（default profile） | 说明 |
|------|------|------|
| Session DB | `~/.ethan/sessions.db` | 对话历史（超 10 MB 自动轮转归档） |
| Session Archive | `~/.ethan/archive/sessions.{start}~{end}.db` | 轮转归档（按日期跨度命名） |
| Lark Sessions | `~/.ethan/lark_sessions.json` | 飞书 chat_id → session_id 映射 |
| Cold Facts | `~/.ethan/memory/facts.json` | 结构化长期 facts（含 tags） |
| Procedures | `~/.ethan/memory/playbook.json` | 行为准则 + 成功路径 |
| User Profile | `~/.ethan/memory/user_profile.md` | 用户画像（叙述性） |
| Episodes | `~/.ethan/memory/episodes.json` | session 情节摘要 |
| Suggestions | `~/.ethan/memory/suggestions.json` | FDE 主动建议 |
| Daily Signals | `~/.ethan/memory/daily/<YYYYMMDD>.jsonl` | 每日原始信号 |
| Memory DB | `~/.ethan/memory/memory.db` | 永久记忆（sqlite-vec） |
| Signals | `ethan/memory/signals.py` | 信号检测 + 关键词提取 + 相关性评分 |
| Daily Signals | `ethan/memory/daily_signals.py` | 跨 session 信号采集 |
| Daily Consolidation | `ethan/memory/daily_consolidation.py` | "做梦"逻辑 |
| Config | `~/.ethan/config.yaml` | 全局配置（非 per-user） |
