# -*- coding: utf-8 -*-
"""排序软降权探针：RANK_DECAY 开/关对召回序的影响，合成库零依赖验证。

验证什么
--------
时间衰减因子乘在 RRF 分数上（recall._collect），这个探针在合成库上验证三条
**必须成立**的性质——任何一条破了就是回归：

1. **新鲜 > 陈旧**（开关开）：同通道命中下，40 天前的 Tier B/C 记忆应排在
   1 天前的新鲜记忆之后。
2. **Tier A 永不被压**（开关开）：40 天前的 preference（Tier A，因子恒
   1.0）不应因年龄被 Tier B/C 新鲜记忆以外的原因压到其后——即衰减不改变
   Tier A 的相对竞争力。
3. **开关关 = 旧序逐位一致**：RANK_DECAY_ENABLED=False 时，_collect 的
   输出序必须等于旧实现排序键 (-RRF, -importance, -confidence) 的序。
   这是"默认关等于改造前"的硬合同。

不验证什么（负向声明）
--------------------
不量 precision/recall——那是 eval_runner_recall.py 对 golden 数据的职责。
本探针只锁排序性质，合成库无真值概念。

用法
----
  uv run python tests/memory_eval/probe_rank_decay.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import ethan.memory.decay as decay_mod  # noqa: E402
from ethan.core.context import ETHAN_USER_ID  # noqa: E402
from ethan.memory.recall import _collect  # noqa: E402
from ethan.memory.records import MemoryEvidence, MemoryRecord  # noqa: E402
from ethan.memory.store import MemoryStore  # noqa: E402

DAY = 86400.0
QUERY = "因子动量方案"


def _record(content, *, dimension, memory_type, key, updated, importance, tentative=False):
    structured = {"tentative": True} if tentative else {}
    return MemoryRecord(
        memory_type=memory_type,
        dimension=dimension,
        memory_key=key,
        content=content,
        scope_type="project",
        scope_id="proj_probe",
        memory_domain="general",
        status="active",
        evidence_level="explicit",
        confidence=0.9,
        importance=importance,
        structured_data=structured,
        updated_at=updated,
        created_at=updated,
    )


def build_library(now: float) -> list[MemoryRecord]:
    return [
        # 陈旧 Tier C（tentative 决定，40 天，高 importance——旧序下本应第一）
        _record("先试试因子动量方案A", dimension="decision.chosen", memory_type="decision",
                key="k_c", updated=now - 40 * DAY, importance=0.99, tentative=True),
        # 新鲜 Tier B（普通决定，1 天）
        _record("定稿因子动量方案B口径", dimension="decision.chosen", memory_type="decision",
                key="k_b", updated=now - 1 * DAY, importance=0.6),
        # 陈旧 Tier A（偏好，40 天，因子恒 1.0）
        _record("因子报告要带公式讲解", dimension="preference.content", memory_type="preference",
                key="k_a", updated=now - 40 * DAY, importance=0.8),
    ]


def run(now: float) -> int:
    token = ETHAN_USER_ID.set("")
    tmp = tempfile.mkdtemp()
    failures = 0
    try:
        with patch("ethan.core.paths.CONFIG_DIR", Path(tmp)):
            store = MemoryStore(Path(tmp) / "memory.db")
            records = build_library(now)
            for rec in records:
                store.create_memory_with_evidence(rec, [MemoryEvidence(
                    memory_id=rec.id, evidence_level="explicit",
                    source_session_id="s1", source_message_id="m1",
                    source_role="user", source_quote=rec.content, created_at=rec.updated_at,
                )])
            with patch("ethan.memory.memory_vectors.recall_neighbors", lambda **kw: []):
                decay_mod.RANK_DECAY_ENABLED = False
                order_off = [m.memory_key for m in _collect(store, QUERY, domain="general", max_items=10)]
                decay_mod.RANK_DECAY_ENABLED = True
                order_on = [m.memory_key for m in _collect(store, QUERY, domain="general", max_items=10)]
                # 独立复算旧实现的排序键（单 FTS 通道、无衰减因子）：
                # (-RRF, -importance, -confidence)。与关开关的 _collect 输出逐位对比，
                # 才是"关 = 旧序"的等价性校验——而不是臆断 bm25 会偏爱哪条。
                fts_hits = store.search_memories(
                    QUERY, memory_domain="general", statuses=["active"], limit=10
                )
                old_scores = {m.id: 1.0 / (61 + rank) for rank, m in enumerate(fts_hits)}
                old_order = [
                    m.memory_key
                    for m in sorted(
                        fts_hits,
                        key=lambda m: (-old_scores[m.id], -m.importance, -m.confidence),
                    )
                ]
            store.close()

        print(f"RANK_DECAY=off: {order_off}")
        print(f"RANK_DECAY=on : {order_on}")

        # 性质 3：关 = 旧序（与复算的旧实现排序键逐位一致）
        if order_off == old_order:
            print("  [ok] 性质3: RANK_DECAY=0 序 = 旧排序键序（逐位一致）")
        else:
            print(f"  [FAIL] 性质3 关开关应等于旧序: got={order_off} want={old_order}")
            failures += 1

        # 性质 1：新鲜 Tier B 压过陈旧 Tier C
        if order_on.index("k_b") < order_on.index("k_c"):
            print("  [ok] 性质1: 新鲜 Tier B 排在陈旧 Tier C 之前")
        else:
            print(f"  [FAIL] 性质1 陈旧 tentative 应被压底: {order_on}")
            failures += 1

        # 性质 2：Tier A 不因 40 天年龄沉底——仍应在 Tier C 之上
        if order_on.index("k_a") < order_on.index("k_c"):
            print("  [ok] 性质2: 陈旧 Tier A（因子 1.0）未被年龄压制")
        else:
            print(f"  [FAIL] 性质2 Tier A 被压到 Tier C 之下: {order_on}")
            failures += 1

        return failures
    finally:
        ETHAN_USER_ID.reset(token)


if __name__ == "__main__":
    failures = run(time.time())
    print(f"\n{'PASS' if failures == 0 else f'{failures} FAILURES'}: rank decay ordering probe")
    sys.exit(1 if failures else 0)
