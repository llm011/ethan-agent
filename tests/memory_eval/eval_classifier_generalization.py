# -*- coding: utf-8 -*-
"""扩充 query 评测：用多样 query 变体测分类器+召回的泛化能力。

eval_runner_precision.py 的评测集只有 7 个 unique query，规则分类器对它们调参后
100%——但这是过拟合。本 runner 把 classification_samples.QUERY_SAMPLES 里的 58 个
多形态 query 逐个跑召回，验证：

1. 规则分类器在这些 query 上的 intent 正确率（已由 classification_samples 验证）
2. 召回结果的角色过滤是否正确——即召回的记忆 memory_role 是否 ⊆ INTENT_ROLE_MAP[intent]
   （unknown 时不过滤，不算）

做法：建一个"全维度"记忆库（每个 dimension 一条），对每个 query 跑召回，检查召回
结果的 memory_role 是否落在期望 role 上。这测的是「过滤精度」——会不会把不该召回的
role 召回进来。

用法:
  uv run python tests/memory_eval/eval_classifier_generalization.py
  ETHAN_MEMORY_CLASSIFY_LLM=1 uv run python tests/memory_eval/eval_classifier_generalization.py
"""
from __future__ import annotations

import collections
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import ethan.core.paths as paths  # noqa: E402
from ethan.core.context import ETHAN_USER_ID  # noqa: E402
from ethan.memory.admission import run_incremental_admission  # noqa: E402
from ethan.memory.classifier import (  # noqa: E402
    INTENT_ROLE_MAP, classify_query_intent, infer_memory_role,
)
from ethan.memory.records import MemoryCandidate  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402

from tests.memory_eval.classification_samples import QUERY_SAMPLES  # noqa: E402


# 全维度记忆库：每个 dimension 一条 active 记忆，覆盖所有 role
# memory_type 取 dimension 一级前缀（与 MemoryType 枚举对齐）
SEED_DIMENSIONS = [
    # (dimension, content, memory_domain, sensitivity)
    ("identity.preferred_name", "用户叫小明", "general", "normal"),
    ("identity.occupation", "用户是搜索引擎工程师", "general", "normal"),
    ("identity.expertise", "用户懂 IR/排序/主动学习", "general", "normal"),
    ("activity.project", "当前焦点是记忆召回降噪", "general", "normal"),
    ("preference.communication", "偏好可以用同行术语", "general", "normal"),
    ("preference.negative", "不接受没有 baseline 的性能主张", "general", "normal"),
    ("decision.chosen", "决定召回按 domain 隔离 companion", "general", "normal"),
    ("methodology.execution_strategy", "按 P0/P1 分阶段推进", "general", "normal"),
    ("methodology.decision_process", "比较方案先列淘汰依据再推荐", "general", "normal"),
    ("methodology.evidence_standard", "技术主张必须用固定评测集验证", "general", "normal"),
    ("companion.current_emotion", "用户当前情绪有点低落", "companion", "sensitive"),
    ("companion.current_stressor", "压力源是发布延期", "companion", "sensitive"),
]

# identity 前缀对应 personal_information memory_type
_DIM_TO_TYPE = {
    "identity": "personal_information",
    "activity": "activity",
    "preference": "preference",
    "decision": "decision",
    "methodology": "methodology",
    "companion": "companion",
}


def _seed_full_library(tmp: Path) -> None:
    """建一个覆盖所有维度的记忆库。companion 域记忆只在 companion 模式召回。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            store = MemoryStore()
            try:
                cands = []
                for dim, content, domain, sens in SEED_DIMENSIONS:
                    prefix = dim.split(".", 1)[0]
                    mtype = _DIM_TO_TYPE.get(prefix, "personal_information")
                    cands.append(MemoryCandidate(
                        memory_type=mtype,
                        dimension=dim,
                        memory_key=dim,
                        content=content,
                        scope_type="user",
                        scope_id="self",
                        memory_domain=domain,
                        evidence_level="explicit",
                        source_session_id="seed",
                        source_message_id="1",
                        source_role="user",
                        source_quote=content,
                        sensitivity=sens,
                        confidence=0.95,
                        user_id="",
                    ))
                store.create_candidate_batch(cands)
                run_incremental_admission(store, cands)
            finally:
                store.close()
    finally:
        ETHAN_USER_ID.reset(token)


def _recall(query: str, mode: str, tmp: Path, max_items: int = 15):
    """跑同步召回,返回召回的 MemoryRecord 列表。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            from ethan.memory.recall import build_structured_recall
            res = build_structured_recall(query, mode=mode, max_items=max_items)
            return res
    finally:
        ETHAN_USER_ID.reset(token)


