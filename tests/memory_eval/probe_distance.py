# -*- coding: utf-8 -*-
"""Layer 2 可分性探针：量真值与噪声在向量距离上分不分得开。

为什么先探针再写 cut
------------------
`RECALL_L2_MAX` 目前一个参数干两件事——既是相关性过滤器，又是注入量闸门。所以调它
只能在 recall 和 precision 之间平移：1.1→1.3 让 recall 58.3%→100%，同时噪声从 4.83
条涨到 9.00 条（新进来的 5.42 条里只有 1.25 条真值，边际精度 23%）。

出路是加一层只管注入、不管准入的截断。候选的 L2 距离是现成的连续信号
（`recall_neighbors` 返回 `(id, distance)`），但 `recall.py:90` 解到 `_distance`
就丢了，只拿 rank 喂 RRF——距离 0.6 的命中和 1.28 的命中权重完全相同。

**但「距离能用来切」是假设，不是事实。** 先量分布：真值和噪声的距离若重叠严重，
再精巧的切点也换不来 precision，那就该把力气全押到 LLM 判官上。本探针就是这个否证
机会，纯离线、零 LLM 成本。

怎么不污染被测对象
----------------
不改 `recall.py`，用 spy 包住两个通道函数后跑**真实** `build_structured_recall`：

- `MemoryStore.search_memories` → FTS/LIKE 通道返回的 record
- `ethan.memory.memory_vectors.recall_neighbors` → 向量通道的 `(id, distance)`

`recall.py:65` 是函数内 import，所以打模块属性能拦住。这样跑的是生产召回，探针只是
旁路记账。代价是拿不到"最终注入的那一屏"——但分布分析要的是**候选级**数据，正是
spy 捕到的这份。

三个产出
-------
1. 绝对距离分位数（真值 vs 噪声）——看重叠程度
2. 相对距离 `dist - min(dist in this query+domain)` 分位数——**这才是 Layer 2 要切的量**。
   绝对阈值假设"悬崖永远在同一处"，而标定逐 query 漂移（判官侧 60-case 已证 maxgap
   严格支配 thr7）；相对距离是逐 query 自适应的。
3. 通道一致性精度——双通道命中是否真的比单通道干净（决定"双通道无条件保留"这条规则）

外加一个 `REL_GAP` 五档模拟扫，直接给出 go/no-go 判据：**recall 掉了就不能开**。

用法
----
  uv run python tests/memory_eval/probe_distance.py --limit-cases 120
  uv run python tests/memory_eval/probe_distance.py --rows-out /tmp/probe.jsonl
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))  # 复用同目录的 eval_runner_precision

import ethan.core.paths as paths  # noqa: E402
from ethan.core.context import ETHAN_USER_ID  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402

# 复用 precision runner 的语料/干扰项/seed 逻辑，避免两套 harness 漂移
from eval_runner_precision import (  # noqa: E402
    _recall_jsonl_path,
    build_distractor_pool,
    pick_distractors,
    seed_case,
)

# 模拟扫的档位。∞ = 关闭 Layer 2（等价当前行为），必须保留作对照基线。
REL_GAPS = [0.10, 0.15, 0.20, 0.25, 0.35, 0.50, float("inf")]


def probe_case(case: dict, tmp: Path, max_items: int) -> dict:
    """跑真实召回，旁路记下每条候选的 (距离, 通道, 是否真值)。

    spy 记的是**过滤前**的通道输出，所以要在这里剔掉 restricted——它永不注入，
    留在分布里会污染噪声组。
    """
    fts_seen: dict[str, object] = {}       # id → record（含 content/sensitivity）
    vec_seen: dict[str, float] = {}        # id → 最小 l2 距离（多域调用取最小）
    fb_seen: dict[str, object] = {}        # 盲兜底路径（list_memories）返回的 record
    domains: dict[str, str] = {}           # id → 该 id 是在哪次 _collect（哪个域）里出现的

    real_search = MemoryStore.search_memories
    real_list = MemoryStore.list_memories

    def spy_search(self, query, **kwargs):
        rows = real_search(self, query, **kwargs)
        domain = kwargs.get("memory_domain", "?")
        for row in rows:
            fts_seen.setdefault(row.id, row)
            domains.setdefault(row.id, domain)
        return rows

    def spy_list(self, **kwargs):
        """`_collect` 里唯一调 list_memories 的地方就是盲兜底分支，所以这个 spy
        非空即等于「该域两通道皆空」——比推断调用次数准确。"""
        rows = real_list(self, **kwargs)
        domain = kwargs.get("memory_domain", "?")
        for row in rows:
            fb_seen.setdefault(row.id, row)
            domains.setdefault(row.id, domain)
        return rows

    import ethan.memory.memory_vectors as MV

    real_neighbors = MV.recall_neighbors

    def spy_neighbors(**kwargs):
        hits = real_neighbors(**kwargs)
        domain = kwargs.get("memory_domain", "?")
        for mid, dist in hits:
            if mid not in vec_seen or dist < vec_seen[mid]:
                vec_seen[mid] = dist
            domains.setdefault(mid, domain)
        return hits

    token = ETHAN_USER_ID.set("")
    contents: dict[str, str] = {}
    sens: dict[str, str] = {}
    lines: list[str] = []
    try:
        with patch.object(paths, "CONFIG_DIR", tmp), \
             patch.object(MemoryStore, "search_memories", spy_search), \
             patch.object(MemoryStore, "list_memories", spy_list), \
             patch.object(MV, "recall_neighbors", spy_neighbors):
            from ethan.memory.recall import build_structured_recall

            res = build_structured_recall(
                case["query"], mode=case.get("mode", ""), max_items=max_items
            )
            lines = list(res.items) if res else []

            # 向量侧只有 id，content 要回查库才能判定相关性
            store = MemoryStore()
            try:
                for mid in set(vec_seen) | set(fts_seen) | set(fb_seen):
                    rec = fts_seen.get(mid) or fb_seen.get(mid) or store.get_memory(mid)
                    if rec is None:
                        continue
                    contents[mid] = rec.content
                    sens[mid] = rec.sensitivity
            finally:
                store.close()
    finally:
        ETHAN_USER_ID.reset(token)

    seed_by_key = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
    relevant = {seed_by_key[k] for k in case["expected_keys"] if k in seed_by_key}

    rows = []
    for mid in set(vec_seen) | set(fts_seen) | set(fb_seen):
        if mid not in contents or sens.get(mid) == "restricted":
            continue
        rows.append({
            "case": case["id"],
            "domain": case["domain"],
            "memory_id": mid,
            "dist": vec_seen.get(mid),
            "in_fts": mid in fts_seen,
            "in_vec": mid in vec_seen,
            "in_fb": mid in fb_seen and mid not in fts_seen and mid not in vec_seen,
            "recall_domain": domains.get(mid, "?"),
            "relevant": contents[mid] in relevant,
        })

    # 相对距离按 (case, recall_domain) 归一——两域是两次独立 _collect，标定不共享
    by_domain: dict[str, list[float]] = collections.defaultdict(list)
    for r in rows:
        if r["dist"] is not None:
            by_domain[r["recall_domain"]].append(r["dist"])
    mins = {d: min(v) for d, v in by_domain.items() if v}
    for r in rows:
        base = mins.get(r["recall_domain"])
        r["rel_dist"] = None if (r["dist"] is None or base is None) else r["dist"] - base

    # 盲兜底：`_collect` 里唯一的 list_memories 调用就在两通道皆空的分支，
    # 所以 fb_seen 非空 == 至少一个域走了盲兜底。query 非空时这条路注入的是
    # 「最近更新的记忆」（store.py 的 ORDER BY 是 updated_at，不是 importance），
    # 零相关性依据。
    return {
        "rows": rows,
        "relevant_total": len(relevant),
        "injected": len(lines),
        "blind_fallback": bool(fb_seen and case["query"].strip()),
        "blind_rows": sum(1 for r in rows if r["in_fb"]),
    }


def _q(values: list[float]) -> str:
    if not values:
        return "        (空)"
    s = sorted(values)

    def pct(p):
        return s[min(len(s) - 1, int(len(s) * p))]

    return (f"n={len(s):<6} p10={pct(.10):.3f} p25={pct(.25):.3f} "
            f"p50={pct(.50):.3f} p75={pct(.75):.3f} p90={pct(.90):.3f} "
            f"mean={statistics.fmean(s):.3f}")


def simulate(rows: list[dict], rel_gap: float) -> tuple[int, int]:
    """按 Layer 2 规则模拟截断，返回 (保留的真值数, 保留的噪声数)。

    规则与计划一致：双通道命中无条件保留（一致性是强信号，RRF 已隐式奖励）；
    没有距离的候选（FTS 独占命中、盲兜底行）不参与距离截断，避免误杀精确命中；
    只有 vec 独占命中受相对断层约束。

    注意盲兜底行也落进"无距离"这一档，所以它们在每一档 REL_GAP 下都被原样保留 ——
    这不是漏洞而是事实：Layer 2 修不了盲兜底路径，那是 Step 3 的活。它会同等压低
    所有档位的 precision，档位之间的**相对**改善仍然可读。
    """
    kept_rel = kept_noise = 0
    for r in rows:
        keep = (
            (r["in_fts"] and r["in_vec"])          # 双通道一致
            or r["dist"] is None                    # 无距离信号，不切
            or r["rel_dist"] is None
            or r["rel_dist"] <= rel_gap             # vec 独占，看相对断层
        )
        if keep:
            if r["relevant"]:
                kept_rel += 1
            else:
                kept_noise += 1
    return kept_rel, kept_noise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-domain", type=int, default=20,
                    help="每域取前 N 条 case。语料按域分块存放，用 --limit-cases 会只取到一个域")
    ap.add_argument("--limit-cases", type=int, default=0, help="取前 N 条（跨域会失衡，仅调试用）")
    ap.add_argument("--distractors", type=int, default=40,
                    help="每 case 掺入的同域干扰项数。**必须显著大于 max_items**，"
                         "否则库比一屏还小，盲兜底把整库倒出来，测不出任何截断效果")
    ap.add_argument("--max-items", type=int, default=15)
    ap.add_argument("--rows-out", type=str, default="", help="逐候选行写入 jsonl")
    args = ap.parse_args()

    jsonl = _recall_jsonl_path()
    if not jsonl.exists():
        print(f"找不到 {jsonl}", file=sys.stderr)
        return 2

    all_cases = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = build_distractor_pool(all_cases)

    if args.limit_cases:
        cases = all_cases[: args.limit_cases]
    else:
        by_dom: dict[str, list[dict]] = collections.defaultdict(list)
        for c in all_cases:
            by_dom[c["domain"]].append(c)
        cases = [c for dom in sorted(by_dom) for c in by_dom[dom][: args.per_domain]]

    l2_max = __import__("ethan.memory.memory_vectors", fromlist=["x"]).RECALL_L2_MAX
    print(f"RECALL_L2_MAX = {l2_max}  (env ETHAN_MEMORY_RECALL_L2)")
    print(f"干扰项池: " + ", ".join(f"{d}={len(v)}" for d, v in sorted(pool.items())))
    print(f"probing {len(cases)} cases (+{args.distractors} distractors each)...", flush=True)

    rows: list[dict] = []
    blind = 0
    total_relevant = 0
    per_case: list[dict] = []
    for i, case in enumerate(cases):
        tmp = Path(tempfile.mkdtemp(prefix="probe_"))
        seed_case(case, pick_distractors(case, pool, args.distractors), tmp)
        out = probe_case(case, tmp, args.max_items)
        rows.extend(out["rows"])
        blind += int(out["blind_fallback"])
        total_relevant += out["relevant_total"]
        per_case.append({"id": case["id"], "domain": case["domain"],
                         "rows": out["rows"], "relevant_total": out["relevant_total"]})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(cases)}", flush=True)

    rel = [r for r in rows if r["relevant"]]
    noise = [r for r in rows if not r["relevant"]]

    print(f"\n候选总数 {len(rows)}（真值 {len(rel)} / 噪声 {len(noise)}）"
          f"  语料真值总数 {total_relevant}")
    print(f"盲兜底 case: {blind}/{len(cases)} ({blind/max(1,len(cases)):.1%})"
          f"  ← 两通道皆空仍注入，零相关性依据")

    print("\n=== 1. 绝对 L2 距离（仅向量命中）===")
    print(f"真值  {_q([r['dist'] for r in rel if r['dist'] is not None])}")
    print(f"噪声  {_q([r['dist'] for r in noise if r['dist'] is not None])}")

    print("\n=== 2. 相对距离 dist - min(同 case 同域) ===")
    print(f"真值  {_q([r['rel_dist'] for r in rel if r.get('rel_dist') is not None])}")
    print(f"噪声  {_q([r['rel_dist'] for r in noise if r.get('rel_dist') is not None])}")

    print("\n=== 3. 通道一致性精度 ===")
    print(f"{'通道':<14}{'候选数':>8}{'真值':>8}{'精度':>9}")
    for label, pred in (
        ("双通道", lambda r: r["in_fts"] and r["in_vec"]),
        ("仅 FTS", lambda r: r["in_fts"] and not r["in_vec"]),
        ("仅向量", lambda r: r["in_vec"] and not r["in_fts"]),
        ("盲兜底", lambda r: r["in_fb"]),
    ):
        sub = [r for r in rows if pred(r)]
        hit = sum(1 for r in sub if r["relevant"])
        print(f"{label:<14}{len(sub):>8}{hit:>8}{(hit/len(sub) if sub else 0):>8.1%}")

    print("\n=== 4. REL_GAP 模拟扫（判据：recall 必须仍是 100%）===")
    print(f"{'REL_GAP':>9}{'保留真值':>10}{'保留噪声':>10}{'precision':>11}{'recall':>9}")
    base_rel = len(rel)
    for gap in REL_GAPS:
        kr, kn = simulate(rows, gap)
        prec = kr / (kr + kn) if (kr + kn) else 0.0
        rc = kr / base_rel if base_rel else 0.0
        tag = "  ← 当前行为" if gap == float("inf") else ""
        label = "∞" if gap == float("inf") else f"{gap:.2f}"
        print(f"{label:>9}{kr:>10}{kn:>10}{prec:>10.1%}{rc:>8.1%}{tag}")

    if args.rows_out:
        with open(args.rows_out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n逐候选行已写入 {args.rows_out}（{len(rows)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
