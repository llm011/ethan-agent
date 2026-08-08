# -*- coding: utf-8 -*-
"""重排 A/B：同一批候选，BGE/RRF 排序 vs LLM 判官排序，测 nDCG / P@k / 切点策略。

为什么需要这个 harness
--------------------
`eval_runner_precision.py` 量出的基线：nDCG 0.689、P@k 42.6%、noise 等于掺入的
干扰项条数（一条不漏全召回）。两个缺口——排序不干净、以及**完全没有 query 相关
的切点决策**（只有固定 max_items）。本 harness 测「LLM 判官」能不能补这两个缺口。

设计要点
--------
1. **候选集来自真实 `_collect`**，不是手搓。判官只做重排，不改变候选集合——
   所以 recall 上界锁死在 BGE 召回到的那些，判官救不回检索阶段就丢掉的。
2. **候选顺序打乱后再喂判官**（按 case id 确定性播种）。若按 BGE 顺序喂，
   判官会锚定在原排序上，A/B 就失去了独立性。
3. **多判官并列跑同一批候选**，头对头比较，避免用单模型结果做模型选型。
4. **分歧清单**：判官高分但标签是噪声的、判官低分但标签是相关的，逐条落盘。
   delta 会被标签质量污染（"做什么的" 是否该召回 activity 本身有歧义），
   只看 delta 会把"判官比标签更合理"误判成"判官错"。

用法
----
  uv run python tests/memory_eval/ab_rerank.py --per-domain 2            # smoke
  uv run python tests/memory_eval/ab_rerank.py --per-domain 10
  uv run python tests/memory_eval/ab_rerank.py --judges new-api/claude-opus-5,claude-haiku-4.5
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import os
import random
import re
import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import ethan.core.paths as paths  # noqa: E402
from ethan.core.context import ETHAN_USER_ID  # noqa: E402
from ethan.memory.records import MemoryDomain, MemoryStatus  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402

from eval_runner_precision import (  # noqa: E402
    _recall_jsonl_path,
    build_distractor_pool,
    pick_distractors,
    seed_case,
)

JUDGE_SYSTEM = "你是记忆相关性判官，只输出 JSON 数组，不要解释。"


def judge_prompt(query: str, cands: list[tuple[str, str]]) -> str:
    lines = "".join(f"{i}. [{dim}] {content}\n" for i, (dim, content) in enumerate(cands))
    return (
        f"用户 query: {query}\n\n候选记忆：\n{lines}\n"
        "对每条打 0-10 分：10=直接回答 query，5=相关但不直接回答，0=完全无关。\n"
        '只输出 JSON 数组，格式 [{"i":0,"score":9}]，每条候选都要给分。'
    )


def collect_candidates(case: dict, tmp: Path, limit: int) -> list[Any]:  # noqa: F821
    """跑真实 _collect 拿候选（保序=BGE/RRF 排序）。返回 memory 对象列表。"""
    token = ETHAN_USER_ID.set("")
    try:
        with patch.object(paths, "CONFIG_DIR", tmp):
            from ethan.memory.recall import _collect, _is_companion_mode

            store = MemoryStore()
            try:
                hits = _collect(
                    store, case["query"],
                    domain=MemoryDomain.GENERAL.value, max_items=limit,
                )
                if _is_companion_mode(case.get("mode", "")):
                    hits += _collect(
                        store, case["query"],
                        domain=MemoryDomain.COMPANION.value, max_items=limit,
                    )
                # 脱离 store 生命周期，只留需要的字段
                return [(m.dimension, m.content, m.memory_key) for m in hits]
            finally:
                store.close()
    finally:
        ETHAN_USER_ID.reset(token)


_SCORE_RE = re.compile(r'"i"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*(-?\d+(?:\.\d+)?)')
_SCORE_RE_REV = re.compile(r'"score"\s*:\s*(-?\d+(?:\.\d+)?)\s*,\s*"i"\s*:\s*(\d+)')


def parse_scores(text: str) -> dict[int, float]:
    """从判官返回里抽 {候选下标: 分数}，三层容错，全失败返回空 dict。

    实测的失败形态：包 ```json fence、JSON 前后带解释、尾随逗号、字段顺序反转。
    第 3 层正则不要求整段是合法 JSON——逐对抽 i/score，比 json.loads 宽容得多，
    单个语法错不会让整次判官作废（一次 parse_failed = 该 case 退回 RRF 原序）。
    """
    out: dict[int, float] = {}

    def _absorb(arr) -> None:
        for item in arr or []:
            try:
                out[int(item["i"])] = float(item["score"])
            except Exception:
                continue

    # 1) 首尾方括号之间当数组——同时吃掉 code fence 和前后解释文本
    try:
        _absorb(json.loads(text[text.index("[") : text.rindex("]") + 1]))
    except Exception:
        pass
    if out:
        return out
    # 2) 整段当 JSON，兼容 {"scores": [...]} 这种包一层的
    try:
        payload = json.loads(text.strip().strip("`"))
        _absorb(payload.get("scores") if isinstance(payload, dict) else payload)
    except Exception:
        pass
    if out:
        return out
    # 3) 正则逐对抽，容忍尾随逗号 / 截断 / 字段顺序反转
    for m in _SCORE_RE.finditer(text):
        out[int(m.group(1))] = float(m.group(2))
    for m in _SCORE_RE_REV.finditer(text):
        out.setdefault(int(m.group(2)), float(m.group(1)))
    return out


