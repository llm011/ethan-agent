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
    → pending 跨 session 复评 → TTL 过期 → 记忆衰减/归档 + 置信度晋升
    → general/companion 分域日摘要
  ② 重建 memory 向量索引（自愈漂移）
  ③ 做梦（daily_consolidation）:从 memory.db 读取当日 active 记忆（已替代 daily/*.jsonl）
    → _sync_corpus_to_memory_db 把 memories 同步进向量库作为去重底库
    → LLM 精炼 insight → embedding L2 去重 → insight 入向量库（无反写）

读路径（唯一入口,每次对话构建 system prompt）:
  <memory_context>  ← recall:FTS5/LIKE 精确通道
                      + BGE 向量语义通道,RRF(k=60) 融合;无命中回退 importance
  <user_profile>    ← 手写画像层      <behavioral_guidelines> ← playbook
```

> 历史变更：
> - `collect_signals` / `daily/*.jsonl` 信号链路已于 2026-07 退役，
>   做梦输入源直接从 `memory.db` 读取当日 active 记忆（消除存储分裂）。
> - `TYPE_MEMORY_MAP` 与 `success_path → playbook.json` 反写链路已于 2026-07 退役——
>   insight 仅作为向量条目入库，不再反写 memories 表或 playbook。
> - `success_patterns` 容器（B1 决策记录结构化）已于 2026-07 退役——
>   从 tool_steps 共现统计抽取的"模式"99.4% 是噪声，注入 system prompt
>   信息增益为 0。`playbook.json` 只保留 `procedures`（行为准则）字段。
> - `memory_write` 解耦 `_KEYWORD_RULES` 硬编码：agent 显式传 `memory_type`/`dimension`
>   时直接采用，未传时按 `category` 走最粗粒度兜底。

## 提取（LLM 只提议）

`ethan/memory/extractors.py`：每 3 个用户轮次，对上次水位线之后的消息做
增量提取（1 次主模型调用，JSON 非法时修复重试 1 次，`max_tokens=16384`）。

硬性校验（不过即弃）：
- **quote 溯源**：每条候选的 quote 必须是所指用户消息的精确子串
- **维度白名单**：由维度注册表生成（见下），`custom.*` 兜底维度强制 observed
- 个人事实类证据必须来自 user 消息；companion 类型仅陪伴模式可产出；
  companion 诊断词表（抑郁/焦虑症/PTSD 等 25 词）硬拒绝
- observed 候选 confidence 封顶 0.6
- **tentative 标记**（decision/activity 专用）："先试试/暂时/就这一次"类临时
  决定由模型标 `tentative=true`，落库为 `structured_data.tentative=True`，
  进入 Tier C 快速衰减轨道（见"记忆衰减与强化"）；定稿表述（定了/最终/以后
  都这样）省略该字段。其他类型上的 tentative 静默丢弃。

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

**跨 scope 偏好配对**（`ETHAN_MEMORY_PAIR_CROSS_L2`，默认 0.6）：project scope
的 `preference.*` 候选（explicit/inferred）若与 user/user_domain/user_skill 级
既有偏好维度严格相等且 L2 达标 → 只补证据到 user 级记忆（永不 supersede，
不建 project 副本）。解决"论文做成PPT"在每个项目里以 project 候选出现、
user 级置信度却永远卡首次准入值的问题——证据的独立 session 数随后由夜间
晋升阶梯自愈。

**tentative 清标**：tentative 记忆被非临时候选强化（同 scope merge 或跨
scope 配对）→ 清掉标记退出 Tier C，updated_at 重置（强化即活跃信号）。

**project 唤醒钩子**：任一候选在 project scope 落地（admitted/merged）→
该 scope 全部 dormant 记忆立即唤醒，重新参与召回（项目回归信号）。

所有配对决策写入 `processing_reason`（`semantic_superseded:l2=…`、
`cross_scope_reinforced:l2=…` 等）可审计。

## 召回（混合双通道）

`ethan/memory/recall.py`：system prompt 唯一的长期记忆块 `<memory_context>`。

- **精确通道**：FTS5 bm25。索引侧把 content/memory_key/searchable_data 切成 bigram 串
  （CJK 切二字、ASCII 词整取），查询侧同样用 bigram OR 拼 MATCH——unicode61 对整段
  CJK 不分词、trigram(3-gram) 实测 0 命中，只有 bigram 能让中文子串匹配命中。零命中落
  LIKE 兜底（bigram OR 子串匹配）。schema v2 升级时 DROP+重建 memory_fts 并回灌现有记忆。
- **语义通道**：BGE 向量近邻（补齐 CJK 与语序变换/同义改写）
- **融合**：RRF(k=60) 排名倒数求和，importance/confidence 决胜
- **Layer 2 确定性截断**（`ETHAN_MEMORY_RECALL_REL_GAP`，默认 `inf`=关闭）：RRF
  融合后对「向量独占」命中施加相对距离断层（`dist - min(dist)`），双通道一致命中
  无条件保留。1200-case 扫参结论：BGE-small-zh INT8 动态范围 0.88-1.22，距离不可分，
  0.25 才不掉 recall 但只省 0.17 条噪声——收益不足，默认关。换 embedding 后可复测。
- **Intent→Role 过滤**（`ethan/memory/classifier.py`，默认开）：召回前对 query 做
  intent 分类（identity/activity/decision/preference/procedure/unknown），按
  `INTENT_ROLE_MAP` 映射到 memory_role，在 FTS/向量/fallback 三条路径上同时过滤。
  memory_role 入库时从 dimension 一级前缀推断（identity.*→identity 等），与 intent
  近似双射。unknown intent 不过滤走全量。1200-case 实测：P@k 45.6%→91.7%、P@注入
  14.0%→93.1%、噪声 9.58→0.83 条，recall 仍 100%、leak 仍 0。5 个域 P@k 达 100%，
  仅 companion 域因 query 多为 unknown 走全量仍有噪声（情感陪伴场景不宜硬切 role）。
- **判官重排 + maxgap 切点**（`ETHAN_MEMORY_RERANK=1` 开启，默认关）：60-case A/B
  （FTS 修活后的干净候选池）opus-5 判官 P@k 40.6%→92.5%、nDCG 0.720→0.975，maxgap
  切点 P=77.9% / R=95%、保留 2.7 条。opus 0 fallback 优于 haiku 的 3 个。成本：每次
  召回 +7-10s 延迟。候选池 FTS 修活后 8-12 条、0% 低于
  `MIN_CANDIDATES=4`，判官不会被跳过。
- 无命中回退 importance top-N（身份类事实始终可用）
- **排序软降权**（`ETHAN_MEMORY_RANK_DECAY`，默认开）：RRF 分数乘 tier 半衰期
  因子（见"记忆衰减与强化"）。因子只影响排序不改状态；Tier A 恒 1.0；
  关闭时因子恒 1.0，排序与旧实现逐位一致（回归测试硬断言）
- companion 域仅陪伴模式召回；restricted 永不注入；forget 同步删除向量索引

## 记忆衰减与强化（`ethan/memory/decay.py`）

记忆的价值由**未来行为投票**：触发情境复现 + 召回后改变行为 → 强化；
长期无信号 → 衰减遗忘。两条链路全部确定性规则、零 LLM，挂载于夜间结构化
沉淀（`run_structured_consolidation`）。

**Tier 规则表**（判定优先级 A > C > B）：

| Tier | 归档 | 召回半衰期 | 判定 |
|------|------|-----------|------|
| A | 豁免 | 不衰减 | companion 域；scope ∈ {user, user_domain, user_skill}；dimension 前缀 ∈ {identity, preference, relationship} |
| B | 21 天休眠 | 30 天 | 其余（project scope 的 decision/methodology 等） |
| C | 14 天无强化 | 3 天 | decision/activity 且 `structured_data.tentative is True`（"先试试"） |

**衰减链路**（`ETHAN_MEMORY_DECAY=1` 时夜间执行，默认关）：
- project scope 连续 21 天无信号（updated_at / created_at / last_recalled_at /
  evidence.created_at 四路 MAX）→ 非 Tier A 记忆批量转 **dormant**（第 7 态：
  保留内容与证据、退出 FTS/向量召回、可随时唤醒）
- tentative 决定 14 天无强化 → dormant
- dormant 超 180 天 → forgotten（脱敏硬删，复用 `forget_memory`）

**强化链路**（`ETHAN_MEMORY_PROMOTE=1`，默认开，独立于衰减开关）：
- evidence 独立 session 数达阶梯（默认 2:0.8 / 3:0.9 / 5:0.95）→ confidence
  单调抬升到阶梯值（`bulk_set_confidence_quiet` 单事务批量写入、不动
  updated_at，避免批量晋升重置 scope 休眠计时）——修复"多次发生的偏好
  卡在首次准入 60%"的存量问题
- 补证据（add_evidence bump updated_at）、召回（last_recalled_at）、tentative
  清标（bump updated_at）都是活跃信号，自动重置衰减锚点

**唤醒**：dormant 可唤醒——UI 单条唤醒（`POST /memory/records/{id}/wake`）、
scope 批量（`POST /memory/records/wake-scope`）、或项目回归时准入钩子自动唤醒。

**上线流程**：先 `ETHAN_MEMORY_DECAY=1 ETHAN_MEMORY_DECAY_DRY_RUN=1` 跑真实
库（只读不改，日志与返回计数真实），确认归档/遗忘量合理后再去 DRY_RUN。

环境变量一览：

| 变量 | 默认 | 作用 |
|------|------|------|
| `ETHAN_MEMORY_RANK_DECAY` | 1 | 召回排序软降权开关 |
| `ETHAN_MEMORY_RANK_HALF_LIFE_PROJECT` | 30 | Tier B 半衰期（天） |
| `ETHAN_MEMORY_RANK_HALF_LIFE_TENTATIVE` | 3 | Tier C 半衰期（天） |
| `ETHAN_MEMORY_PROMOTE` | 1 | 置信度晋升开关 |
| `ETHAN_MEMORY_PROMOTE_LADDER` | 2:0.8,3:0.9,5:0.95 | session 数→置信度阶梯 |
| `ETHAN_MEMORY_PROMOTE_DOMAINS` | general | 晋升生效域（companion 默认豁免） |
| `ETHAN_MEMORY_PAIR_CROSS_L2` | 0.6 | 跨 scope 偏好配对阈值 |
| `ETHAN_MEMORY_DECAY` | 0 | 夜间归档/遗忘开关 |
| `ETHAN_MEMORY_DECAY_DRY_RUN` | 0 | 只读模拟 |
| `ETHAN_MEMORY_DECAY_PROJECT_IDLE_DAYS` | 21 | 项目休眠判定（天） |
| `ETHAN_MEMORY_DECAY_TENTATIVE_GRACE_DAYS` | 14 | tentative 宽限期（天） |
| `ETHAN_MEMORY_DECAY_FORGET_DAYS` | 180 | dormant 硬删（天） |

## 夜间沉淀与做梦

合并为单一编排 `run_nightly_consolidation`（每晚 0 点遍历全部 profile）：
顺序有意为之——结构化先跑，当日新准入的记忆进入做梦的向量去重底库，
insight 不会与刚提取的记忆重复反写。两步各自保留独立的
`consolidation_jobs` 记录（幂等，失败可重试不推进边界）。

做梦（`daily_consolidation.py`）：
- **输入源**：直接从 `memory.db` 读取当日 active 记忆（最多 15 条），
  替代旧的 `daily/*.jsonl` 信号文件——3 轮实时抽取写入 memory.db →
  0 点做梦直接读 memory.db，消除存储分裂。
- **去重底库**：`_sync_corpus_to_memory_db` 把 memories 表 active 记忆
  全量同步进向量库（`type=fact_sync`），作为 insight L2 去重的底库——
  insight 与已有记忆语义相同会自动跳过。
- **退役反写**：`success_path → playbook.json` 反写链路已删除。
  insight 仅作为向量条目入库，永久保留，不参与 LRU 淘汰。
  （`success_patterns` 容器已退役，见上文历史变更。）

## 存储布局

`memory.db`（per-profile 物理隔离，schema v4）：`memories`（7 态状态机：
candidate/active/disputed/superseded/expired/**dormant**/forgotten）+
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

recall runner 已迁回本仓 `tests/memory_eval/eval_runner_recall.py`（测试基建
应跟代码同仓演进——曾因分离导致 API drift 未被发现），golden 数据仍留外部仓，
经 `ETHAN_MEMORY_TRAIN_DATA` 或主仓同级 `ethan-memory-train-data/` 定位。
`tests/memory_eval/sweep_threshold.py` 扫 `RECALL_L2_MAX` 工作点：
1.1 时命中率 89.0%（同维度并列事实被阈值截断），1.3 时 100%，泄漏率全程 0%
（leak 由域隔离保证，与阈值无关）。

## 卫星组件

- **User Profile**（`user_profile.md`）：7 个固定 section 的手写画像层，
  Web 编辑页 + `profile_update` 工具写入；heartbeat 每日分区压缩
- **Playbook**（`playbook.json`）：agent 行为准则，由 `procedure_write` 工具 /
  `Consolidator` 从用户纠正中显式写入（`success_patterns` 已退役）
- **Working Memory**（REPL）：进程内 rolling summary 会话内压缩 +
  字符预算截断；web 渠道 messages 只带 hot 滑窗（长期记忆统一走 prompt 注入）