def _recall_ids(query: str, mode: str, tmp: Path, max_items: int = 15) -> list[str]:
    """跑召回,返回召回内容的列表(保序)。"""
    res = _recall(query, mode, tmp, max_items)
    return list(res.items) if res else []


def evaluate_query(sample: tuple[str, str, str], tmp: Path) -> dict:
    """对单个 query 样本评测:分类是否正确 + 召回角色过滤是否正确。

    返回:
        query, expect_intent, rule_intent, role_correct(分类→role 是否覆盖期望),
        recall_role_ok(召回的记忆 role 是否都落在期望 role 上),
        recalled_n, recalled_roles
    """
    query, expect_intent, conf = sample
    rule_intent = classify_query_intent(query)

    # companion 情绪 query 需要 companion 模式才能召回 companion 域
    mode = "companion" if expect_intent == "emotion" else ""

    expected_role = INTENT_ROLE_MAP.get(expect_intent)
    rule_role = INTENT_ROLE_MAP.get(rule_intent)

    # 召回
    lines = _recall_ids(query, mode, tmp)

    # 从召回行反推 role：每行是 "[label] content (来源...)"，用 SEED_DIMENSIONS 反查
    dim_by_content = {c: (d, infer_memory_role(d)) for d, c, _, _ in SEED_DIMENSIONS}
    recalled_roles = set()
    for line in lines:
        for content, (dim, role) in dim_by_content.items():
            if content in line:
                recalled_roles.add(role)
                break

    # 召回角色过滤是否正确:unknown(不过滤)不算,只检查有期望 role 的 case
    if expected_role is None:
        role_filter_ok = True  # 不过滤,无法判定
    else:
        # 期望召回的角色是否都出现了(保 recall)+ 没有不该出现的角色(保 precision)
        # 注意:有些 role 的记忆可能因 query 语义不命中而没召回,这不算错
        wrong_roles = recalled_roles - {expected_role}
        role_filter_ok = len(wrong_roles) == 0

    # 分类是否正确
    intent_correct = rule_intent == expect_intent

    return {
        "query": query,
        "expect_intent": expect_intent,
        "rule_intent": rule_intent,
        "confidence": conf,
        "intent_correct": intent_correct,
        "expected_role": expected_role,
        "recalled_n": len(lines),
        "recalled_roles": sorted(recalled_roles),
        "role_filter_ok": role_filter_ok,
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cls_gen_"))
    _seed_full_library(tmp)
    print(f"全维度记忆库已建: {tmp}\n")

    results = [evaluate_query(s, tmp) for s in QUERY_SAMPLES]

    # 汇总
    by_conf = collections.defaultdict(list)
    for r in results:
        by_conf[r["confidence"]].append(r)

    print(f"{'conf':<8} {'intent准确':>10} {'role过滤正确':>12} {'样本数':>6}")
    print("-" * 42)
    for conf in ("high", "medium", "low"):
        rows = by_conf.get(conf, [])
        if not rows:
            continue
        ic = sum(1 for r in rows if r["intent_correct"])
        rc = sum(1 for r in rows if r["role_filter_ok"])
        print(f"{conf:<8} {ic:>6}/{len(rows):<3} {rc:>6}/{len(rows):<5} {len(rows):>6}")
    all_ic = sum(1 for r in results if r["intent_correct"])
    all_rc = sum(1 for r in results if r["role_filter_ok"])
    print("-" * 42)
    print(f"{'ALL':<8} {all_ic:>6}/{len(results):<3} {all_rc:>6}/{len(results):<5} {len(results):>6}")

    # 失败 case 详情
    fails = [r for r in results if not r["role_filter_ok"] or not r["intent_correct"]]
    if fails:
        print(f"\n问题 case ({len(fails)}):")
        for r in fails:
            flags = []
            if not r["intent_correct"]:
                flags.append(f"intent≠({r['rule_intent']})")
            if not r["role_filter_ok"]:
                flags.append(f"role泄漏({r['recalled_roles']})")
            print(f"  [{r['confidence']:6s}] {' '.join(flags):30s} "
                  f"expect={r['expect_intent']:11s} {r['query']!r}")
    else:
        print("\n全部通过:分类正确 + 召回角色过滤无泄漏")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
