# 记忆系统设计文档

## 概述

Ethan 的长期记忆以**结构化记忆管道**为核心（`memory.db` 是唯一事实源），
周围保留四个各有独立消费者的卫星组件：

| 组件 | 定位 | 存储 |
|----|------|------|
| **结构化记忆** | 长期用户事实的唯一事实源：提取→准入→召回→夜间沉淀 | `memory.db`（SQLite 六表 + 向量索引） |
| Session | 完整对话历史持久化 | `sessions.db` |
| Working Memory | 会话内上下文压缩（REPL 进程内 rolling summary） | 内存（易失） |
| User Profile | 叙述性用户画像（用户/agent 手写层，Web 可编辑） | `user_profile.md` |
| Playbook | agent 自身行为规范（从纠正中学习） | `playbook.json` |

核心设计原则——**确定性与概率性分离**：记忆的写入触发、准入决策和召回由
系统规则确定性保证；LLM 只在"记什么内容"上做概率性提议。embedding 语义
相似度也只用于"配对建议/召回通道"，merge/supersede 决策规则全部确定。

> 历史说明：flat-facts 系统（`facts.json` / `FactStore` / `extract_cold`）
> 已于 2026-07 退役，存量数据由 `legacy_migration` 一次性迁移进 memories 表。
> Episode 链路（`episodic.py` / `episodes.json` / `_mine_recurring_needs` /
> `_build_suggestion_hint`）已于 2026-07 退役，重复模式挖掘由结构化记忆
> 管道的跨 session 复评负责。
> 新旧对比与融合决策见 [memory/unification.md](./memory/unification.md)。

---

## 架构总览

```
写路径（每轮对话后 _maybe_consolidate）:
  每 3 轮: StructuredMemoryExtractor → candidates → AdmissionPolicy → memories
  修正关键词触发: 检测到"不是/其实/纠正"等关键词时立即触发，避免跨轮次修正无法及时更新
  agent主动: memory_write（显式传 memory_type/dimension）→ explicit/corrected 候选 → 立即准入
            profile_update → user_profile.md    procedure_write → playbook.json

夜间统一沉淀（0 点,run_nightly_consolidation,做梦与每日沉淀合并）:
  ① 结构化每日沉淀:兜底扫描短会话（user_turns<3 但内容有价值）
    → pending 跨 session 复评 → TTL 过期 → general/companion 分域日摘要
  ② 重建 memory 向量索引（自愈漂移）
  ③ 做梦（daily_consolidation）:从 memory.db 读取当日 active 记忆（已替代 daily/*.jsonl）
    → _sync_corpus_to_memory_db 把 memories/playbook 同步进向量库作为去重底库
    → LLM 精炼 insight → embedding L2 去重 → insight 入向量库
    → 仅 success_path 反写 playbook.json;其它类型仅入库不反写

读路径（唯一入口,每次对话构建 system prompt）:
  <memory_context>  ← recall:FTS5/LIKE 精确通道
                      + BGE 向量语义通道,RRF(k=60) 融合;无命中回退 importance
  <user_profile>    ← 手写画像层      <behavioral_guidelines> ← playbook
```

> 历史变更：
> - `collect_signals` / `daily/*.jsonl` 信号链路已于 2026-07 退役，
>   做梦输入源直接从 `memory.db` 读取当日 active 记忆（消除存储分裂）。
> - `TYPE_MEMORY_MAP` 已删除——`repetition`/`error` 类型不再反写为候选走准入，
>   只入向量库；仅 `success_path` 反写 `playbook.json`。
> - `memory_write` 解耦 `_KEYWORD_RULES` 硬编码：agent 显式传 `memory_type`/`dimension`
>   时直接采用，未传时按 `category` 走最粗粒度兜底。

## 提取（LLM 只提议）

`ethan/memory/extractors.py`：每 5 个用户轮次，对上次水位线之后的消息做
增量提取（1 次主模型调用，JSON 非法时修复重试 1 次，`max_tokens=16384`）。

硬性校验（不过即弃）：
- **quote 溯源**：每条候选的 quote 必须是所指用户消息的精确子串
- **维度白名单**：由维度注册表生成（见下），`custom.*` 兜底维度强制 observed
- 个人事实类证据必须来自 user 消息；companion 类型仅陪伴模式可产出；
  companion 诊断词表（抑郁/焦虑症/PTSD 等 25 词）硬拒绝
- observed 候选 confidence 封顶 0.6

### 维度注册表（`ethan/memory/dimensions.py`）

64 个维度 × 7 个 memory_type（personal_information 14 / preference 11 /
activity 7 / decision 8 / relationship 3 / methodology 11 / companion 10），
声明式注册：每个类型带"角色定位"，每个维度带判别边界 + 正例。
**白名单校验和提取 prompt 的维度段落都从注册表生成**，二者严格一致——
新增维度只需在注册表加一行。methodology 候选必须带
`scenario/trigger/steps` 结构体。

实测效果（120 条 golden live A/B，同 runner 同模型）：注册表 prompt
P 0.94→0.99、R 0.56→0.74、F1 0.70→0.84（此前 prompt 只列了 ~19/64 维）。

