# -*- coding: utf-8 -*-
"""分类样本集：query intent + memory role 标注样本。

评测集 recall.jsonl 只有 7 个 unique query，规则分类器对它们调参后 eval 100%——但这
是过拟合，不是泛化能力。本文件扩出一批**多形态 query 变体**，每个标注正确 intent +
期望 role，用来：

1. 验证规则分类器（HIGH/MEDIUM_CONFIDENCE_RULES）在更多 query 上的准确率
2. 作为 LLM 兜底分类器的 few-shot 样本 + 评测基线

query 形态覆盖：
- 同义改写（"我是谁" / "我叫啥" / "我是哪位"）
- 口语化（"我咋了" / "最近搞啥呢"）
- 带冗余词（"那个，你还记得我不，就是叫什么来着"）
- 反问 / 间接（"你应该知道我喜欢啥吧"）
- 跨域混淆（"我最近为什么这么累" — activity 还是 emotion？标 emotion，问的是状态）

memory_role 标注口径与 infer_memory_role 一致：dimension 一级前缀即 role。
"""
from __future__ import annotations

# ============================================================================
# Query 样本：(query, intent, confidence)
# confidence: "high" = 规则应命中且唯一；"medium" = 规则可能命中但有歧义；
#             "low" = 规则大概率 miss，需要 LLM 兜底
# ============================================================================

QUERY_SAMPLES: list[tuple[str, str, str]] = [
    # ---- identity（身份/称呼/职业/专长）----
    ("你是谁？不对，我是谁？", "identity", "high"),
    ("我叫什么名字", "identity", "high"),
    ("你还记得我叫什么吗", "identity", "high"),
    ("我是哪位", "identity", "medium"),
    ("我叫啥来着", "identity", "medium"),
    ("我的职业是什么", "identity", "high"),
    ("我是做什么工作的", "identity", "high"),
    ("你了解我的专业背景吗", "identity", "low"),
    ("我的专长领域是啥", "identity", "low"),
    ("之前跟你说过的我是干嘛的", "identity", "low"),
    ("我是搞什么的", "identity", "medium"),
    ("知道我是谁不", "identity", "medium"),

    # ---- activity（当前在做的事/项目焦点）----
    ("我最近在忙什么", "activity", "high"),
    ("最近在搞啥项目", "activity", "medium"),
    ("手头项目是哪个", "activity", "high"),
    ("我现在主要在做什么", "activity", "low"),
    ("最近工作重心在哪", "activity", "low"),
    ("我这阵子忙什么呢", "activity", "medium"),
    ("当前焦点是什么", "activity", "low"),
    ("最近在推进什么", "activity", "low"),

    # ---- decision（技术/方案决定及理由）----
    ("之前那个技术决定是什么", "decision", "high"),
    ("为什么选了 SQLite", "decision", "high"),
    ("当时怎么决定用这个的", "decision", "high"),
    ("选了什么方案", "decision", "high"),
    ("那个决定的原因", "decision", "low"),
    ("为什么不用别的", "decision", "low"),
    ("当初为什么这么定", "decision", "low"),
    ("技术决定是什么来着", "decision", "medium"),

    # ---- preference（沟通偏好/禁忌/回答风格）----
    ("回答的时候要注意什么", "preference", "high"),
    ("我喜欢什么沟通方式", "preference", "high"),
    ("有什么偏好", "preference", "high"),
    ("回答注意啥", "preference", "medium"),
    ("我不喜欢什么样的回答", "preference", "low"),
    ("跟我说话的习惯", "preference", "low"),
    ("你应该怎么跟我交流", "preference", "low"),
    ("沟通上有什么讲究", "preference", "low"),

    # ---- procedure / methodology（方法论/流程/比较方法）----
    ("技术方案该怎么比较", "procedure", "high"),
    ("怎么比较两个方案", "procedure", "high"),
    ("上次怎么调试的", "procedure", "high"),
    ("有什么方法论", "procedure", "medium"),
    ("做事的流程是什么", "procedure", "medium"),
    ("怎么评估技术主张", "procedure", "low"),
    ("决策流程是怎样的", "procedure", "low"),
    ("怎么分阶段推进", "procedure", "low"),

    # ---- emotion（情绪/状态/压力/近况感受）----
    ("我上次跟你说我怎么了", "emotion", "high"),
    ("我心情怎么样", "emotion", "high"),
    ("最近状态好吗", "emotion", "high"),
    ("我压力大不大", "emotion", "high"),
    ("我咋了最近", "emotion", "medium"),
    ("你还好吗，不对，我还好吗", "emotion", "medium"),
    ("我最近是不是有点焦虑", "emotion", "low"),
    ("我跟你说过的烦心事", "emotion", "low"),
    ("我上次情绪怎么样", "emotion", "medium"),
    ("最近怎么样了", "emotion", "medium"),
    ("我压力大吗", "emotion", "medium"),

    # ---- unknown（无法归类，走全量召回）----
    ("今天天气如何", "unknown", "low"),
    ("帮我写段代码", "unknown", "low"),
    ("随便聊聊", "unknown", "low"),
]


