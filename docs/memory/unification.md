# 记忆系统融合方案：新旧对比、取舍与终态架构

> 本文回答三个问题：新的结构化记忆流程比旧的 flat-facts 流程多了什么？各自有什么优缺点？合并之后长什么样、好在哪里？
>
> 配套实施计划分 5 个 PR 推进，见文末路线图。

---

## 1. 现状：两套系统并行运行

| | 旧（flat facts） | 新（structured memory） |
|---|---|---|
| 提取 | `extract_cold`：每 10 轮 1 次 lite LLM，从 rolling summary 提炼 key_facts | `StructuredMemoryExtractor`：<3 轮即时、之后每 3 轮 1 次主模型，从原始消息增量提取 JSON 候选 |
| 写入 | 直接写 facts.json，词重叠 80% 启发式合并 | LLM 只提议候选，**确定性准入代码**决定 admitted/merged/pending/rejected |
| 存储 | `~/.ethan/memory/facts.json`（JSON 数组） | `memory.db` SQLite 六表（memories/evidence/candidates/jobs/FTS5/日摘要） |
| 召回 | tags 关键词匹配 + confidence 排序，top 5~20 条 | FTS5 全文检索 + importance 兜底，按 domain 隔离 |
| 注入 | system prompt `<memory_context>` **+** 四渠道 messages 里再伪造 user/assistant 对重复注入一次 | system prompt `<structured_memory>`（与旧块并列） |
| 溯源 | 只有 source=session_id 字符串 | 每条记忆带用户消息**原文 quote**（精确子串校验）+ message_id |
| 运维 | 无 | consolidation_jobs 幂等、水位线增量、失败不前进可重试 |
| 隐私 | 无隔离 | companion 域仅陪伴模式召回；restricted 永不注入；forget 脱敏原文 |
| 评测 | 无 | golden 集 6 域 × 200 条 + dry/live/recall/tasks 四种 runner |

**并行期的代价**：同一批对话被 LLM 提取两次、写入两处、注入两遍。每 10 个用户轮次的后台 LLM 调用 ≈ 4+N 次（提取 1-2 次主模型 + compress 1 次 lite + extract_cold 1 次 lite + 每条 fact 提 tags N 次 lite + signals 1 次 lite）。

---

## 2. 新流程比旧流程多了什么

1. **证据溯源**：每条记忆必须带用户消息原文 quote，提取时精确子串校验——记忆从"黑盒结论"变成"可回查的引用"。
2. **准入门槛**：LLM 只提议，写不写由确定性代码按 evidence_level 决定（explicit/corrected 直进，observed 需 ≥2 独立 session 复证）——噪声和一次性推断进不了长期记忆。
3. **幂等与可恢复**：job 生命周期 + 水位线，LLM 调用失败标 failed、边界不前进、下轮自动重试，不会丢提取也不会重复提取。
4. **domain 隔离与敏感级**：companion 情感记忆只在陪伴模式召回，restricted 永不注入——情感数据不泄漏到工作会话。
5. **supersede 链与遗忘**：纠正（corrected）生成指向替代者的 FK 链；forget 会把正文和证据 quote 脱敏改写，而不是静默删行。
6. **TTL 过期**：`valid_until` 支持临时记忆（如"这周在赶 deadline"），午夜自动过期。
7. **维度化结构**：64 个维度（个人信息 14 / 偏好 11 / 活动 7 / 决策 8 / 方法论 11 / 陪伴 10 / 关系 3），methodology 还带 scenario/trigger/steps 结构体——召回可以按类型、按域、按场景进行。
8. **夜间复评 + 日摘要**：跨 session 的 observed 晋升、过期清理、按域生成当日摘要。
9. **可评测**：1200 条 golden 集，P/R/F1、准入正确率、泄漏率全部可量化。当前基线：tasks 全链路 P=0.95 R=0.43，准入 110/110 正确，0 泄漏；recall 2100/2100 命中。

## 3. 新流程的优点

- **可信**：每条记忆能回查到用户原话，幻觉记忆可被审计和追责。
- **防污染**：准入门槛 + companion 诊断词表拒绝（抑郁/焦虑症等 25 个词永不入库）+ 非陪伴模式禁产 companion 候选。
- **可运维**：失败可见（job failed + 错误信息）、可重试、幂等——旧链路 `except Exception: pass` 静默失效的问题不复存在。
- **隐私分级**：域隔离 + 敏感级 + 脱敏遗忘，三层语义都比"删 JSON 一行"强。
- **数据可说话**：任何 prompt/阈值/模型改动都能用 golden 集量化前后差异。

## 4. 新流程的缺点（诚实清单）