async def run_judge(model: str, query: str, cands: list[tuple[str, str]],
                    retries: int = 1) -> tuple[dict[int, float], dict]:
    """返回 ({候选下标: 分数}, meta)。空 dict = 重试后仍解析失败。

    meta 带 attempts / latency_s / raw_failures / missing，用于报 parse 失败率、
    延迟、以及判官漏打分的候选数——生产上这几个数决定要不要上 schema 约束。
    """
    from ethan.providers.base import Message
    from ethan.providers.manager import create_provider

    provider = create_provider(model)
    meta: dict = {"attempts": 0, "latency_s": 0.0, "raw_failures": [], "missing": []}
    prompt = judge_prompt(query, cands)

    for attempt in range(retries + 1):
        meta["attempts"] += 1
        msgs = [Message(role="user", content=prompt)]
        if attempt:
            # 把上一次的坏输出回灌再纠格式，比原样重发更容易拉回来
            msgs.append(Message(role="assistant", content=meta["raw_failures"][-1][:500]))
            msgs.append(Message(role="user", content=(
                f"格式不对，没解析出分数。只输出 JSON 数组，{len(cands)} 条候选每条一项，"
                '形如 [{"i":0,"score":9}]，不要 code fence、不要解释。')))
        t0 = time.perf_counter()
        resp = await provider.chat(msgs, system=JUDGE_SYSTEM)
        meta["latency_s"] += time.perf_counter() - t0
        text = resp.content or ""
        scores = parse_scores(text)
        if scores:
            meta["missing"] = [i for i in range(len(cands)) if i not in scores]
            return scores, meta
        meta["raw_failures"].append(text)
    return {}, meta


def _ndcg(relevance: list[int], ideal_count: int) -> float:
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevance))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


def _metrics(relevance: list[int], n_relevant: int) -> dict:
    k = n_relevant
    return {
        "ndcg": _ndcg(relevance, k) if k else 0.0,
        "p_at_k": (sum(relevance[:k]) / k) if k else 0.0,
        "p_at_all": (sum(relevance) / len(relevance)) if relevance else 0.0,
    }