## 准入（代码决定）

`ethan/memory/admission.py` 真值表：

| evidence_level | 无既有 active | 有既有（同 key+scope+domain） |
|---|---|---|
| explicit | 建 active（conf≥0.95） | 内容一致→补证据；发散→supersede |
| corrected | 建 active（conf=1.0） | 一律 supersede |
| inferred | 建 active | 补证据 merge |
| observed | **留 pending** | ≥2 独立 session 复证才晋升（conf≤0.85） |

observed 模式可用 `ETHAN_ADMISSION_OBSERVED_MODE=accrual` 切换为：
单 session 即建 active 但 confidence 封 0.5（默认 gate，A/B 由 golden 评测定）。

### 语义配对（embedding 只做建议）

准入时先查同 scope+domain 的向量近邻（L2≤0.7）：
- explicit/corrected + 同 dimension + 内容发散 → supersede（继承 key 四元组；
  解决"住在深圳"与"家在深圳南山"各存一条的问题）
- inferred / 跨 dimension / 内容一致 → 只补证据 merge
- observed → 仍须先过 ≥2 session 门，晋升时并入近邻而非新建
- companion 域不参与语义配对

所有配对决策写入 `processing_reason`（`semantic_superseded:l2=…` 等）可审计。

## 召回（混合双通道）

`ethan/memory/recall.py`：system prompt 唯一的长期记忆块 `<memory_context>`。

- **精确通道**：FTS5 bm25（零命中落 LIKE 兜底——unicode61 对 CJK 无分词）
- **语义通道**：BGE 向量近邻（补齐 CJK 与语序变换/同义改写）
- **融合**：RRF(k=60) 排名倒数求和，importance/confidence 决胜
- 无命中回退 importance top-N（身份类事实始终可用）
- companion 域仅陪伴模式召回；restricted 永不注入；forget 同步删除向量索引

## 夜间沉淀与做梦

合并为单一编排 `run_nightly_consolidation`（每晚 0 点遍历全部 profile）：
顺序有意为之——结构化先跑，当日新准入的记忆进入做梦的向量去重底库，
insight 不会与刚提取的记忆重复反写。两步各自保留独立的
`consolidation_jobs` 记录（幂等，失败可重试不推进边界）。

做梦（`daily_consolidation.py`）：
- **输入源**：直接从 `memory.db` 读取当日 active 记忆（最多 15 条），
  替代旧的 `daily/*.jsonl` 信号文件——5 轮实时抽取写入 memory.db →
  0 点做梦直接读 memory.db，消除存储分裂。
- **去重底库**：`_sync_corpus_to_memory_db` 把 memories 表 active 记忆 +
  playbook 的 success_patterns 全量同步进向量库（`type=fact_sync`），
  作为 insight L2 去重的底库——insight 与已有记忆语义相同会自动跳过。
- **反写策略**：只 `success_path` 类型反写到 `playbook.json` 的
  success_patterns；`repetition`/`error` 等其它类型仅入向量库不反写
  （`TYPE_MEMORY_MAP` 已删除，避免"硬编码反写到 memories 表"再走一次
  准入的冗余链路）。insight 向量条目永久保留，不参与 LRU 淘汰。

## 存储布局

`memory.db`（per-profile 物理隔离）：`memories`（6 态状态机）+
`memory_evidence`（quote 证据链）+ `memory_candidates`（4 态）+
`consolidation_jobs`（幂等水位线）+ `daily_summaries` + `memory_fts`（FTS5）+
`vec_items`/`vec_index`（sqlite-vec：insight、fact_sync 镜像、memory 语义索引）。

## 隐私与遗忘

- companion 情感记忆独立域存储/召回，只在陪伴模式注入
- sensitivity=restricted 永不进 prompt
- `forget_memory`：正文与证据 quote 改写为 `[forgotten]`，并同步删除
  FTS 行与向量索引（vec_items.text 不删等于没脱敏）
- 秘密值在提取前由 `mask_text` 脱敏

## 评测体系

独立仓库 `llm011/ethan-memory-train-data`：golden 集 6 域 × 200 条，
四个 runner——dry（0-LLM 断言）、live（真提取 + LLM 判官）、
recall（召回命中/泄漏）、tasks（全链路含 job/准入正确率）。
当前基线：live P=0.99 R=0.74；recall 2100/2100 命中、0/1400 泄漏；
tasks 96/96 job 完成、准入 110/110 正确。任何 prompt/阈值/模型改动
必须用该基线做前后对比。

## 卫星组件

- **User Profile**（`user_profile.md`）：7 个固定 section 的手写画像层，
  Web 编辑页 + `profile_update` 工具写入；heartbeat 每日分区压缩
- **Playbook**（`playbook.json`）：agent 行为规范，从用户纠正与成功路径学习
- **Working Memory**（REPL）：进程内 rolling summary 会话内压缩 +
  字符预算截断；web 渠道 messages 只带 hot 滑窗（长期记忆统一走 prompt 注入）