# ============================================================================
# Memory 样本：(dimension, expected_role)
# 验证 infer_memory_role 的覆盖
# ============================================================================

MEMORY_SAMPLES: list[tuple[str, str]] = [
    ("identity.preferred_name", "identity"),
    ("identity.occupation", "identity"),
    ("identity.expertise", "identity"),
    ("activity.project", "activity"),
    ("preference.communication", "preference"),
    ("preference.negative", "preference"),
    ("decision.chosen", "decision"),
    ("methodology.execution_strategy", "methodology"),
    ("methodology.decision_process", "methodology"),
    ("methodology.evidence_standard", "methodology"),
    ("methodology.information_source", "methodology"),
    ("methodology.decision_style", "methodology"),
    ("companion.current_emotion", "task_context"),
    ("companion.current_stressor", "task_context"),
    ("skill_experience.tooling", "skill_experience"),
    ("relationship.agreement", "relationship"),
    ("unknown_garbage_dimension", "task_context"),
]


def build_sample_json() -> dict:
    """导出为 JSON 结构（供 classifier._validate_on_samples 消费）。"""
    return {
        "query_samples": [
            {"query": q, "intent": i, "confidence": c}
            for q, i, c in QUERY_SAMPLES
        ],
        "memory_samples": [
            {"dimension": d, "memory_role": r}
            for d, r in MEMORY_SAMPLES
        ],
    }


if __name__ == "__main__":
    import json
    from pathlib import Path

    from ethan.memory.classifier import (
        classify_query_intent, infer_memory_role, INTENT_ROLE_MAP,
    )

    # 验证 query intent
    print("=== Query Intent 规则分类器准确率 ===")
    by_conf: dict[str, list[tuple[bool, str, str, str]]] = {}
    for q, expect, conf in QUERY_SAMPLES:
        pred = classify_query_intent(q)
        ok = pred == expect
        by_conf.setdefault(conf, []).append((ok, q, expect, pred))

    for conf in ("high", "medium", "low"):
        rows = by_conf.get(conf, [])
        if not rows:
            continue
        correct = sum(1 for ok, *_ in rows if ok)
        print(f"\n[{conf}] {correct}/{len(rows)} = {correct/len(rows):.1%} 准确")
        if correct < len(rows):
            for ok, q, expect, pred in rows:
                if not ok:
                    print(f"    MISS  expect={expect:11s} pred={pred:11s}  {q!r}")

    # 验证 memory role
    print("\n=== Memory Role 推断准确率 ===")
    correct = sum(1 for d, expect in MEMORY_SAMPLES if infer_memory_role(d) == expect)
    print(f"{correct}/{len(MEMORY_SAMPLES)} = {correct/len(MEMORY_SAMPLES):.1%} 准确")
    for d, expect in MEMORY_SAMPLES:
        pred = infer_memory_role(d)
        if pred != expect:
            print(f"    MISS  expect={expect:14s} pred={pred:14s}  dim={d}")

    # 导出样本集到 /tmp 供 classifier._validate_on_samples 用
    out = Path("/tmp/classification_samples_full.json")
    out.write_text(json.dumps(build_sample_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n样本集已导出: {out} (query={len(QUERY_SAMPLES)}, memory={len(MEMORY_SAMPLES)})")
