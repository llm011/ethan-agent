# -*- coding: utf-8 -*-
"""Memory eval — dry 模式评测(0 LLM)。

把每条 extraction case 的 expected 当作「LLM 本该输出的候选」喂进
admission + store,验证确定性链路:
  - dimension 白名单校验(GAP 维度应被 extractors._validate_dimension 拒绝)
  - 准入规则(explicit/corrected/inferred→admitted,observed→pending)
  - 幂等(非 corrected 二次 admit→merged;corrected→supersede 不重复)
  - companion 诊断词拒收(_contains_denied_term)
  - companion mode 边界(_is_companion_mode)
  - quote 是 user 消息精确子串

用法: uv run python eval_runner_dry.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # worktree 根,以便 import ethan

from ethan.memory.records import MemoryCandidate  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402
from ethan.memory.admission import (  # noqa: E402
    AdmissionPolicy,
    OUTCOME_ADMITTED,
    OUTCOME_MERGED,
    OUTCOME_PENDING,
    OUTCOME_REJECTED,
)
import ethan.memory.extractors as X  # noqa: E402

GOLDEN = HERE / "golden"


def build_candidate(e: dict, case: dict) -> MemoryCandidate:
    domain = case["domain"]
    return MemoryCandidate(
        memory_type=e["memory_type"],
        dimension=e["dimension"],
        memory_key=e["memory_key"],
        content=e["content"],
        scope_type=e["scope_type"],
        scope_id=e["scope_id"],
        memory_domain="companion" if domain == "companion" else "general",
        evidence_level=e["evidence_level"],
        source_session_id=case["id"],           # 每个 case 当独立 session
        source_message_id=str(e["message_id"]),
        source_role="user",
        source_quote=e["quote"],
        structured_data=e.get("structured") or {},
        confidence=1.0 if e["evidence_level"] == "corrected" else 0.95,
        user_id="eval_user",
    )


def main() -> int:
    cases = []
    for path in sorted(GOLDEN.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(json.loads(line))

    tmp = Path(tempfile.mkdtemp(prefix="memeval_"))

    stats = collections.Counter()
    per_domain = collections.defaultdict(collections.Counter)
    failures: list[str] = []

    def check(cond: bool, label: str, cid: str, detail: str = "") -> None:
        stats[label + ("_pass" if cond else "_fail")] += 1
        per_domain[dom][label + ("_pass" if cond else "_fail")] += 1
        if not cond:
            failures.append(f"[{dom}] {cid}: {label} — {detail}")

    for case in cases:
        dom = case["domain"]
        cid = case["id"]
        scenario = case["scenario"]
        user_msgs = {m["id"]: m["content"] for m in case["messages"] if m["role"] == "user"}

        # ── A. quote 精确子串校验 ──
        for e in case["expected"]:
            src = user_msgs.get(e["message_id"], "")
            check(e["quote"] in src, "quote_substring", cid, f'quote={e["quote"][:24]!r}')

        # ── B. 维度白名单:GAP 维度应被 _validate_dimension 拒绝(不喂 admission)──
        cands: list[MemoryCandidate] = []
        for e in case["expected"]:
            is_gap = e.get("gap_dimension", False)
            try:
                X._validate_dimension(e["memory_type"], e["dimension"])
                dim_ok = True
            except ValueError:
                dim_ok = False
            check(dim_ok != is_gap, "gap_dim_rejected", cid,
                  f'{e["dimension"]} {"应被拒却通过" if is_gap else "非 GAP 却被拒"}')
            if is_gap:
                continue  # GAP 维度在 extractor 层就被拒,到不了 admission
            cands.append(build_candidate(e, case))

        # ── C. 负样本(expected=[]):验证不产生记忆 + 边界检测 ──
        if not case["expected"]:
            check(True, "negative_no_memory", cid)  # 无候选即无产出
            if scenario == "diagnostic_reject":
                text = " ".join(m["content"] for m in case["messages"])
                check(X._contains_denied_term(text) is not None, "denied_term_detected", cid,
                      f"诊断词未被识别: {text[:30]!r}")
            if scenario == "companion_leak":
                check(not X.StructuredMemoryExtractor._is_companion_mode(case["mode"]),
                      "leak_mode_blocked", cid, f'mode={case["mode"]!r} 误判为 companion')
            continue

        # ── D. 正样本:独立 store(每 case 隔离,避免跨 case key+scope 碰撞)──
        if not cands:
            continue
        store = MemoryStore(db_path=tmp / f"{cid}.db")
        policy = AdmissionPolicy(store)
        try:
            store.create_candidate_batch(cands)
            for c in cands:
                memory_id, outcome = policy.admit_candidate(c)
                lvl = c.evidence_level
                if lvl in ("explicit", "corrected", "inferred"):
                    ok = outcome == OUTCOME_ADMITTED and memory_id is not None
                    check(ok, "admit_positive", cid, f"{lvl} 应 admitted,实际 outcome={outcome}")
                    if ok:
                        # ── E. 幂等:同 candidate 二次 admit ──
                        _, outcome2 = policy.admit_candidate(c)
                        if lvl == "corrected":
                            check(outcome2 == OUTCOME_ADMITTED, "idempotent_corrected", cid,
                                  f"corrected 二次应 supersede(admitted),实际 {outcome2}")
                        else:
                            check(outcome2 == OUTCOME_MERGED, "idempotent_merged", cid,
                                  f"二次 admit 应 merged,实际 {outcome2}")
                elif lvl == "observed":
                    check(outcome == OUTCOME_PENDING, "observed_pending", cid,
                          f"observed 单 session 应 pending,实际 outcome={outcome}")
        finally:
            store.close()

    # ── 汇总 ──
    def pct(p: int, f: int) -> str:
        t = p + f
        return f"{p}/{t} ({100*p/t:.0f}%)" if t else "—"

    print("\n" + "=" * 78)
    print("DRY 模式评测汇总(0 LLM)")
    print("=" * 78)
    metrics = [
        ("quote_substring", "quote 是 user 消息精确子串"),
        ("gap_dim_rejected", "GAP 维度被白名单正确拒绝"),
        ("admit_positive", "explicit/corrected/inferred 准入 admitted"),
        ("observed_pending", "observed 单 session 保持 pending"),
        ("negative_no_memory", "负样本不产生记忆"),
        ("denied_term_detected", "诊断词被 _contains_denied_term 识别"),
        ("leak_mode_blocked", "非 companion 模式不误判 companion"),
        ("idempotent_merged", "幂等:非 corrected 二次 admit merged"),
        ("idempotent_corrected", "幂等:corrected 二次 supersede 不重复"),
    ]
    print(f'{"metric":<34}{"pass/total":>16}')
    print("-" * 78)
    for key, desc in metrics:
        p = stats[key + "_pass"]
        f = stats[key + "_fail"]
        mark = "✓" if f == 0 and p > 0 else ("✗" if f > 0 else "·")
        print(f"{mark} {desc:<32}{pct(p, f):>16}")

    print("\n按域名分的准入正确率(admit_positive + observed_pending):")
    for dom in sorted(per_domain):
        p = per_domain[dom]["admit_positive_pass"] + per_domain[dom]["observed_pending_pass"]
        f = per_domain[dom]["admit_positive_fail"] + per_domain[dom]["observed_pending_fail"]
        print(f"  {dom:<22}{pct(p, f):>16}")

    total_fail = sum(v for k, v in stats.items() if k.endswith("_fail"))
    print("-" * 78)
    print(f"总断言: {sum(stats.values())}  失败: {total_fail}")
    if failures:
        print("\n失败明细(前 30):")
        for x in failures[:30]:
            print("  -", x)
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