1. **提取 prompt 长且细**（64 维说明 + 规则），模型换代/降级后可能大面积失效——需要评测守门 + prompt 注册表化。
2. **维度白名单在代码里**，加维度要改 extractors.py 多处——不如 flat facts 灵活。
3. **提取用主模型**（lite haiku 经 relay 会注入 Kiro 人设拒绝提取任务），单次成本高于旧链路的 lite 调用。
4. **召回率偏低**：R=0.43（tasks 全链路），activity/decision/preference 域漏提明显——prompt"宁多勿漏"调优空间。
5. **准入去重是精确 key 匹配**："住在深圳"和"家在深圳南山"不会被识别为同一事实——缺语义归并。
6. **observed ≥2 session 硬门槛**被外部评审质疑武断（注：该评审部分误解——"我住在深圳"属 explicit 单次即准入；observed 仅针对 LLM 从上下文推断的内容。但硬门槛 vs confidence 累积值得用数据 A/B）。
7. **并行期成本翻倍**——这是双系统并存的过渡态问题，融合后即消除。

## 5. 旧流程的独有价值（合并时必须保留的）

| 组件 | 价值 | 去向 |
|---|---|---|
| episodes.json | 0 LLM 成本；heartbeat 需求挖掘 + Web API 的唯一数据源 | 已退役（2026-07） |
| user_profile.md | 用户可见可编辑（Web 编辑页），信任级别高于自动提取 | 保留，独立手写层 |
| playbook.json | agent 自身行为准则（procedures），不是用户事实 | 保留（success_patterns 已退役） |
| daily signals → insight | 跨 session 重复需求/失败模式挖掘 | 保留（success_path 反写已退役，仅入向量库） |
| REPL 进程内 WorkingMemory | 长会话内上下文压缩（web 渠道没有的的真实能力） | 保留，职责收缩为纯上下文管理 |
| memory_write / profile_update / procedure_write 工具 | agent 主动记忆能力 | 保留，后端改道结构化存储 |

## 6. 合并后的架构

```
读路径（唯一入口）:
  system prompt: <memory_context>  ← build_structured_recall（FTS + importance 兜底 + embedding hybrid）
                 <user_profile>（手写层，不动）
                 <behavioral_guidelines>（playbook，不动）
  messages: 仅会话内 hot 滑窗（REPL 保留压缩），不再注入 cold facts 伪消息对

写路径:
  每 3 轮: structured extraction → candidates → admission → memories   【唯一事实提取】
  agent主动: memory_write → candidate(explicit) → 立即准入
  每  夜: run_nightly_consolidation（做梦与每日沉淀合并，见下）
          ① 兜底扫描短会话 + pending 跨 session 复评
          ② insight 挖掘（重复需求/失败模式），embedding 去重 → 入向量库（不反写）
          ③ TTL 过期 + 按域日摘要

存储:
  memory.db ← 唯一长期事实库（含 FTS5 + 向量索引）
  user_profile.md ← 手写画像层，独立保留
  playbook.json ← 仅 procedures（行为准则），success_patterns 已退役
  facts.json → 一次性迁移后归档删除
  episodes.json / suggestions.json → 已退役删除
  daily/*.jsonl → 已退役（做梦输入源直接从 memory.db 读取）
```

> 2026-07 后续退役（在五 PR 落地之后）：
> - `collect_signals` / `daily/*.jsonl` 信号链路已退役，做梦输入源直接从 `memory.db` 读取当日 active 记忆
> - `TYPE_MEMORY_MAP` 与 `success_path → playbook.json` 反写链路已退役，insight 仅作为向量条目入库
> - `success_patterns` 容器（B1）已退役，`playbook.json` 只保留 `procedures` 字段
> - Episode 链路（`episodic.py` / `_mine_recurring_needs` / `_build_suggestion_hint`）已退役
> - 心跳 `_extract_decision_patterns` 已退役（同 success_patterns 一并清理）

**做梦与每日沉淀的合并**：现在 0 点跑两个独立 job（`run_daily_consolidation` 精炼信号产 insight、`run_structured_consolidation` 重提取复评产日摘要）——扫同一批 session、调各自的 LLM、写同一个库。合并为 `run_nightly_consolidation` 单一编排：一次扫当日数据，结构化复评与 insight 挖掘共享上下文与去重底库，统一 LLM 预算，失败一起重试（内部仍分两条 job 记录保持幂等粒度）。

## 7. 合并带来的优势

1. **成本下降**：每 10 轮后台 LLM 调用从 ~4+N 次降到 2-3 次（消灭双提取、tags 提取、重复 compress）；夜间两个 job 合并再省一遍扫描与摘要调用。
2. **单一事实源**：一条事实只存一处、只注入一遍，不再有 facts.json 与 memories 互相矛盾的窗口期。
3. **召回质量可演进**：FTS5 + embedding hybrid（BGE 对 CJK 原生友好，修复 FTS 无中文分词的短板）+ 准入语义归并——这些在 facts.json 的 tags 词匹配时代都做不到。
4. **可解释、可审计**：每条记忆有证据链、每次准入有 processing_reason、每次提取有 job 记录。
5. **可扩展而不改代码**：维度注册表声明式扩展 + `custom.*` 兜底命名空间，解决"加维度改代码"的僵硬。
6. **变更可守门**：所有后续调优（prompt、阈值、模型）都有 golden 基线对比，回归可量化。

