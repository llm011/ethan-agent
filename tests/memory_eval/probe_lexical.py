# -*- coding: utf-8 -*-
"""词法通道探针：FTS/LIKE 到底能不能命中中文 query，以及修好它值不值。

为什么有这个探针
--------------
`probe_distance.py` 本来是去量向量距离的可分性（结论：不可分，Layer 2 否证）。
但它的通道统计意外报出一件更基本的事——**1340 条候选里 FTS 通道命中 0 条**：

    通道       候选数    真值     精度
    双通道         0      0     0.0%
    仅 FTS        0      0     0.0%
    仅向量      1340    190    14.2%

也就是说 `recall.py` 里那套「FTS 精确通道 + 向量语义通道，RRF 融合」实际上是**单通道**。
RRF 在只有一路输入时退化成恒等排序，注释里写的「向量通道补齐 FTS 的 CJK 分词短板」
说反了：不是补齐，是全部替代。

这直接影响两个已有判断：
1. `probe_distance` 里「双通道一致性是强信号」这个假设**从来没被测到过**（样本 0）。
   一致性截断可能才是真正的 Layer 2，但前提是词法通道先活过来。
2. 精确率 14% 的锅有多少在「只有一路召回」上，目前未知。

本探针在离线小语料上对照几种词法方案，回答「修好值不值」。不碰生产代码。

被测的两个独立缺陷
----------------
(a) **tokenizer**：`store.py` 建 `memory_fts` 时没有 `tokenize=` 子句，走默认
    unicode61。它把整段 CJK 当**一个 token**，而 FTS5 是 token 相等匹配、不做子串，
    所以 "工程师" 匹配不上 "用户是一名后端工程师"。
(b) **query 构造**：`store.py:594` 把 query 原样传给 MATCH，不分词。FTS5 对空格
    分隔的裸词是**隐式 AND**，所以多词只会越查越窄，永远不会 OR。

两个缺陷必须一起看：只换 tokenizer 不改 query 构造，对话式 query 依然全灭
（trigram 下 "我是做什么工作的" 整串当查询要求所有 trigram 都在，实测 0 命中）。
所以对照里把 tokenizer 和 query 策略拆成两个维度。

用法
----
  uv run python tests/memory_eval/probe_lexical.py --per-domain 20
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sqlite3
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

CJK = re.compile(r"[\u3400-\u9fff]+")
ASCII_WORD = re.compile(r"[A-Za-z0-9_]+")


def ngrams(text: str, n: int) -> list[str]:
    """CJK 段切 n-gram，ASCII 词整取。词法索引/查询两侧共用，保证口径一致。"""
    out: list[str] = []
    for run in CJK.findall(text):
        out.extend(run[i : i + n] for i in range(len(run) - n + 1))
    out.extend(ASCII_WORD.findall(text.lower()))
    return out


def _match_expr(terms: list[str]) -> str:
    """OR 拼 MATCH 表达式。每个 term 加双引号当字符串字面量，避开 FTS5 语法字符。"""
    uniq = list(dict.fromkeys(t for t in terms if t.strip()))
    return " OR ".join(f'"{t}"' for t in uniq)


# ── 四种词法方案 ──────────────────────────────────────────────────────────
# 每项: (标签, tokenize 子句, 索引列变换, query → MATCH 表达式)
STRATEGIES = [
    ("unicode61+原样 (当前生产)", "", lambda c: c, lambda q: f'"{q}"'),
    ("trigram+原样",              "tokenize='trigram'", lambda c: c, lambda q: f'"{q}"'),
    ("trigram+OR 三字",           "tokenize='trigram'", lambda c: c,
     lambda q: _match_expr(ngrams(q, 3))),
    ("unicode61+二字索引+OR 二字", "", lambda c: " ".join(ngrams(c, 2)),
     lambda q: _match_expr(ngrams(q, 2))),
]


def lexical_hits(corpus: list[str], query: str, tok: str, xform, qbuild) -> list[str]:
    """在小语料上建一次性 FTS 索引跑 query，返回按 bm25 排序的命中 content。"""
    con = sqlite3.connect(":memory:")
    try:
        clause = f", {tok}" if tok else ""
        con.execute(f"CREATE VIRTUAL TABLE f USING fts5(idx UNINDEXED, body{clause})")
        con.executemany(
            "INSERT INTO f(idx, body) VALUES (?, ?)",
            [(str(i), xform(c)) for i, c in enumerate(corpus)],
        )
        expr = qbuild(query)
        if not expr.strip() or expr == '""':
            return []
        try:
            rows = con.execute(
                "SELECT idx FROM f WHERE f MATCH ? ORDER BY bm25(f)", (expr,)
            ).fetchall()
        except sqlite3.DatabaseError:
            return []          # MATCH 语法错 = 生产里落 LIKE 兜底，这里记 0 命中
        return [corpus[int(r[0])] for r in rows]
    finally:
        con.close()


def like_hits(corpus: list[str], query: str) -> list[str]:
    """复刻 store.py 的 LIKE 兜底：**整串** query 当 %substring%，不分词。"""
    return [c for c in corpus if query in c]


def vector_hits(corpus: list[str], query: str, l2_max: float) -> list[tuple[str, float]]:
    """向量通道：小语料上暴力算 L2，按距离升序，截断到 l2_max。"""
    from ethan.memory.embeddings import embed_sync

    qv = embed_sync(query)
    scored = []
    for c in corpus:
        cv = embed_sync(c)
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(qv, cv)))
        if d <= l2_max:
            scored.append((c, d))
    scored.sort(key=lambda x: x[1])
    return scored


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-domain", type=int, default=20)
    ap.add_argument("--distractors", type=int, default=40)
    ap.add_argument("--l2-max", type=float, default=1.3)
    ap.add_argument("--limit", type=int, default=15, help="每通道取前 N 条（比 max_items）")
    args = ap.parse_args()

    jsonl = _recall_jsonl_path()
    if not jsonl.exists():
        print(f"找不到 {jsonl}", file=sys.stderr)
        return 2

    all_cases = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    pool = build_distractor_pool(all_cases)
    by_dom: dict[str, list[dict]] = collections.defaultdict(list)
    for c in all_cases:
        by_dom[c["domain"]].append(c)
    cases = [c for dom in sorted(by_dom) for c in by_dom[dom][: args.per_domain]]
    print(f"{len(cases)} cases  干扰项 {args.distractors}/case  L2_MAX={args.l2_max}\n")

    # 每个方案累计 (命中真值, 命中总数, 真值总数, 有命中的 case 数)
    stats = {label: [0, 0, 0, 0] for label, *_ in STRATEGIES}
    stats["LIKE 兜底 (整串子串)"] = [0, 0, 0, 0]
    stats["向量 (当前实际唯一通道)"] = [0, 0, 0, 0]
    # 一致性：向量 ∩ 最佳词法方案
    agree = [0, 0]      # [命中真值, 命中总数]
    vec_only = [0, 0]
    lex_only = [0, 0]

    for n, case in enumerate(cases):
        seed_by_key = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
        relevant = {seed_by_key[k] for k in case["expected_keys"] if k in seed_by_key}
        if not relevant:
            continue
        corpus = [s["content"] for s in case["seed_memories"]]
        corpus += [s["content"] for s in pick_distractors(case, pool, args.distractors)]
        corpus = list(dict.fromkeys(corpus))
        query = case["query"]

        results: dict[str, list[str]] = {}
        for label, tok, xform, qbuild in STRATEGIES:
            results[label] = lexical_hits(corpus, query, tok, xform, qbuild)[: args.limit]
        results["LIKE 兜底 (整串子串)"] = like_hits(corpus, query)[: args.limit]
        vec = [c for c, _ in vector_hits(corpus, query, args.l2_max)][: args.limit]
        results["向量 (当前实际唯一通道)"] = vec

        for label, hits in results.items():
            s = stats[label]
            s[0] += sum(1 for h in hits if h in relevant)
            s[1] += len(hits)
            s[2] += len(relevant)
            s[3] += int(bool(hits))

        best_lex = set(results["unicode61+二字索引+OR 二字"])
        vecset = set(vec)
        for c in vecset & best_lex:
            agree[0] += c in relevant
            agree[1] += 1
        for c in vecset - best_lex:
            vec_only[0] += c in relevant
            vec_only[1] += 1
        for c in best_lex - vecset:
            lex_only[0] += c in relevant
            lex_only[1] += 1

        if (n + 1) % 40 == 0:
            print(f"  {n+1}/{len(cases)}", flush=True)

    print(f"\n{'方案':<30}{'召回条数':>9}{'精度':>8}{'recall':>9}{'有命中 case':>12}")
    print("-" * 70)
    for label in list(stats):
        hit, tot, rel, ncase = stats[label]
        prec = hit / tot if tot else 0.0
        rc = hit / rel if rel else 0.0
        print(f"{label:<30}{tot/len(cases):>9.2f}{prec:>7.1%}{rc:>8.1%}"
              f"{ncase/len(cases):>11.0%}")

    print("\n=== 通道一致性（向量 vs unicode61+二字索引）===")
    print(f"{'集合':<20}{'条数':>8}{'真值':>7}{'精度':>8}")
    for label, (h, t) in (("双通道一致", agree), ("仅向量", vec_only), ("仅词法", lex_only)):
        print(f"{label:<20}{t:>8}{h:>7}{(h/t if t else 0):>7.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
