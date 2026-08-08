# -*- coding: utf-8 -*-
"""精确率评测：给每个 case 掺入同域干扰项，测 precision@k / nDCG，而非只测命中。

为什么需要这个 runner
--------------------
`eval_runner_recall.py` 只测两件事：expected_keys 的 content 是否出现（hit）、
must_not_contain 是否出现（leak）。它的 seed 集**只含该 case 自己的相关记忆**，
所以召回把库里所有东西全塞进来也能拿 100% hit——命中率对精确率完全不敏感。
实测证据：PR #182 把 RECALL_L2_MAX 1.1→1.3 后 hit 89%→100%，但同一批候选里
绝大多数是噪声。命中率数字是真的，精确率维度是空的。

注意本 runner 的绝对值随 `RECALL_L2_MAX` 变化：1200-case 基线
（recall 100% / P@k 42.6% / P@注入 14.0% / nDCG 0.689 / 平均 9.58 条噪声）
是在阈值 = 1.3 下测的。阈值仍是 1.1 时 recall 会低于 100%。

本 runner 的做法
--------------
从**同一 memory_domain、不同 dimension 前缀**的其他 case 里借真实记忆当干扰项，
掺进 seed 集。前缀不同保证它们确实不该被这个 query 召回（借同前缀的会变成
"冲突事实"而非干扰项——比如另一个 case 的 identity.preferred_name 对
"我是谁" 这个 query 是真相关的）。干扰项取自真实语料而非合成，分布更接近线上。

指标
----
- precision@k（k=|expected_keys|，理想切点）：召回文本里相关条数 / min(k, 召回数)
- precision@max_items：实际注入 prompt 的那一屏里有多少是相关的
- recall：expected_keys 的命中率（与旧 runner 可比）
- nDCG@k：二值相关度，衡量相关项是否排在前面
- leak：must_not_contain 是否出现（掺干扰项后域隔离应仍然守住）

用法
----
  uv run python tests/memory_eval/eval_runner_precision.py
  uv run python tests/memory_eval/eval_runner_precision.py --limit-cases 100
  uv run python tests/memory_eval/eval_runner_precision.py --distractors 20 --max-items 15
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import ethan.core.paths as paths  # noqa: E402
from ethan.core.context import ETHAN_USER_ID  # noqa: E402
from ethan.memory.admission import run_incremental_admission  # noqa: E402
from ethan.memory.records import MemoryCandidate  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402


def _recall_jsonl_path() -> Path:
    env = os.environ.get("ETHAN_MEMORY_TRAIN_DATA")
    if env:
        return Path(env) / "data" / "recall.jsonl"
    return HERE.parent.parent.parent / "ethan-memory-train-data" / "data" / "recall.jsonl"


def _prefix(dimension: str) -> str:
    """dimension 的第一段，如 identity.preferred_name → identity。"""
    return dimension.split(".", 1)[0]


def build_distractor_pool(cases: list[dict]) -> dict[str, list[dict]]:
    """按 memory_domain 聚合全语料的 seed_memories，供借用当干扰项。

    去重键用 (memory_key, content)——同 key 不同内容的会在准入时互相 supersede，
    掺进去反而制造了"事实冲突"而不是"无关干扰"。
    """
    pool: dict[str, dict[tuple[str, str], dict]] = collections.defaultdict(dict)
    for case in cases:
        for seed in case["seed_memories"]:
            domain = seed.get("memory_domain", "general")
            pool[domain][(seed["memory_key"], seed["content"])] = seed
    return {d: list(v.values()) for d, v in pool.items()}


def pick_distractors(case: dict, pool: dict[str, list[dict]], n: int) -> list[dict]:
    """为 case 挑 n 条同域、前缀不同、key 不冲突的干扰项。确定性（按 case id 播种）。"""
    own_keys = {s["memory_key"] for s in case["seed_memories"]}
    # 排除 expected 相关的整个 dimension 家族——同前缀的是相关项不是干扰项
    banned_prefixes = {_prefix(k) for k in case["expected_keys"]}
    banned_prefixes |= {_prefix(s["dimension"]) for s in case["seed_memories"]}
    # 干扰项与 seed 同域，否则会被 SQL memory_domain 过滤掉，等于没掺
    domains = {s.get("memory_domain", "general") for s in case["seed_memories"]}

    candidates = []
    for domain in sorted(domains):
        for seed in pool.get(domain, []):
            if seed["memory_key"] in own_keys:
                continue
            if _prefix(seed["dimension"]) in banned_prefixes:
                continue
            # restricted 永不注入，掺进来测不出东西
            if seed.get("sensitivity") == "restricted":
                continue
            candidates.append(seed)

    rng = random.Random(case["id"])
    rng.shuffle(candidates)
    # 同一 memory_key 只留一条，避免准入阶段互相 supersede
    picked: list[dict] = []
    seen_keys: set[str] = set()
    for seed in candidates:
        if seed["memory_key"] in seen_keys:
            continue
        seen_keys.add(seed["memory_key"])
        picked.append(seed)
        if len(picked) >= n:
            break
    return picked


def _to_candidate(seed: dict, case_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        memory_type=seed["memory_type"],
        dimension=seed["dimension"],
        memory_key=seed["memory_key"],
        content=seed["content"],
        scope_type="user",
        scope_id="self",
        memory_domain=seed.get("memory_domain", "general"),
        evidence_level="explicit",
        source_session_id=case_id,
        source_message_id="1",
        source_role="user",
        source_quote=seed["content"],
        sensitivity=seed.get("sensitivity", "normal"),
        confidence=0.95,
        user_id="",
    )


def seed_case(case: dict, distractors: list[dict], tmp: Path) -> None:
    """相关项 + 干扰项一起经 candidate→admission 落成 active。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            store = MemoryStore()
            try:
                cands = [_to_candidate(s, case["id"]) for s in case["seed_memories"]]
                cands += [_to_candidate(s, case["id"]) for s in distractors]
                if cands:
                    store.create_candidate_batch(cands)
                    run_incremental_admission(store, cands)
            finally:
                store.close()
    finally:
        ETHAN_USER_ID.reset(token)