## 8. 实施路线图（5 个 PR）

| PR | 内容 | 规模 |
|---|---|---|
| 1 止血 | tasks.py 删 compress/extract_cold；四渠道删 cold_facts 伪消息注入；heartbeat 停用 facts 去重 | 中 |
| 2 存储统一 | facts.json→memories 迁移脚本（幂等+启动自动执行）；memory_write 改道；召回单块化；Web API 兼容适配（UI 零改动）；REPL 改造；FactStore 删除 | 大 |
| 3 夜间合并 | daily_consolidation + structured_consolidation → run_nightly_consolidation | 中 |
| 4 能力升级 | 维度注册表 + prompt 生成；embedding 语义归并（只做配对建议，决策保持确定性）；hybrid 召回；observed 门槛 A/B（数据定胜负） | 大 |
| 5 收尾 | docs/README 更新；user_profile 与 memories 关系维持独立（后续再评估自动生成） | 小 |

每 PR 独立可回滚；验证 = 0-LLM 单测全绿 + golden 评测基线不回退 + 真服务冒烟。

## 9. 对外部评审意见的逐条回应

1. **"8 类型 4 证据 6 状态过重"** → 不砍类型体系（DB 里只是 TEXT 列，真正复杂度在 prompt）；prompt 注册表化后大幅缩短；删除死代码 skill_experience。
2. **"observed ≥2 武断"** → 部分误解（explicit 单次即准入）；硬门槛 vs confidence 累积做成 flag（`ETHAN_ADMISSION_OBSERVED_MODE=gate|accrual`，默认 gate），A/B 由 golden 评测决定默认值。
3. **"白名单僵硬"** → 采纳：PR-4 维度注册表 + custom.* 兜底。
4. **"成本翻倍"** → 采纳：这是并行动态，融合的本质就是消灭它。
5. **"无语义匹配"** → 采纳：PR-4 用现有 BGE embedding 做归并配对，但**决策规则保持确定性**（embedding 只提建议，不违反"确定性与概率性分离"原则）。
6. **"prompt 脆弱"** → 采纳：注册表生成 prompt + golden 评测守门模型换代。

---

## 10. 实施结果（2026-07-17 全部完成）

五个 PR 全部落地，`feat/structured-memory-pipeline` 分支：

| PR | 内容 | 关键提交 |
|---|---|---|
| 1 止血 | tasks.py 删 compress/extract_cold；四渠道删 cold_facts 伪消息注入；heartbeat 停 facts 去重 | `808e814` |
| 2 存储统一 | facts.json 退役（迁移脚本+启动自动迁移）；memory_write 改道；召回单块化；Web API 兼容适配（UI 零改动）；FactStore 删除 | `7b14351` |
| 3 夜间合并 | run_nightly_consolidation 统一编排（结构化先跑，做梦的去重底库含当日新记忆） | `03b3393` |
| 4 能力升级 | 维度注册表 + 语义配对准入 + 混合召回 + observed flag | `ecd5725` |
| 5 文档 | memory.md 重写、README 双语言、heartbeat/architecture 等同步 | 见分支 |

**实测数据**：

- **提取质量 A/B（120 条 golden live，同 runner 同模型）**：注册表 prompt 前后
  P 0.94→**0.99**、R 0.56→**0.74**、F1 0.70→**0.84**。
  分域 R：activity 0.35→0.95、decision 0.29→0.96、preference 0.25→0.58、
  methodology 0.41→0.52、personal 0.40→0.58、companion 0.88 持平——
  因果验证了"prompt 维度说明完整度 ≈ 召回率"（此前 prompt 只列 ~19/64 维）。
- **召回**：2100/2100 命中、0/1400 泄漏（混合召回改造后不回退）。
- **单测**：140 passed（含语义配对/混合召回/迁移幂等/编排顺序等新覆盖）。
- **成本**：每 10 轮后台 LLM 调用从 ~4+N 次降至 2-3 次；夜间两个 job 合一。

**遗留**（后续按需）：
- observed gate vs accrual 的 live A/B（2×96 条，flag 已就位，默认 gate）
- preference/methodology/personal 域 R 仍在 0.5~0.6 区间，prompt 可继续调优
- 做梦 prompt 的 supporting_signals 证据链与 type 判别边界

> **2026-07 后续退役**（五 PR 落地之后清理的过度工程）：
> - `collect_signals` / `daily/*.jsonl` 信号链路退役，做梦输入源直接从 `memory.db` 读取
> - `success_path → playbook.json` 反写链路退役（`TYPE_MEMORY_MAP` 删除）
> - `success_patterns` 容器（B1）退役——99.4% 噪声、注入 system prompt 信息增益为 0
> - Episode 链路（`episodic.py` / `_mine_recurring_needs` / `_build_suggestion_hint`）退役
> - 心跳 `_extract_decision_patterns` 退役（同 success_patterns 一并清理）
> - 提取门槛从 5 轮降为短会话（<3 轮）即时触发 + 每 3 轮增量；短会话兜底扫描保留（user_turns<3 但内容有价值）
