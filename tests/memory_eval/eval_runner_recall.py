# -*- coding: utf-8 -*-
"""Memory eval — recall 模式评测(0 LLM)。

对每条 recall case:
  1. 独立临时 memory 目录(每 case 隔离),把 seed_memories 经 candidate→admission
     落成 active(与生产同路径)
  2. 调真实 build_structured_recall(query, mode)
  3. 断言: expected_keys 对应的 content 出现在召回文本;must_not_contain 全部不出现

指标: 召回命中率(hit)、泄漏率(leak)、分域统计。

用法:
  uv run python eval_runner_recall.py            # 数据不存在时先跑 generate.py
  uv run python eval_runner_recall.py --limit 100
"""
from __future__ import annotations

import argparse
import json
import subprocess
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

RECALL_JSONL = HERE / "data" / "recall.jsonl"


def seed_and_recall(case: dict, tmp: Path) -> str:
    """独立目录落 seed,返回 build_structured_recall 输出文本。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            store = MemoryStore()
            try:
                cands = []
                for s in case["seed_memories"]:
                    cands.append(MemoryCandidate(
                        memory_type=s["memory_type"],
                        dimension=s["dimension"],
                        memory_key=s["memory_key"],
                        content=s["content"],
                        scope_type="user", scope_id="self",
                        memory_domain=s.get("memory_domain", "general"),
                        evidence_level="explicit",
                        source_session_id=case["id"],
                        source_message_id="1",
                        source_role="user",
                        source_quote=s["content"],
                        sensitivity=s.get("sensitivity", "normal"),
                        confidence=0.95,
                        user_id="",
                    ))
                if cands:
                    store.create_candidate_batch(cands)
                    run_incremental_admission(store, cands)
            finally:
                store.close()

            from ethan.memory.recall import build_structured_recall
            return build_structured_recall(case["query"], mode=case.get("mode", ""))
    finally:
        ETHAN_USER_ID.reset(token)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    args = ap.parse_args()

    if not RECALL_JSONL.exists():
        print("data/recall.jsonl 不存在,先跑 generate.py ...")
        subprocess.run([sys.executable, str(HERE / "generate.py")], check=True, cwd=HERE)

    cases = [json.loads(l) for l in RECALL_JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        cases = cases[:args.limit]

    stats = collections.Counter()
    per_domain = collections.defaultdict(collections.Counter)
    failures: list[str] = []

    for case in cases:
        dom = case["domain"]
        tmp = Path(tempfile.mkdtemp(prefix="recalleval_"))
        try:
            text = seed_and_recall(case, tmp)
        except Exception as exc:
            stats["error"] += 1
            failures.append(f"[{dom}] {case['id']}: {type(exc).__name__} {exc}")
            continue

        seed_by_key = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
        for key in case["expected_keys"]:
            content = seed_by_key.get(key, "")
            hit = content in text
            stats["hit" if hit else "miss"] += 1
            per_domain[dom]["hit" if hit else "miss"] += 1
            if not hit:
                failures.append(f"[{dom}] {case['id']}: 未召回 {key} ({content[:30]!r})")
        for bad in case["must_not_contain"]:
            leaked = bad in text
            stats["leak" if leaked else "noleak"] += 1
            per_domain[dom]["leak" if leaked else "noleak"] += 1
            if leaked:
                failures.append(f"[{dom}] {case['id']}: 泄漏 {bad!r}")

    total_hit = stats["hit"] + stats["miss"]
    total_leak = stats["leak"] + stats["noleak"]
    print("\n" + "=" * 70)
    print(f"RECALL 评测汇总({len(cases)} 条 case,0 LLM)")
    print("=" * 70)
    print(f"命中率: {stats['hit']}/{total_hit} ({100*stats['hit']/max(total_hit,1):.1f}%)")
    print(f"泄漏率: {stats['leak']}/{total_leak} ({100*stats['leak']/max(total_leak,1):.1f}%)")
    if stats["error"]:
        print(f"执行错误: {stats['error']}")
    print("\n分域:")
    for dom in sorted(per_domain):
        s = per_domain[dom]
        h, l = s["hit"] + s["miss"], s["leak"] + s["noleak"]
        print(f"  {dom:<20} hit {s['hit']}/{h}  leak {s['leak']}/{l}")
    if failures:
        print(f"\n失败明细(前 20 / 共 {len(failures)}):")
        for x in failures[:20]:
            print("  -", x)
    return 1 if (stats["miss"] or stats["leak"] or stats["error"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