def recall_case(case: dict, tmp: Path, max_items: int) -> list[str]:
    """跑召回，返回逐条召回行（保序——nDCG 需要排名）。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            from ethan.memory.recall import build_structured_recall

            res = build_structured_recall(
                case["query"], mode=case.get("mode", ""), max_items=max_items
            )
            return list(res.items) if res else []
    finally:
        ETHAN_USER_ID.reset(token)


def _ndcg(relevance: list[int], ideal_count: int) -> float:
    """二值相关度 nDCG。relevance 按召回排名给出 1/0。"""
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevance))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


def evaluate_case(case: dict, tmp: Path, max_items: int) -> dict:
    lines = recall_case(case, tmp, max_items)
    seed_by_key = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
    relevant_contents = {seed_by_key[k] for k in case["expected_keys"] if k in seed_by_key}

    # 逐条判定是否相关（召回行是格式化文本，用 content 子串判定，与旧 runner 一致）
    relevance = [1 if any(c in line for c in relevant_contents) else 0 for line in lines]

    k = len(relevant_contents)
    hit = sum(relevance)
    prec_at_k = (sum(relevance[:k]) / k) if k > 0 else 0.0
    prec_at_max = (hit / len(lines)) if lines else 0.0
    recall = (hit / k) if k > 0 else 0.0
    ndcg = _ndcg(relevance, k) if k > 0 else 0.0

    text = "\n".join(lines)
    leaks = [bad for bad in case["must_not_contain"] if bad in text]

    return {
        "id": case["id"],
        "domain": case["domain"],
        "recalled": len(lines),
        "relevant_total": k,
        "hit": hit,
        "noise": len(lines) - hit,
        "precision_at_k": prec_at_k,
        "precision_at_max": prec_at_max,
        "recall": recall,
        "ndcg": ndcg,
        "leaks": leaks,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-cases", type=int, default=0, help="只跑前 N 条 case")
    ap.add_argument("--distractors", type=int, default=15, help="每 case 掺入的同域干扰项数")
    ap.add_argument("--max-items", type=int, default=15,
                    help="build_structured_recall 的 max_items（15=recall_memory 工具实际值）")
    ap.add_argument("--json-out", type=str, default="", help="逐 case 结果写入路径")
    args = ap.parse_args()

    jsonl = _recall_jsonl_path()
    if not jsonl.exists():
        print(f"找不到 {jsonl}", file=sys.stderr)
        print("请 clone llm011/ethan-memory-train-data 或设置 ETHAN_MEMORY_TRAIN_DATA", file=sys.stderr)
        return 2

    all_cases = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = build_distractor_pool(all_cases)
    print(f"干扰项池: " + ", ".join(f"{d}={len(v)}" for d, v in sorted(pool.items())))

    cases = all_cases[: args.limit_cases] if args.limit_cases else all_cases

    print(f"seeding {len(cases)} cases (+{args.distractors} distractors each)...", flush=True)
    results = []
    per_domain = collections.defaultdict(list)
    skipped_no_distractor = 0
    for i, case in enumerate(cases):
        distractors = pick_distractors(case, pool, args.distractors)
        if not distractors:
            skipped_no_distractor += 1
        tmp = Path(tempfile.mkdtemp(prefix="prec_"))
        seed_case(case, distractors, tmp)
        res = evaluate_case(case, tmp, args.max_items)
        res["distractors_seeded"] = len(distractors)
        results.append(res)
        per_domain[case["domain"]].append(res)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(cases)}", flush=True)

    def avg(rows, field):
        return sum(r[field] for r in rows) / len(rows) if rows else 0.0

    total_leaks = sum(len(r["leaks"]) for r in results)
    print(f"\n{'domain':<22} {'P@k':>7} {'P@max':>7} {'recall':>7} {'nDCG':>7} "
          f"{'noise':>7} {'leak':>5}")
    print("-" * 72)
    for dom in sorted(per_domain):
        rows = per_domain[dom]
        print(f"{dom:<22} {avg(rows,'precision_at_k'):>6.1%} {avg(rows,'precision_at_max'):>6.1%} "
              f"{avg(rows,'recall'):>6.1%} {avg(rows,'ndcg'):>6.3f} "
              f"{avg(rows,'noise'):>7.2f} {sum(len(r['leaks']) for r in rows):>5}")
    print("-" * 72)
    print(f"{'ALL':<22} {avg(results,'precision_at_k'):>6.1%} {avg(results,'precision_at_max'):>6.1%} "
          f"{avg(results,'recall'):>6.1%} {avg(results,'ndcg'):>6.3f} "
          f"{avg(results,'noise'):>7.2f} {total_leaks:>5}")

    print(f"\n平均召回条数: {avg(results,'recalled'):.2f} / max_items={args.max_items}")
    print(f"平均干扰项掺入: {avg(results,'distractors_seeded'):.1f}")
    if skipped_no_distractor:
        print(f"警告: {skipped_no_distractor} 条 case 找不到合格干扰项（前缀全被排除），"
              f"这些 case 的精确率等同旧 runner")
    if total_leaks:
        print(f"\n!! 泄漏 {total_leaks} 处——掺干扰项后域隔离失守，需排查")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n逐 case 结果已写入 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
