# Memory Eval — 结构化记忆召回评测

> 0-LLM、确定性、可复跑。评测对象 = `ethan/memory/recall.py` 的 `build_structured_recall`。

## 数据与 runner 的关系

- **runner 留在本仓** `tests/memory_eval/eval_runner_recall.py`：测试基建应跟代码同仓演进——API drift（如 `build_structured_recall` 返回类型从 str 变 `RecallResult`）才能被及时抓到。本仓 `6c12f9e` 起从外部仓迁回 runner。
- **golden 数据留在外部仓** `llm011/ethan-memory-train-data`（`data/recall.jsonl`，1200 条 × 850KB）：当初为仓库瘦身迁出，不进本仓。

## 定位数据

runner 按以下顺序找 `data/recall.jsonl`：

1. 环境变量 `ETHAN_MEMORY_TRAIN_DATA=<path>`（指向 `ethan-memory-train-data` 仓根）
2. 默认主仓同级目录：`../ethan-memory-train-data/data/recall.jsonl`

找不到则退出码 2 并提示。CI 无数据时该步骤应 skip，不挂流水线。

## 运行

```bash
# 数据仓已 clone 到主仓同级（开发机默认）
uv run python tests/memory_eval/eval_runner_recall.py
uv run python tests/memory_eval/eval_runner_recall.py --limit 100        # 快速抽样
uv run python tests/memory_eval/eval_runner_recall.py --json-out /tmp/r.json  # 逐 case 结果
```

## case schema

```json
{
  "id": "rec_personal_information_0001",
  "domain": "personal_information",
  "mode": "",                       // "" = 普通模式；"companion" = 苏念模式
  "seed_memories": [                // 经真实 candidate→admission 落成 active
    {"memory_type": "...", "dimension": "identity.preferred_name",
     "memory_key": "identity.preferred_name", "content": "用户叫阿岚",
     "memory_domain": "general", "sensitivity": "normal"}
  ],
  "query": "你还记得我是谁吗，做什么的？",
  "expected_keys": ["identity.preferred_name", "identity.occupation", "identity.expertise"],
  "must_not_contain": ["焦虑", "抑郁"]   // 这些串不得出现在召回文本
}
```

## 指标

- **命中率 (hit)**：`expected_keys` 对应 content 出现在召回文本里的比例。
- **泄漏率 (leak)**：`must_not_contain` 串出现在召回文本里的比例。leak 的护栏是**域隔离**（companion 域记忆在非 companion 模式不召回，restricted 不注入），与向量阈值无关。

## 6 领域

`personal_information` / `preference` / `methodology` / `activity` / `decision` / `companion`，每域 200 条。companion 域一半 mode=""（测泄漏）、一半 mode="companion"（测召回）。

## 相关

- 阈值扫描：`sweep_threshold.py`（扫 `RECALL_L2_MAX` 找最佳工作点）
- 代码：`ethan/memory/recall.py`（召回）、`ethan/memory/memory_vectors.py`（向量阈值）
- 外部数据仓：`llm011/ethan-memory-train-data`
