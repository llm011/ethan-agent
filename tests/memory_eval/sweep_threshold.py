# -*- coding: utf-8 -*-
"""阈值扫描：扫 RECALL_L2_MAX ∈ 一组值，每个值跑全量 1200 case，报 hit/leak/分域。

目的：用数据决定向量通道 L2 截断的最佳工作点（hit 最大、leak=0）。
leak 由域隔离保证（companion 域在非 companion 模式不召回），与阈值无关，
因此预期 leak 全程 0；hit 随阈值上升收敛。

用法:
  uv run python tests/memory_eval/sweep_threshold.py
  uv run python tests/memory_eval/sweep_threshold.py --limits 1.1,1.2,1.3,1.4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import collections
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import ethan.core.paths as paths  # noqa: E402
from ethan.core.context import ETHAN_USER_ID  # noqa: E402
from ethan.memory.records import MemoryCandidate  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402
from ethan.memory.admission import run_incremental_admission  # noqa: E402
import ethan.memory.memory_vectors as mv  # noqa: E402


def _recall_jsonl_path() -> Path:
    env = os.environ.get("ETHAN_MEMORY_TRAIN_DATA")
    if env:
        return Path(env) / "data" / "recall.jsonl"
    return HERE.parent.parent.parent / "ethan-memory-train-data" / "data" / "recall.jsonl"


def seed_case(case: dict, tmp: Path) -> None:
    """落 seed_memories 经 candidate→admission 成 active。每 case 一个独立目录。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            store = MemoryStore()
            try:
                cands = [
                    MemoryCandidate(
                        memory_type=s["memory_type"], dimension=s["dimension"],
                        memory_key=s["memory_key"], content=s["content"],
                        scope_type="user", scope_id="self",
                        memory_domain=s.get("memory_domain", "general"),
                        evidence_level="explicit",
                        source_session_id=case["id"], source_message_id="1",
                        source_role="user", source_quote=s["content"],
                        sensitivity=s.get("sensitivity", "normal"),
                        confidence=0.95, user_id="",
                    )
                    for s in case["seed_memories"]
                ]
                if cands:
                    store.create_candidate_batch(cands)
                    run_incremental_admission(store, cands)
            finally:
                store.close()
    finally:
        ETHAN_USER_ID.reset(token)


def recall_case(case: dict, tmp: Path) -> str:
    """对已 seed 的目录跑召回，返回文本。RECALL_L2_MAX 由调用方 monkeypatch。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            from ethan.memory.recall import build_structured_recall
            res = build_structured_recall(case["query"], mode=case.get("mode", ""))
            return res.text if res else ""
    finally:
        ETHAN_USER_ID.reset(token)


def evaluate(cases, seeded_dirs, threshold):
    """对一个阈值跑全量，返回 (hit, miss, leak, noleak, per_domain, fails)。"""
    mv.RECALL_L2_MAX = threshold  # monkeypatch 模块常量；recall_neighbors 读这个
    stats = collections.Counter()
    per_domain = collections.defaultdict(collections.Counter)
    fails = []
    for case, tmp in zip(cases, seeded_dirs):
        dom = case["domain"]
        text = recall_case(case, tmp)
        seed_by_key = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
        for key in case["expected_keys"]:
            content = seed_by_key.get(key, "")
            hit = content in text
            stats["hit" if hit else "miss"] += 1
            per_domain[dom]["hit" if hit else "miss"] += 1
            if not hit:
                fails.append(f"[{dom}] {case['id']}: {key}")
        for bad in case["must_not_contain"]:
            leaked = bad in text
            stats["leak" if leaked else "noleak"] += 1
            per_domain[dom]["leak" if leaked else "noleak"] += 1
            if leaked:
                fails.append(f"[{dom}] {case['id']}: LEAK {bad!r}")
    return stats, per_domain, fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limits", type=str, default="1.1,1.15,1.2,1.25,1.3,1.35,1.4",
                    help="逗号分隔的 RECALL_L2_MAX 值")
    ap.add_argument("--limit-cases", type=int, default=0, help="只跑前 N 条 case（调试用）")
    args = ap.parse_args()

    jsonl = _recall_jsonl_path()
    if not jsonl.exists():
        print(f"找不到 {jsonl}", file=sys.stderr)
        print("请 clone llm011/ethan-memory-train-data 或设置 ETHAN_MEMORY_TRAIN_DATA", file=sys.stderr)
        return 2

    cases = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit_cases:
        cases = cases[:args.limit_cases]

    limits = [float(x) for x in args.limits.split(",") if x.strip()]

    # 一次性 seed 所有 case（seed 是最大开销，跨阈值复用）
    print(f"seeding {len(cases)} cases to temp dirs...", flush=True)
    seeded_dirs: list[Path] = []
    for i, case in enumerate(cases):
        tmp = Path(tempfile.mkdtemp(prefix="sweep_"))
        seed_case(case, tmp)
        seeded_dirs.append(tmp)
        if (i + 1) % 200 == 0:
            print(f"  seeded {i+1}/{len(cases)}", flush=True)

    original = mv.RECALL_L2_MAX
    print(f"\n{'L2':<6} {'hit':>10} {'leak':>10} {'hit%':>7} {'leak%':>7}")
    print("-" * 50)
    results = []
    try:
        for lim in limits:
            stats, per_domain, fails = evaluate(cases, seeded_dirs, lim)
            total_hit = stats["hit"] + stats["miss"]
            total_leak = stats["leak"] + stats["noleak"]
            hit_pct = 100 * stats["hit"] / max(total_hit, 1)
            leak_pct = 100 * stats["leak"] / max(total_leak, 1)
            print(f"{lim:<6} {stats['hit']:>4}/{total_hit:<5} {stats['leak']:>4}/{total_leak:<5} "
                  f"{hit_pct:>6.1f}% {leak_pct:>6.1f}%")
            results.append({
                "l2": lim, "hit": stats["hit"], "miss": stats["miss"],
                "leak": stats["leak"], "noleak": stats["noleak"],
                "per_domain": {d: dict(s) for d, s in per_domain.items()},
                "fails": fails,
            })
    finally:
        mv.RECALL_L2_MAX = original

    # 分域明细 for 最佳工作点（hit 最大 & leak=0）
    best = max((r for r in results if r["leak"] == 0), key=lambda r: r["hit"], default=None)
    if best:
        print(f"\n=== 最佳工作点 RECALL_L2_MAX={best['l2']} "
              f"(hit {best['hit']}/{best['hit']+best['miss']}, leak 0) 分域: ===")
        for dom in sorted(best["per_domain"]):
            s = best["per_domain"][dom]
            h = s.get("hit", 0) + s.get("miss", 0)
            l = s.get("leak", 0) + s.get("noleak", 0)
            print(f"  {dom:<20} hit {s.get('hit',0)}/{h}  leak {s.get('leak',0)}/{l}")
        if best["fails"]:
            print(f"\n残留 miss（前 20 / 共 {len(best['fails'])}）:")
            for x in best["fails"][:20]:
                print("  -", x)

    out = HERE / "sweep_report.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整报告已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