def baseline_cuts(relevance: list[int], n_relevant: int) -> dict:
    """RRF 原序下各切点的表现，用作 fallback 条目的 cuts。

    topK 在原序上照样能切；thr/maxgap 需要 query 相关的分数，RRF 没有——所以
    fallback 时这几档等于"不切"，整屏候选全注入。这正是今天线上的行为。
    """
    out = {}
    for k in (3, 5, 8):
        rel = relevance[:k]
        out[f"top{k}"] = {
            "precision": (sum(rel) / len(rel)) if rel else 0.0,
            "recall": (sum(rel) / n_relevant) if n_relevant else 0.0,
        }
    p_all = (sum(relevance) / len(relevance)) if relevance else 0.0
    for name in ("thr6", "thr7", "maxgap"):
        out[name] = {"precision": p_all, "recall": 1.0 if n_relevant else 0.0,
                     "kept": len(relevance)}
    return out


def cut_strategies(scores: list[float], relevance: list[int], n_relevant: int) -> dict:
    """在判官分数上试几种切点，报 precision / recall。scores 已按降序对齐 relevance。"""
    out = {}
    for k in (3, 5, 8):
        rel = relevance[:k]
        out[f"top{k}"] = {
            "precision": (sum(rel) / len(rel)) if rel else 0.0,
            "recall": (sum(rel) / n_relevant) if n_relevant else 0.0,
        }
    for thr in (6.0, 7.0):
        idx = [i for i, s in enumerate(scores) if s >= thr]
        rel = [relevance[i] for i in idx]
        out[f"thr{int(thr)}"] = {
            "precision": (sum(rel) / len(rel)) if rel else 0.0,
            "recall": (sum(rel) / n_relevant) if n_relevant else 0.0,
            "kept": len(rel),
        }
    # 最大断层：相邻分数差最大处切断
    if len(scores) >= 2:
        gaps = [(scores[i] - scores[i + 1], i + 1) for i in range(len(scores) - 1)]
        _, cut = max(gaps, key=lambda g: (g[0], -g[1]))
    else:
        cut = len(scores)
    rel = relevance[:cut]
    out["maxgap"] = {
        "precision": (sum(rel) / len(rel)) if rel else 0.0,
        "recall": (sum(rel) / n_relevant) if n_relevant else 0.0,
        "kept": cut,
    }
    return out


def prepare_case(case: dict, pool, n_distract: int, limit: int) -> dict | None:
    """同步阶段：seed + 真实 _collect + BEFORE 指标。

    必须与判官阶段严格分离。seed_case 走真实 admission（含 ONNX 向量化），
    每 case 阻塞数秒且完全同步；若和判官调用混在同一批协程里，事件循环会被
    别的 case 的 seed 占住几十秒，在飞的 HTTP 连接得不到调度 → 全部超时成
    APIConnectionError（实测 24/24 失败就是这么来的）。
    """
    tmp = Path(tempfile.mkdtemp(prefix="ab_"))
    distractors = pick_distractors(case, pool, n_distract)
    seed_case(case, distractors, tmp)
    cands = collect_candidates(case, tmp, limit)
    if not cands:
        return None

    seed_by_key = {s["memory_key"]: s["content"] for s in case["seed_memories"]}
    relevant_contents = {seed_by_key[k] for k in case["expected_keys"] if k in seed_by_key}
    n_relevant = len(relevant_contents)
    if n_relevant == 0:
        return None

    # BEFORE：_collect 原序
    before_rel = [1 if c in relevant_contents else 0 for _, c, _ in cands]

    # 打乱后喂判官，避免锚定 BGE 顺序
    order = list(range(len(cands)))
    random.Random(case["id"]).shuffle(order)
    shuffled = [(cands[i][0], cands[i][1]) for i in order]

    return {
        "id": case["id"], "domain": case["domain"], "query": case["query"],
        "n_candidates": len(cands), "n_relevant": n_relevant,
        "before": _metrics(before_rel, n_relevant),
        "before_cuts": baseline_cuts(before_rel, n_relevant),
        "judges": {},
        "_shuffled": shuffled,
        "_relevant": relevant_contents,
    }


