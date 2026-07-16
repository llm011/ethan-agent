# Memory Eval — 结构化记忆评测设计

> 状态:golden extraction 集已就位(**6 域 × 200 = 1200 条**,手写 210 + `gen/` 生成 990),dry 评测全绿(4853 断言 0 失败)。评测对象 = `feat/structured-memory-pipeline` 的提取(extractors)→ 准入(admission)→ 召回(recall)链路。recall 集与 live 模式待做。
>
> golden 增量样本用 `gen/gen_all.py` 重新生成(幂等,保留手写部分);各域生成器可单独跑自校验:`python3 gen/gen_<domain>.py`。

## 一、评测两大类

| 类别 | 测什么 | 输入 | 期望（ground truth） | 通过判据 |
|---|---|---|---|---|
| **A. 记录能力 (extraction)** | 能不能把对话里的事实正确提取成结构化记忆 | 一段对话（user+assistant 多轮，带 message_id 与 mode） | 一组 expected candidates：`memory_type / dimension / memory_key / content / evidence_level / scope / quote / message_id` | 提取出的候选满足：①quote 是某条 user 消息的精确子串；②dimension 合法；③memory_key+content 语义命中 expected；④evidence_level 正确；⑤companion 维度仅在 companion mode 提取；⑥诊断/人格标签被拒 |
| **B. 召回能力 (recall)** | 能不能按 query 调动相关记忆、且不泄漏 | 预置一批 active memory + 一条 user query + mode | `expected_keys`（应召回的 memory_key 集合）+ `must_not_contain`（不得出现的串，主要用于 companion 隔离） | `build_structured_recall(query, mode)` 返回文本包含 expected_keys 对应 content；且不含 `must_not_contain`；companion 域在非苏念模式零召回 |

两类都**幂等可复跑**：A 类可用 fake provider（确定性）跑 dry 模式 0 LLM 成本，或 live 模式跑真实 LLM；B 类纯 store+recall，无 LLM。

## 二、领域与子维度（6 领域）

每领域 ≥ 200 条样本。子维度对齐 `extractors.py` 的白名单，**标 [GAP] 的为用户要求但 extractor 暂不支持**——eval 暴露 gap，需后续扩 `extractors.py` 维度白名单。

### 1. 个人信息 personal_information
- `identity.preferred_name`（称呼）、`identity.gender`[GAP]（性别）、`identity.age`[GAP]（年龄）、`identity.mbti`[GAP]（MBTI）、`identity.interests`[GAP]（兴趣）、`identity.language`、`identity.timezone`、`identity.location`（常住地）、`identity.education`、`identity.relationship`（家庭/关系状况）
- 场景多样式：单事实直陈、多事实一段话、纠正旧值、被动观察、含噪声对话

### 2. 偏好 preference
- `preference.communication`（先结论后证据）、`preference.tone`、`preference.decision_tradeoff`（方案偏好）、`preference.negative`（负向偏好/不接受什么）、`preference.tools`、`preference.schedule`（作息）、`preference.boundary`、`preference.response_verbosity`

### 3. 方法论 methodology
- `methodology.problem_definition`、`methodology.evidence_standard`（证据标准）、`methodology.decision_process`、`methodology.information_source`、`methodology.complexity_management`、`methodology.execution_strategy`、`methodology.risk_and_reversibility`、`methodology.communication`
- ⚠️ methodology 候选必须含 `structured.scenario/trigger/steps/...`；eval 验证结构化字段

### 4. 活动/目标 activity
- `activity.long_term_goal`（长期目标）、`activity.current_project`（当前项目）、`activity.current_focus`（当前焦点）、`activity.deadline`（截止）、`activity.blocker`（阻塞）、`activity.recent_completion`（近期完成）、`activity.responsibility`

### 5. 决定与约定 decision
- `decision.chosen`（已选）、`decision.rejected`（已否）、`decision.rationale`（理由）、`decision.commitment`（承诺）、`decision.agreement`（约定）、`decision.correction`（纠正）
- 含「助手建议未获用户确认→不应写入」的负样本

### 6. 苏念/情感 companion（仅 companion mode）
- `companion.current_emotion`、`companion.current_stressor`、`companion.soothing_preference`、`companion.support_boundary`、`companion.important_inner_experience`、`companion.explicit_value`
- 负样本：诊断词（抑郁/人格/依恋/创伤）必须被拒；非苏念模式零提取

## 三、样本场景模板（保证多样）

