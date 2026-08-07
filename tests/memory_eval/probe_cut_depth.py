# -*- coding: utf-8 -*-
"""切深探针：把「注入量」和「排序质量」的贡献拆开，判断 embedding 是不是瓶颈。

要回答的问题
-----------
`probe_distance` / `probe_lexical` 都否证了确定性切点，剩下两个候选解释：

  (a) BGE-small-zh INT8 能力不足 → 换更强的 embedding
  (b) 注入量太大 → 收 max_items

这两个假设对同一个指标（P@注入 14%）给出完全不同的处方，必须先分开。方法是把
每个 case 的候选按真实 BGE 排序，逐切深 k 报 precision/recall，并同时给出
**oracle 上界**（同一 k 下最好可能的排序）：

  oracle P@k = min(k, n_rel) / k          ← 纯算术上界，与模型无关
  oracle R@k = min(k, n_rel) / n_rel

于是 14% 这个数被分解成两部分：

  oracle@k 本身      = 「注入量」的贡献（算术天花板，换模型改不了）
  oracle@k − 实测@k  = 「排序质量」的贡献（换模型能改的那部分）

哪一项占大头，就该先修哪一项。

为什么不直接换模型试
------------------
换 embedding 要重建全量向量索引、放大延迟、放弃 INT8 小模型，代价远高于改一个
`max_items`。而且如果算术天花板就在附近，换模型对 P@注入 的改善**上限是 0**——
这与 60-case 重排 A/B 里 P@all 三臂完全相同（14.0%）是同一个机制：
只改顺序不改集合，集合级 precision 天然不变。

口径警告
-------
oracle 上界依赖二值标签，而标签已知偏保守（methodology 域那批「有用背景」被记成
噪声）。所以 oracle 是**下界的上界**——真实天花板只会更高，不会更低。

用法
----
  uv run python tests/memory_eval/probe_cut_depth.py --per-domain 20
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

from eval_runner_precision import (  # noqa: E402
    _recall_jsonl_path,
    build_distractor_pool,
    pick_distractors,
)

CUTS = [1, 2, 3, 5, 8, 11, 15, 20]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-domain", type=int, default=20)
    ap.add_argument("--distractors", type=int, default=40)
    ap.add_argument("--l2-max", type=float, default=1.3)
    args = ap.parse_args()

    from ethan.memory.embeddings import embed_sync

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

    def l2(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    # acc[k] = [实测命中, 实测注入, oracle命中, 真值总数, case 数]
    acc = {k: [0, 0, 0, 0, 0] for k in CUTS}
    n_rel_total = 0
    n_cand_total = 0
    ranks_of_first: list[int] = []

    for n, case in enumerate(cases):
        sk = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
        relevant = {sk[k] for k in case["expected_keys"] if k in sk}
        if not relevant:
            continue
        corpus = list(dict.fromkeys(
            [s["content"] for s in case["seed_memories"]]
            + [s["content"] for s in pick_distractors(case, pool, args.distractors)]
        ))
        qv = embed_sync(case["query"])
        scored = sorted(
            ((c, l2(qv, embed_sync(c))) for c in corpus), key=lambda x: x[1]
        )
        # 与生产一致：先过 RECALL_L2_MAX 准入，再谈切深
        cands = [c for c, d in scored if d <= args.l2_max]
        rels = [1 if c in relevant else 0 for c in cands]
        n_rel = len(relevant)
        n_rel_total += n_rel
        n_cand_total += len(cands)
        if 1 in rels:
            ranks_of_first.append(rels.index(1) + 1)

        for k in CUTS:
            a = acc[k]
            got = min(k, len(cands))
            a[0] += sum(rels[:k])
            a[1] += got
            a[2] += min(k, n_rel)      # oracle 在同一切深下能命中的真值数
            a[3] += n_rel
            a[4] += 1

        if (n + 1) % 40 == 0:
            print(f"  {n+1}/{len(cases)}", flush=True)

    ncase = acc[CUTS[0]][4]
    print(f"\n{ncase} case  平均候选 {n_cand_total/ncase:.1f} 条  "
          f"平均真值 {n_rel_total/ncase:.2f} 条  L2_MAX={args.l2_max}")
    print(f"首个真值平均排名 {sum(ranks_of_first)/len(ranks_of_first):.2f}"
          f"  (MRR={sum(1/r for r in ranks_of_first)/ncase:.3f})")

    print(f"\n{'切深 k':>7}{'实测 P':>9}{'oracle P':>10}{'差距':>8}"
          f"{'实测 R':>9}{'oracle R':>10}{'注入':>7}")
    print("-" * 62)
    for k in CUTS:
        hit, inj, orc, rel, _ = acc[k]
        p_act = hit / inj if inj else 0.0
        p_orc = orc / inj if inj else 0.0
        r_act = hit / rel if rel else 0.0
        r_orc = orc / rel if rel else 0.0
        print(f"{k:>7}{p_act:>8.1%}{p_orc:>10.1%}{p_orc-p_act:>8.1%}"
              f"{r_act:>9.1%}{r_orc:>10.1%}{inj/ncase:>7.1f}")

    print("\n读法：oracle P 是同一切深下**任何**排序器的上界（纯算术，换 embedding 改不了）。")
    print("     『差距』列才是排序质量的欠账，也就是换更强 embedding 能拿回的那部分。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
