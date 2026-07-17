# -*- coding: utf-8 -*-
"""Memory eval — live 模式评测(真 LLM 提取)。

对 golden case 真跑 StructuredMemoryExtractor.extract()(真 provider),
把产出候选与 expected 比对:
  - dimension: 精确匹配
  - content: char 3-gram Jaccard 相似度 >= tau 判为语义命中
  - quote: 必须是 user 消息精确子串
  - 负样本(expected=[]): 产生候选即误提取;companion_leak 不得出 companion 维度;
    diagnostic_reject 不得出含诊断词候选(应被 extractor 内部拦截)

指标: 总体/分域 P/R/F1、quote 合规率、零产出率(含 JSON parse 失败)、
GAP 维度产出率(应为 0,白名单外维度到不了输出)。

用法:
  uv run python eval_runner_live.py                     # 每域抽 20 条
  uv run python eval_runner_live.py --per-domain 5      # 快速冒烟
  uv run python eval_runner_live.py --domains companion --per-domain 30
  uv run python eval_runner_live.py --all               # 全量(贵,慎用)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from ethan.memory.extractors import SourceMessage, StructuredMemoryExtractor  # noqa: E402

GOLDEN = HERE / "golden"
REPORT = HERE / "report_live.json"


def ngrams(text: str, n: int = 3) -> set[str]:
    text = text.lower().strip()
    if len(text) <= n:
        return {text}
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def content_sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ga, gb = ngrams(a), ngrams(b)
    return len(ga & gb) / len(ga | gb) if (ga | gb) else 0.0


def sample_cases(cases: list[dict], per_domain: int | None) -> list[dict]:
    """等距抽样(确定性,覆盖各场景),per_domain=None 表示全量。"""
    by_dom: dict[str, list[dict]] = collections.defaultdict(list)
    for c in cases:
        by_dom[c["domain"]].append(c)
    out = []
    for dom in sorted(by_dom):
        pool = by_dom[dom]
        if per_domain is None or per_domain >= len(pool):
            out.extend(pool)
        else:
            step = len(pool) / per_domain
            out.extend(pool[int(i * step)] for i in range(per_domain))
    return out


JUDGE_SYSTEM = "你是记忆提取评测的判官。只输出严格 JSON,不要 markdown 代码块、不要解释。"

JUDGE_PROMPT = """对话:
{transcript}

expected(应该提取出的记忆):
{expected}

candidates(LLM 实际提取出的记忆):
{candidates}

任务:
1. 对每条 expected,在 candidates 里找语义等价的一条:核心事实一致即可,
   措辞、详略、额外细节不算差异;dimension 不同一律不算匹配。
2. 对没有被匹配的 candidate,结合对话判断:
   - valid_extra: 对话里确实有依据的合理提取(expected 之外的合理补充)
   - wrong: 错误、编造、无对话依据,或把 assistant 的话当用户事实

输出 JSON:
{{"matches": [<每条 expected 对应的 candidate 下标,无匹配为 -1>],
  "candidate_labels": [{{"index": <未匹配 candidate 下标>, "label": "valid_extra|wrong"}}]}}