每个领域内混用以下场景，避免全是「单事实直陈」：
1. **single_explicit**：用户一句话直陈一个事实（explicit）。
2. **multi_fact_one_turn**：一段话含 3-5 个事实（一个场景多条，满足用户「一个场景需要多条」）。
3. **correction**：用户先说 A、后纠正成 B（corrected→supersede）。
4. **observed_single**：单次行为展示（observed，单 session 不晋升）。
5. **observed_repeat**：跨 2 session 重复同一 pattern（observed→升 active+inferred）。
6. **negative_pref**：「我不希望 X / 不要 Y」（preference.negative / boundary）。
7. **assistant_unconfirmed**：助手提议但用户没确认（应 NOOP，负样本）。
8. **noise**：事实夹在闲聊/工具调用结果里（抗干扰）。
9. **companion_leak**：非苏念模式下出现情绪表达（应零 companion 提取）。
10. **diagnostic_reject**：companion mode 下出现诊断词（应被拒）。

## 四、case schema

### A 类（extraction）
```json
{
  "id": "ext_personal_0001",
  "domain": "personal_information",
  "kind": "extraction",
  "scenario": "multi_fact_one_turn",
  "mode": "",
  "messages": [
    {"id": 1, "role": "user", "content": "..."},
    {"id": 2, "role": "assistant", "content": "..."}
  ],
  "expected": [
    {"memory_type":"personal_information","dimension":"identity.preferred_name",
     "memory_key":"identity.preferred_name","content":"用户希望被叫做小明",
     "evidence_level":"explicit","scope_type":"user","scope_id":"self",
     "quote":"你就叫我小明吧","message_id":1}
  ],
  "forbidden_domains": ["companion"],
  "gap_dimension": false
}
```
- `quote` 必须是 `messages[*].content`（role=user）的**精确子串**——这是 extractor 的硬约束，也是 eval 的 ground-truth 来源。
- `gap_dimension=true` 表示该 dimension 在 extractor 白名单缺失（age/mbti/interests/gender），dry 模式预期 miss，用于追踪 gap。

### B 类（recall）
```json
{
  "id": "rec_personal_0001",
  "domain": "personal_information",
  "kind": "recall",
  "mode": "",
  "seed_memories": [
    {"memory_type":"personal_information","dimension":"identity.preferred_name",
     "memory_key":"identity.preferred_name","content":"用户叫小明",
     "status":"active","memory_domain":"general","sensitivity":"normal"}
  ],
  "query": "你还记得我叫什么吗",
  "expected_keys": ["identity.preferred_name"],
  "must_not_contain": ["焦虑","抑郁","秘密"]
}
```

## 五、数据集与生成

- 生成器：`generate.py`（确定性，固定 RNG seed，可复现）。
- 产出：`data/extraction.jsonl`、`data/recall.jsonl`，每领域各 200 条 → 各 1200 条，共 2400 条。
- 填充池（姓名/职业/年龄/MBTI/兴趣/研究课题/目标/截止日/情绪/压力源…）多值随机组合，保证不重复。
- 一部分标 `golden: true` 为手工精修的边界 case（纠正、负样本、诊断词、多事实）。

## 六、评测脚本 `eval_runner.py`

两种模式：
- **dry 模式**（0 LLM）：把每条 extraction case 的 `expected` 当作「LLM 本该输出的候选 JSON」喂进 `admission`+`store`，验证确定性链路（quote 校验、dimension 校验、companion 边界、准入/supersede/forget、幂等）。用于回归 pipeline 正确性。
- **live 模式**（真实 LLM）：对每条 case 跑 `StructuredMemoryExtractor.extract`（真 provider），把产出候选与 `expected` 比对，算 precision/recall/F1。成本 = N×LLM 调用，建议先小批量。
- recall 评测：按 case 预置 store，跑 `build_structured_recall`，断言 expected_keys 命中 + must_not_contain 不出现。

指标：
- extraction：per-domain precision / recall / F1（按 memory_key+content 语义匹配）；companion 泄漏率；诊断词漏拒率；quote 合规率。
- recall：hit@k、companion 泄漏率、restricted 泄漏率。
- 输出 `report.json` + 控制台汇总表。

## 七、已知 gap（eval 暴露，待修）
1. `extractors.py` personal 维度缺 `identity.age / gender / mbti / interests`——用户明确要这些，需扩白名单。
2. methodology 维度名与 plan 文档（evidence_standard 等）不完全一致——以代码白名单为准，doc 对齐。
3. companion 诊断词表可继续扩充（eval 的 diagnostic_reject case 会持续加压）。