def _fallback_entry(result: dict, reason: str, meta: dict | None = None) -> dict:
    """判官不可用时退回 RRF 原序——生产语义就是这样，不能记成"召回为空"。

    "after" 直接取 BEFORE 的指标：这样汇总出来的 AFTER 均值天然含 fallback 惩罚，
    是能拿去做上线决策的数字，而非只统计成功样本的乐观值。
    """
    return {
        "after": dict(result["before"]),
        "cuts": result["before_cuts"],
        "disagreements": [],
        "scored_count": 0,
        "fallback": reason,
        "meta": meta or {},
    }


async def judge_case(result: dict, judges: list[str], sem: asyncio.Semaphore,
                     retries: int, raw_log: list) -> dict:
    """异步阶段：只发判官请求，不做任何阻塞工作。"""
    shuffled = result["_shuffled"]
    relevant_contents = result["_relevant"]
    n_relevant = result["n_relevant"]
    case = {"id": result["id"], "query": result["query"]}

    for model in judges:
        async with sem:
            try:
                scored, meta = await run_judge(model, case["query"], shuffled, retries)
            except Exception as exc:
                # 完整 traceback 立刻落 stderr——只留 "APIConnectionError" 这个类名
                # 分不出是 timeout / proxy / base_url 错，debug 时全靠这几行
                print(f"\n!! judge 异常 case={case['id']} model={model}\n"
                      f"{traceback.format_exc()}", file=sys.stderr, flush=True)
                result["judges"][model] = _fallback_entry(
                    result, f"{type(exc).__name__}: {exc}"[:200])
                continue
        for raw in meta.get("raw_failures", []):
            raw_log.append({"case": case["id"], "model": model,
                            "query": case["query"], "n_cands": len(shuffled), "raw": raw})
        if not scored:
            result["judges"][model] = _fallback_entry(result, "parse_failed", meta)
            continue

        # 判官漏打分的候选按 -1 排到末尾，等于"判官没表态就别注入"
        ranked = sorted(range(len(shuffled)), key=lambda i: -scored.get(i, -1.0))
        after_rel = [1 if shuffled[i][1] in relevant_contents else 0 for i in ranked]
        after_scores = [scored.get(i, -1.0) for i in ranked]

        disagree = []
        for i in range(len(shuffled)):
            dim, content = shuffled[i]
            s = scored.get(i)
            if s is None:
                continue
            is_rel = content in relevant_contents
            if s >= 6 and not is_rel:
                disagree.append({"kind": "judge_high_label_noise", "score": s,
                                 "dimension": dim, "content": content})
            elif s <= 3 and is_rel:
                disagree.append({"kind": "judge_low_label_relevant", "score": s,
                                 "dimension": dim, "content": content})

        result["judges"][model] = {
            "after": _metrics(after_rel, n_relevant),
            "cuts": cut_strategies(after_scores, after_rel, n_relevant),
            "disagreements": disagree,
            "scored_count": len(scored),
            "meta": meta,
        }
    return result