matches 数组长度必须等于 expected 条数。"""


async def judge_case(provider, case, cands) -> dict | None:
    """一次调用判全 case:expected→candidate 映射 + 多余 candidate 定性。"""
    if not case["expected"]:
        return None
    from ethan.providers.base import Message
    transcript = "\n".join(
        f"[{m['id']}] {m['role']}: {m['content']}" for m in case["messages"]
    )[:2000]
    expected = [e for e in case["expected"] if not e.get("gap_dimension")]
    exp_text = "\n".join(
        f"{i}. ({e['dimension']}) {e['content']}" for i, e in enumerate(expected)
    )
    cand_text = "\n".join(
        f"{i}. ({c.dimension}) {c.content}" for i, c in enumerate(cands)
    ) or "(空)"
    prompt = JUDGE_PROMPT.format(transcript=transcript, expected=exp_text, candidates=cand_text)
    try:
        resp = await provider.chat(
            [Message(role="user", content=prompt)], tools=None, system=JUDGE_SYSTEM,
        )
        text = (resp.content or "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(text[start:end + 1])
        matches = data.get("matches")
        if not isinstance(matches, list) or len(matches) != len(expected):
            return None
        labels = {int(x["index"]): x.get("label") for x in data.get("candidate_labels", [])
                  if isinstance(x, dict) and str(x.get("index", "")).lstrip("-").isdigit()}
        return {"matches": [int(m) if isinstance(m, (int, float)) or
                            (isinstance(m, str) and m.lstrip("-").isdigit()) else -1
                            for m in matches],
                "labels": labels}
    except Exception:
        return None


async def run_case(extractor, case: dict) -> dict:
    msgs = [
        SourceMessage(session_id=case["id"], message_id=m["id"], role=m["role"],
                      content=m["content"], created_at=float(i))
        for i, m in enumerate(case["messages"])
    ]
    t0 = time.time()
    try:
        cands = await extractor.extract(
            msgs, session_id=case["id"], user_id="eval_user",
            mode=case.get("mode", ""), job_key=f"live-{case['id']}",
        )
        if cands is None:  # LLM 调用失败(瞬时错误)
            cands = []
            error = "llm_call_failed"
        else:
            error = ""
    except Exception as exc:  # provider 错误等
        cands = []
        error = f"{type(exc).__name__}: {exc}"
    latency = time.time() - t0
    return {"case": case, "candidates": cands, "error": error, "latency": latency}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-domain", type=int, default=20, help="每域抽样条数(等距)")
    ap.add_argument("--all", action="store_true", help="全量 1200 条(贵)")
    ap.add_argument("--domains", type=str, default="", help="只跑指定域,逗号分隔")
    ap.add_argument("--tau", type=float, default=0.4, help="content 相似度阈值")
    ap.add_argument("--conc", type=int, default=4, help="并发数")
    ap.add_argument("--model", type=str, default=None, help="覆盖模型(默认=生产同款主模型)")
    ap.add_argument("--no-judge", action="store_true", help="不用 LLM 判官,退回 n-gram 判定")
    args = ap.parse_args()

    cases = []
    for path in sorted(GOLDEN.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(json.loads(line))
    if args.domains:
        keep = set(args.domains.split(","))
        cases = [c for c in cases if c["domain"] in keep]
    cases = sample_cases(cases, None if args.all else args.per_domain)
    print(f"live 评测: {len(cases)} 条 case,tau={args.tau},并发={args.conc}")

    # 与生产一致:_run_structured_extraction 传的是主模型,不是 lite
    if args.model is None:
        from ethan.core.config import get_config
        args.model = get_config().defaults.model
    print(f"模型: {args.model}")

    extractor = StructuredMemoryExtractor(model=args.model)
    sem = asyncio.Semaphore(args.conc)

    # 判官 provider:与提取同一模型,独立于 extractor 内部 provider
    judge_provider = None
    if not args.no_judge:
        from ethan.providers.manager import create_provider
        judge_provider = create_provider(args.model)

    async def guarded(c):
        async with sem:
            r = await run_case(extractor, c)
            if judge_provider is not None and c["expected"]:
                r["verdict"] = await judge_case(judge_provider, c, r["candidates"])
            else:
                r["verdict"] = None
            v = "judge✗" if (judge_provider and c["expected"] and r["verdict"] is None) else ""
            print(f"  [{c['domain'][:12]:<12}] {c['id']}: {len(r['candidates'])} 候选 "
                  f"({r['latency']:.1f}s){v}{' ERROR ' + r['error'] if r['error'] else ''}")
            return r

    results = await asyncio.gather(*(guarded(c) for c in cases))

    # ── 比对 ──
    stats = collections.Counter()
    per_domain = collections.defaultdict(collections.Counter)
    report_cases = []

    for r in results:
        case, cands = r["case"], r["candidates"]
        dom, cid = case["domain"], case["id"]
        user_msgs = {m["id"]: m["content"] for m in case["messages"] if m["role"] == "user"}
        expected = [e for e in case["expected"] if not e.get("gap_dimension")]
        gap_expected = [e for e in case["expected"] if e.get("gap_dimension")]
        gap_dims = {e["dimension"] for e in gap_expected}

        def bump(key, n=1):
            stats[key] += n
            per_domain[dom][key] += n

        if r["error"]:
            bump("provider_error")
        if not cands:
            bump("zero_candidates")

        # quote 合规
        for c in cands:
            src = user_msgs.get(int(c.source_message_id) if str(c.source_message_id).isdigit() else -1, "")
            bump("quote_ok" if c.source_quote in src else "quote_bad")

        # GAP 维度不应出现在输出里(白名单外)
        if any(c.dimension in gap_dims for c in cands):
            bump("gap_leaked")

        # 负样本
        if not case["expected"]:
            if cands:
                bump("false_positive")
            else:
                bump("negative_ok")
            if case["scenario"] == "companion_leak":
                bump("leak_fail" if any(c.dimension.startswith("companion.") for c in cands)
                     else "leak_ok")
            if case["scenario"] == "diagnostic_reject":
                bump("diag_fail" if cands else "diag_ok")  # 应被 extractor 拦截/拒提
            report_cases.append({"id": cid, "domain": dom, "scenario": case["scenario"],
                                 "candidates": len(cands), "error": r["error"]})
            continue

        # 正样本:expected ↔ candidates 按 dimension 匹配 + content 相似度
        tp = fp = fn = 0
        used = set()
        sims = []
        verdict = r.get("verdict")
        if verdict is not None:
            # LLM 判官路径:matches 映射 + valid_extra 不计 FP
            bump("judge_ok")
            matched_cands = set()
            for ei, e in enumerate(expected):
                ci = verdict["matches"][ei] if ei < len(verdict["matches"]) else -1
                if 0 <= ci < len(cands) and cands[ci].dimension == e["dimension"] \
                        and ci not in matched_cands:
                    tp += 1
                    matched_cands.add(ci)
                    sims.append(content_sim(e["content"], cands[ci].content))
                else:
                    fn += 1
            for i in range(len(cands)):
                if i in matched_cands:
                    continue
                label = verdict["labels"].get(i, "wrong")
                if label == "valid_extra":
                    bump("valid_extra")
                else:
                    fp += 1
        else:
            # n-gram 回退路径
            for e in expected:
                best, best_sim = None, 0.0
                for i, c in enumerate(cands):
                    if i in used or c.dimension != e["dimension"]:
                        continue
                    sim = content_sim(e["content"], c.content)
                    if sim > best_sim:
                        best, best_sim = i, sim
                if best is not None and best_sim >= args.tau:
                    tp += 1
                    used.add(best)
                    sims.append(best_sim)
                else:
                    fn += 1
            fp = len(cands) - len(used)
        bump("tp", tp); bump("fp", fp); bump("fn", fn)
        if sims:
            bump("sim_sum", sum(sims)); bump("sim_cnt", len(sims))
        report_cases.append({
            "id": cid, "domain": dom, "scenario": case["scenario"],
            "expected": len(expected), "candidates": len(cands),
            "tp": tp, "fp": fp, "fn": fn,
            "cand_dims": [c.dimension for c in cands],
            "exp_dims": [e["dimension"] for e in expected],
            "cand_contents": [c.content for c in cands],
            "exp_contents": [e["content"] for e in expected],
            "error": r["error"],
        })

    # ── 汇总 ──
    def prf(s):
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        return p, r, f

    print("\n" + "=" * 78)
    print("LIVE 模式评测汇总(真 LLM 提取)")
    print("=" * 78)
    p, r, f = prf(stats)
    print(f"总体: P={p:.2f} R={r:.2f} F1={f:.2f}  (tp={stats['tp']} fp={stats['fp']} fn={stats['fn']}, "
          f"valid_extra={stats['valid_extra']}, judge 成功={stats['judge_ok']})")
    print(f"quote 合规: {stats['quote_ok']}/{stats['quote_ok']+stats['quote_bad']}")
    print(f"零产出: {stats['zero_candidates']}/{len(cases)}  provider 错误: {stats['provider_error']}")
    print(f"GAP 维度泄漏: {stats['gap_leaked']}  负样本误提取: {stats['false_positive']}"
          f"  companion 泄漏: {stats['leak_fail']}  诊断词漏拒: {stats['diag_fail']}")
    if stats["sim_cnt"]:
        print(f"命中对平均相似度: {stats['sim_sum']/stats['sim_cnt']:.2f}")
    print("\n分域 P/R/F1:")
    for dom in sorted(per_domain):
        s = per_domain[dom]
        p, r, f = prf(s)
        print(f"  {dom:<22} P={p:.2f} R={r:.2f} F1={f:.2f}  "
              f"(tp={s['tp']} fp={s['fp']} fn={s['fn']}, 零产出={s['zero_candidates']})")

    REPORT.write_text(json.dumps({
        "args": vars(args), "stats": dict(stats),
        "per_domain": {k: dict(v) for k, v in per_domain.items()},
        "cases": report_cases,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
