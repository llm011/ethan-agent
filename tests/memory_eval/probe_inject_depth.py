# -*- coding: utf-8 -*-
"""注入深度探针：宽预算 + 浅注入，在**真实召回链路**上逐域量代价。

与 probe_cut_depth 的区别
------------------------
`probe_cut_depth` 是离线暴力算 L2 排序的模拟，只有向量一路、没有 RRF、没有域门控。
本探针直接调生产的 `_collect_split()`，跑的是真链路：FTS/LIKE + 向量 + RRF 融合 +
domain 隔离 + restricted 过滤 + 盲兜底。所以它的数才是决定 `fallback_keep` 取值的依据。

为什么要「宽预算 + 浅注入」而不是直接调小 max_items
----------------------------------------------
`_collect` 的 `max_items` 一个参数控三件事：FTS limit、向量 limit(*2)、最终截断。
所以直接调小它会**同时**收窄候选池——那就退化成又一次调阈值，仍在同一条
recall/precision 曲线上平移，正是要避开的东西。

要的是另一件事：池子保持宽（recall 不掉），只把**进 prompt 的那一屏**收窄，拿 RRF
排序的头部。所以本探针固定 budget=20 调 `_collect`，只扫注入深度。这也是 PR #189
把候选预算和注入上限拆成 `max_items` / `fallback_keep` 两个参数之后才能落地的改法。

逐域是硬要求
----------
全局平均会掩盖单域崩溃。decision 域的 P@k 基线只有 21%，methodology 的真值是「有用
背景」而非「直接回答」，这两域对浅切的耐受度可能与 personal_information 差一个量级。

用法
----
  uv run python tests/memory_eval/probe_inject_depth.py --per-domain 20
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import ethan.core.paths as paths  # noqa: E402
from ethan.core.context import ETHAN_USER_ID  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402

from eval_runner_precision import (  # noqa: E402
    _recall_jsonl_path,
    build_distractor_pool,
    pick_distractors,
    seed_case,
)

DEPTHS = [1, 2, 3, 4, 5, 6, 8, 10, 15]
BUDGET = 20  # 候选预算，固定 = recall_memory 现在的 max_items


def collect_ranked(
    case: dict, tmp: Path, budget: int, query: str | None = None
) -> tuple[list[str], list[str], bool]:
    """调生产 `_collect`，返回 (general 候选, companion 候选, 是否走了盲兜底)。

    **两域分开返回，不合并。** 截断必须逐域做——companion 模式下 general 通常就能
    占满深度，在并集上切会把 companion 整段砍掉（`recall.py` 的 docstring 明确警告
    过这点，#189 的 fallback 也是 `general[:keep] + companion[:keep]`）。第一版探针
    在并集上切，companion 域 recall 从深度 1 到 10 恒为 33.3%、到 15 突然变 100%，
    那是这个截断错误的产物而不是域的性质。

    这里不用 #189 的 `_collect_split` —— 本分支叠在 #188 上，还没有那个函数。
    """
    fb_hit = {"v": False}
    real_list = MemoryStore.list_memories

    def spy_list(self, **kwargs):
        rows = real_list(self, **kwargs)
        if rows:
            fb_hit["v"] = True
        return rows

    q = case["query"] if query is None else query
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp), \
             patch.object(MemoryStore, "list_memories", spy_list):
            from ethan.memory.records import MemoryDomain
            from ethan.memory.recall import _collect, _is_companion_mode

            store = MemoryStore()
            try:
                general = _collect(
                    store, q, domain=MemoryDomain.GENERAL.value, max_items=budget
                )
                companion: list = []
                if _is_companion_mode(case.get("mode", "")):
                    companion = _collect(
                        store, q, domain=MemoryDomain.COMPANION.value, max_items=budget
                    )
            finally:
                store.close()
        return (
            [m.content for m in general],
            [m.content for m in companion],
            fb_hit["v"],
        )
    finally:
        ETHAN_USER_ID.reset(token)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-domain", type=int, default=20)
    ap.add_argument("--distractors", type=int, default=40)
    ap.add_argument("--budget", type=int, default=BUDGET)
    args = ap.parse_args()

    jsonl = _recall_jsonl_path()
    if not jsonl.exists():
        print(f"找不到 {jsonl}", file=sys.stderr)
        return 2

    all_cases = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = build_distractor_pool(all_cases)
    by_dom: dict[str, list[dict]] = collections.defaultdict(list)
    for c in all_cases:
        by_dom[c["domain"]].append(c)
    cases = [c for dom in sorted(by_dom) for c in by_dom[dom][: args.per_domain]]

    l2_max = __import__("ethan.memory.memory_vectors", fromlist=["x"]).RECALL_L2_MAX
    print(f"budget={args.budget}  L2_MAX={l2_max}  {len(cases)} cases "
          f"(+{args.distractors} distractors)\n", flush=True)

    # acc[domain][depth] = [命中, 注入, 真值总数, case数]
    acc: dict[str, dict[int, list[int]]] = collections.defaultdict(
        lambda: {d: [0, 0, 0, 0] for d in DEPTHS}
    )
    n_cands: list[int] = []
    blind = 0
    mrr: list[float] = []

    for n, case in enumerate(cases):
        sk = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
        relevant = {sk[k] for k in case["expected_keys"] if k in sk}
        if not relevant:
            continue
        tmp = Path(tempfile.mkdtemp(prefix="inj_"))
        seed_case(case, pick_distractors(case, pool, args.distractors), tmp)
        general, companion, fb = collect_ranked(case, tmp, args.budget)
        n_cands.append(len(general) + len(companion))
        blind += int(fb)
        # MRR 只看 general 序（companion 是独立的一份额度，混在一起排名没有意义）
        g_rels = [1 if c in relevant else 0 for c in general]
        mrr.append(1.0 / (g_rels.index(1) + 1) if 1 in g_rels else 0.0)

        for d in DEPTHS:
            # 逐域截断：每域各占一份深度额度，不在并集上切
            injected = general[:d] + companion[:d]
            a = acc[case["domain"]][d]
            a[0] += sum(1 for c in injected if c in relevant)
            a[1] += len(injected)
            a[2] += len(relevant)
            a[3] += 1

        if (n + 1) % 40 == 0:
            print(f"  {n+1}/{len(cases)}", flush=True)

    ncase = len(n_cands)
    print(f"\n平均候选 {sum(n_cands)/ncase:.1f} 条  MRR={sum(mrr)/ncase:.3f}  "
          f"盲兜底 {blind}/{ncase}")

    print(f"\n=== 全局 ===")
    print(f"{'注入深度':>8}{'P@注入':>9}{'recall':>9}{'真值条数':>10}{'噪声条数':>10}")
    print("-" * 47)
    for d in DEPTHS:
        hit = sum(acc[dm][d][0] for dm in acc)
        inj = sum(acc[dm][d][1] for dm in acc)
        rel = sum(acc[dm][d][2] for dm in acc)
        print(f"{d:>8}{hit/inj if inj else 0:>8.1%}{hit/rel if rel else 0:>9.1%}"
              f"{hit/ncase:>10.2f}{(inj-hit)/ncase:>10.2f}")

    print(f"\n=== 逐域 recall（浅切能不能扛住，看这张）===")
    doms = sorted(acc)
    print(f"{'深度':>5}" + "".join(f"{d[:11]:>13}" for d in doms))
    print("-" * (5 + 13 * len(doms)))
    for d in DEPTHS:
        row = f"{d:>5}"
        for dm in doms:
            hit, _, rel, _ = acc[dm][d]
            row += f"{hit/rel if rel else 0:>12.1%} "
        print(row)

    print(f"\n=== 逐域 P@注入 ===")
    print(f"{'深度':>5}" + "".join(f"{d[:11]:>13}" for d in doms))
    print("-" * (5 + 13 * len(doms)))
    for d in DEPTHS:
        row = f"{d:>5}"
        for dm in doms:
            hit, inj, _, _ = acc[dm][d]
            row += f"{hit/inj if inj else 0:>12.1%} "
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