async def main_async(args) -> int:
    jsonl = _recall_jsonl_path()
    if not jsonl.exists():
        print(f"找不到 {jsonl}", file=sys.stderr)
        return 2
    all_cases = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = build_distractor_pool(all_cases)

    by_domain = collections.defaultdict(list)
    for c in all_cases:
        by_domain[c["domain"]].append(c)
    sample = []
    for dom in sorted(by_domain):
        sample.extend(by_domain[dom][: args.per_domain])

    judges = [m.strip() for m in args.judges.split(",") if m.strip()]
    print(f"判官: {judges}")
    print(f"样本: {len(sample)} case ({args.per_domain}/域) × {len(judges)} 判官 "
          f"= {len(sample)*len(judges)} 次调用")

    # 阶段一：全部 seed + _collect 跑完（同步，不与判官请求交错）
    print("阶段一 seed + _collect ...", flush=True)
    prepared = []
    for i, c in enumerate(sample, 1):
        r = prepare_case(c, pool, args.distractors, args.limit)
        if r:
            prepared.append(r)
        if i % 10 == 0:
            print(f"  seed {i}/{len(sample)}", flush=True)
    if not prepared:
        print("无有效候选", file=sys.stderr)
        return 1

    # 阶段二：只剩纯 IO，事件循环不再被 ONNX / sqlite 阻塞
    print(f"阶段二 判官打分（{len(prepared)} case × {len(judges)} 判官）...", flush=True)
    sem = asyncio.Semaphore(args.concurrency)
    raw_log: list = []
    tasks = [judge_case(r, judges, sem, args.retries, raw_log) for r in prepared]
    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        results.append(await coro)
        if i % 10 == 0:
            print(f"  judge {i}/{len(tasks)}", flush=True)

    if not results:
        print("无有效结果", file=sys.stderr)
        return 1

    def avg(rows, fn):
        vals = [fn(r) for r in rows]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else 0.0

    print(f"\n=== 排序质量（{len(results)} case）===")
    print(f"{'':<26} {'nDCG':>7} {'P@k':>7} {'P@all':>7}")
    print(f"{'BEFORE (BGE/RRF)':<26} {avg(results, lambda r: r['before']['ndcg']):>7.3f} "
          f"{avg(results, lambda r: r['before']['p_at_k']):>6.1%} "
          f"{avg(results, lambda r: r['before']['p_at_all']):>6.1%}")
    # 含 fallback 的全样本均值——这是上线决策该看的数字。
    # 另报纯成功样本，用来区分"判官不行"和"链路不稳"。
    for m in judges:
        rows = [r for r in results if r["judges"].get(m)]
        fb = [r for r in rows if r["judges"][m].get("fallback")]
        good = [r for r in rows if not r["judges"][m].get("fallback")]
        tag = f"AFTER {m}"
        print(f"{tag:<26} {avg(rows, lambda r: r['judges'][m]['after']['ndcg']):>7.3f} "
              f"{avg(rows, lambda r: r['judges'][m]['after']['p_at_k']):>6.1%} "
              f"{avg(rows, lambda r: r['judges'][m]['after']['p_at_all']):>6.1%}"
              + (f"   (含 {len(fb)} 次 fallback)" if fb else ""))
        if fb:
            print(f"{'  └ 仅成功样本':<26} {avg(good, lambda r: r['judges'][m]['after']['ndcg']):>7.3f} "
                  f"{avg(good, lambda r: r['judges'][m]['after']['p_at_k']):>6.1%} "
                  f"{avg(good, lambda r: r['judges'][m]['after']['p_at_all']):>6.1%}"
                  f"   (n={len(good)})")

    print(f"\n=== 切点策略（precision / recall）===")
    for m in judges:
        ok = [r for r in results if "cuts" in r["judges"].get(m, {})]
        if not ok:
            continue
        print(f"\n{m}:")
        for strat in ("top3", "top5", "top8", "thr6", "thr7", "maxgap"):
            p = avg(ok, lambda r: r["judges"][m]["cuts"][strat]["precision"])
            rc = avg(ok, lambda r: r["judges"][m]["cuts"][strat]["recall"])
            kept = avg(ok, lambda r: r["judges"][m]["cuts"][strat].get("kept"))
            kept_s = f"  保留 {kept:.1f} 条" if kept else ""
            print(f"  {strat:<8} P={p:>6.1%}  R={rc:>6.1%}{kept_s}")

    print(f"\n=== 分域 nDCG ===")
    doms = sorted({r["domain"] for r in results})
    header = f"{'domain':<22} {'before':>8}" + "".join(f" {m.split('/')[-1][:14]:>15}" for m in judges)
    print(header)
    for dom in doms:
        rows = [r for r in results if r["domain"] == dom]
        line = f"{dom:<22} {avg(rows, lambda r: r['before']['ndcg']):>8.3f}"
        for m in judges:
            ok = [r for r in rows if "after" in r["judges"].get(m, {})]
            line += f" {avg(ok, lambda r: r['judges'][m]['after']['ndcg']):>15.3f}"
        print(line)

    print(f"\n=== 判官 vs 标签 分歧 ===")
    for m in judges:
        hi = [d for r in results for d in r["judges"].get(m, {}).get("disagreements", [])
              if d["kind"] == "judge_high_label_noise"]
        lo = [d for r in results for d in r["judges"].get(m, {}).get("disagreements", [])
              if d["kind"] == "judge_low_label_relevant"]
        print(f"\n{m}: 判官≥6但标签=噪声 {len(hi)} 条; 判官≤3但标签=相关 {len(lo)} 条")
        seen = set()
        for d in sorted(hi, key=lambda x: -x["score"]):
            key = (d["dimension"], d["content"])
            if key in seen:
                continue
            seen.add(key)
            print(f"    高分噪声 {d['score']:>4}  [{d['dimension']}] {d['content'][:32]}")
            if len(seen) >= 8:
                break
        for d in lo[:5]:
            print(f"    低分相关 {d['score']:>4}  [{d['dimension']}] {d['content'][:32]}")

    # 生产可行性看这张表：parse 失败率和 fallback 率决定要不要上 schema 约束，
    # 延迟决定能不能挂在 recall_memory 的同步路径上。
    print(f"\n=== 判官稳定性 / 成本 ===")
    print(f"{'model':<26} {'首轮OK':>7} {'重试后OK':>8} {'fallback':>9} "
          f"{'漏打分':>7} {'延迟s':>7}")
    for m in judges:
        rows = [r for r in results if r["judges"].get(m)]
        if not rows:
            continue
        entries = [r["judges"][m] for r in rows]
        fb = [e for e in entries if e.get("fallback")]
        good = [e for e in entries if not e.get("fallback")]
        first_ok = [e for e in good if e.get("meta", {}).get("attempts", 1) == 1]
        retried_ok = len(good) - len(first_ok)
        missing = sum(len(e.get("meta", {}).get("missing", [])) for e in good)
        lat = [e["meta"]["latency_s"] for e in entries if e.get("meta", {}).get("latency_s")]
        print(f"{m:<26} {len(first_ok):>3}/{len(entries):<3} {retried_ok:>8} "
              f"{len(fb):>9} {missing:>7} "
              f"{(sum(lat)/len(lat) if lat else 0):>7.1f}")
        for e in fb:
            print(f"    fallback 原因: {e['fallback'][:80]}")

    if args.raw_out and raw_log:
        Path(args.raw_out).write_text(json.dumps(raw_log, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        print(f"\n{len(raw_log)} 条解析失败原始输出已写入 {args.raw_out}")
    elif raw_log:
        print(f"\n注意: {len(raw_log)} 次解析失败（未落盘，加 --raw-out 可诊断）")

    if args.json_out:
        # _shuffled/_relevant 是阶段间传递的内部字段，_relevant 还是 set（不可序列化）
        clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
        Path(args.json_out).write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        print(f"\n逐 case 结果已写入 {args.json_out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-domain", type=int, default=2, help="每域抽样 case 数")
    ap.add_argument("--distractors", type=int, default=15)
    ap.add_argument("--limit", type=int, default=20, help="_collect 的 max_items（给判官的候选上限）")
    ap.add_argument("--judges", type=str,
                    default="new-api/claude-opus-5,claude-haiku-4.5")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--retries", type=int, default=1, help="解析失败后重试次数")
    ap.add_argument("--json-out", type=str, default="")
    ap.add_argument("--raw-out", type=str, default="",
                    help="解析失败的原始模型输出落盘路径（诊断格式问题用）")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
