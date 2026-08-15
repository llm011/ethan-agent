"""记忆衰减/遗忘 + 强化晋升（ethan.memory.decay）的单元测试。

时间全部用显式 now/时间戳注入（不依赖真实时钟）；衰减开关通过 monkeypatch
模块属性切换（模块在 import 时读 env，直接改属性与改 env+reload 等价且不
污染其他测试）。
"""
from __future__ import annotations

import sqlite3
import time as _time
from dataclasses import replace

import pytest

from ethan.memory.decay import (
    TIER_A,
    TIER_B,
    TIER_C,
    _parse_ladder,
    apply_confidence_promotion,
    apply_memory_decay,
    ladder_target,
    memory_tier,
    rank_decay_factor,
    wake_scope_dormant,
)
from ethan.memory.recall import _collect
from ethan.memory.records import MemoryEvidence, MemoryRecord, MemoryStatus
from ethan.memory.store import MemoryStore

NOW = 1_800_000_000.0
DAY = 86400.0


def make_record(
    *,
    content: str = "测试记忆",
    memory_type: str = "decision",
    dimension: str = "decision.chosen",
    memory_key: str | None = None,
    scope_type: str = "project",
    scope_id: str = "proj_a",
    domain: str = "general",
    status: str = "active",
    confidence: float = 0.9,
    importance: float = 0.8,
    tentative: bool = False,
    updated_at: float = NOW,
    created_at: float = NOW,
) -> MemoryRecord:
    structured: dict = {}
    if tentative:
        structured["tentative"] = True
    if memory_type == "companion":
        domain = "companion"
    return MemoryRecord(
        memory_type=memory_type,
        dimension=dimension,
        memory_key=memory_key or f"{dimension}:{content[:12]}",
        content=content,
        scope_type=scope_type,
        scope_id=scope_id,
        memory_domain=domain,
        status=status,
        evidence_level="explicit",
        confidence=confidence,
        importance=importance,
        structured_data=structured,
        updated_at=updated_at,
        created_at=created_at,
    )


def add_memory(
    store: MemoryStore,
    record: MemoryRecord,
    *,
    sessions: tuple[str, ...] = ("s1",),
    evidence_at: float | None = None,
) -> str:
    """写入一条 active 记忆 + 每个 session 一条 evidence。

    evidence_at 显式控制 evidence.created_at（模拟存量数据），不传则用当前时刻。
    """
    evidence = [
        MemoryEvidence(
            memory_id=record.id,
            evidence_level=record.evidence_level,
            source_session_id=session,
            source_message_id=f"{session}-m1",
            source_role="user",
            source_quote=record.content,
            created_at=evidence_at if evidence_at is not None else record.updated_at,
        )
        for session in sessions
    ]
    store.create_memory_with_evidence(record, evidence)
    return record.id


@pytest.fixture
def decay_on(monkeypatch):
    monkeypatch.setattr("ethan.memory.decay.DECAY_ENABLED", True)
    monkeypatch.setattr("ethan.memory.decay.DECAY_DRY_RUN", False)


@pytest.fixture
def hash_embed():
    """强制 hash embedding（离线、确定性），与 test_structured_memory 同一手法。"""
    import ethan.memory.embeddings as emb

    old_checked, old_encoder = emb._encoder_checked, emb._encoder
    emb._encoder = None
    emb._encoder_checked = True
    yield
    emb._encoder_checked, emb._encoder = old_checked, old_encoder


# ── Tier 判定 ───────────────────────────────────────────────────────────────


def test_tier_a_exemptions():
    # user 系 scope 全豁免
    for scope_type in ("user", "user_domain", "user_skill"):
        assert memory_tier(make_record(scope_type=scope_type)) == TIER_A
    # 任何 scope 下豁免维度
    assert memory_tier(make_record(memory_type="personal_information", dimension="identity.name")) == TIER_A
    assert memory_tier(make_record(memory_type="preference", dimension="preference.content")) == TIER_A
    assert memory_tier(make_record(memory_type="relationship", dimension="relationship.agreement")) == TIER_A
    # companion 域整体豁免（哪怕 project scope 形状）
    assert memory_tier(make_record(memory_type="companion", dimension="companion.emotional_event", scope_type="mode", scope_id="companion")) == TIER_A


def test_tier_c_tentative_only_decision_activity():
    assert memory_tier(make_record(tentative=True)) == TIER_C
    assert memory_tier(make_record(memory_type="activity", dimension="activity.focus", tentative=True)) == TIER_C
    # 非 decision/activity 上的 tentative 标记无效 → B
    assert memory_tier(make_record(memory_type="methodology", dimension="methodology.approach", tentative=True)) == TIER_B
    # A 压 C：user scope 下的临时决定不归档不衰减
    assert memory_tier(make_record(scope_type="user", tentative=True)) == TIER_A


def test_old_records_without_tentative_default_b():
    assert memory_tier(make_record()) == TIER_B


# ── rank_decay_factor ───────────────────────────────────────────────────────


def test_rank_decay_factor_monotonic():
    record = make_record(updated_at=NOW)
    factors = [rank_decay_factor(record, NOW + d * DAY) for d in (0, 1, 5, 30, 90)]
    assert all(a > b for a, b in zip(factors, factors[1:])), factors
    # Tier B 半衰期 30 天：30 天处应接近 0.5
    assert factors[3] == pytest.approx(0.5, abs=0.01)
    # Tier C 半衰期 3 天
    c = make_record(tentative=True, updated_at=NOW)
    assert rank_decay_factor(c, NOW + 3 * DAY) == pytest.approx(0.5, abs=0.01)


def test_rank_decay_factor_tier_a_and_disabled(monkeypatch):
    record = make_record(memory_type="preference", dimension="preference.content", updated_at=NOW)
    assert rank_decay_factor(record, NOW + 365 * DAY) == 1.0
    monkeypatch.setattr("ethan.memory.decay.RANK_DECAY_ENABLED", False)
    stale = make_record(tentative=True, updated_at=NOW - 90 * DAY)
    assert rank_decay_factor(stale, NOW) == 1.0


def test_rank_decay_factor_recall_anchor_resets():
    """旧 updated_at 但最近被召回过 → 衰减计时被 last_recalled_at 重置。"""
    stale_but_recalled = replace(
        make_record(updated_at=NOW - 90 * DAY), last_recalled_at=NOW - 1 * DAY
    )
    assert rank_decay_factor(stale_but_recalled, NOW) == pytest.approx(0.5 ** (1 / 30), abs=0.01)
    never_recalled = make_record(updated_at=NOW - 90 * DAY)
    assert rank_decay_factor(never_recalled, NOW) < 0.2


# ── 召回排序降权 ────────────────────────────────────────────────────────────


def test_collect_rank_decay_reorders_stale_tentative(tmp_path, hash_embed, monkeypatch):
    """RRF 分数相近时：陈旧 tentative 决定应被压到新鲜决定之后；关闭开关恢复旧序。

    注意 _collect 内部取真实 time.time()，所以这里的时间基准也用真实时钟。
    """
    monkeypatch.setattr("ethan.memory.memory_vectors.recall_neighbors", lambda **kw: [])
    real_now = _time.time()
    store = MemoryStore(tmp_path / "memory.db")
    stale = make_record(
        content="先试试因子动量方案A", tentative=True, importance=0.99,
        updated_at=real_now - 40 * DAY, created_at=real_now - 40 * DAY,
    )
    fresh = make_record(
        content="定稿因子动量方案B口径", memory_key="decision.chosen:fresh",
        importance=0.5, updated_at=real_now - 1 * DAY, created_at=real_now - 1 * DAY,
    )
    add_memory(store, stale, evidence_at=real_now - 40 * DAY)
    add_memory(store, fresh, evidence_at=real_now - 1 * DAY)

    def top_id() -> str:
        hits = _collect(store, "因子动量方案", domain="general", max_items=4, intent="unknown")
        assert hits, "FTS 通道应命中两条"
        return hits[0].id

    # 开关关：因子恒 1.0，排序退回 (-RRF, -importance, -confidence)——
    # stale 在 FTS 序里靠前且 importance 更高，应排第一（与旧实现逐位一致）
    monkeypatch.setattr("ethan.memory.decay.RANK_DECAY_ENABLED", False)
    assert top_id() == stale.id
    # 开关开：stale Tier C 因子 0.5^(40/3)，被 fresh 压过
    monkeypatch.setattr("ethan.memory.decay.RANK_DECAY_ENABLED", True)
    assert top_id() == fresh.id
    store.close()


def test_collect_fallback_applies_decay(tmp_path, hash_embed, monkeypatch):
    """兜底路径：开降权按 importance×factor 排（修正历史 updated_at DESC 行为），
    关降权保持 updated_at DESC 原序。"""
    monkeypatch.setattr("ethan.memory.memory_vectors.recall_neighbors", lambda **kw: [])
    real_now = _time.time()
    store = MemoryStore(tmp_path / "memory.db")
    low_imp_recent = make_record(
        content="无关甲", memory_key="decision.chosen:a", importance=0.2,
        updated_at=real_now - 1 * DAY,
    )
    high_imp_tier_a = make_record(
        content="无关乙", memory_key="preference.content:b",
        memory_type="preference", dimension="preference.content", importance=0.9,
        updated_at=real_now - 2 * DAY,
    )
    add_memory(store, low_imp_recent, evidence_at=real_now - 1 * DAY)
    add_memory(store, high_imp_tier_a, evidence_at=real_now - 2 * DAY)

    def order() -> list[str]:
        hits = _collect(store, "完全不会命中的查询xyzq", domain="general", max_items=4)
        return [h.id for h in hits]

    monkeypatch.setattr("ethan.memory.decay.RANK_DECAY_ENABLED", False)
    assert order() == [low_imp_recent.id, high_imp_tier_a.id]  # updated_at DESC 原序
    monkeypatch.setattr("ethan.memory.decay.RANK_DECAY_ENABLED", True)
    assert order() == [high_imp_tier_a.id, low_imp_recent.id]  # 0.9×1.0 > 0.2×~0.98
    store.close()


# ── 休眠检测与归档 ──────────────────────────────────────────────────────────


def test_project_scope_dormant_after_idle(tmp_path, decay_on):
    store = MemoryStore(tmp_path / "memory.db")
    old = NOW - 22 * DAY
    decision = make_record(content="路线B", updated_at=old, created_at=old)
    pref = make_record(
        content="PPT 要给公式讲解", memory_type="preference",
        dimension="preference.content", memory_key="preference.content:ppt",
        updated_at=old, created_at=old,
    )
    add_memory(store, decision, evidence_at=old)
    add_memory(store, pref, evidence_at=old)

    result = apply_memory_decay(store, NOW)

    assert result["dormanted"] == 1  # 只归档非 Tier A
    got = store.get_memory(decision.id)
    assert got.status == MemoryStatus.DORMANT.value and got.dormant_at is not None
    kept = store.get_memory(pref.id)
    assert kept.status == MemoryStatus.ACTIVE.value  # Tier A 维度留在原地
    # dormant 不再进 FTS 召回
    assert store.search_memories("路线", statuses=["active"]) == []
    store.close()


def test_scope_recent_recall_blocks_dormancy(tmp_path, decay_on):
    store = MemoryStore(tmp_path / "memory.db")
    old = NOW - 22 * DAY
    decision = make_record(content="路线B", updated_at=old, created_at=old)
    add_memory(store, decision, evidence_at=old)
    # 昨天被召回过 → scope 仍活跃
    conn = store._get_conn()
    conn.execute(
        "UPDATE memories SET last_recalled_at=? WHERE id=?",
        (NOW - 1 * DAY, decision.id),
    )
    conn.commit()

    result = apply_memory_decay(store, NOW)
    assert result["dormanted"] == 0
    assert store.get_memory(decision.id).status == MemoryStatus.ACTIVE.value
    store.close()


def test_evidence_activity_blocks_dormancy(tmp_path, decay_on):
    """存量数据兜底：updated_at 很旧但 evidence 是新的（历史 add_evidence 不 bump）→ 不休眠。"""
    store = MemoryStore(tmp_path / "memory.db")
    old = NOW - 22 * DAY
    decision = make_record(content="路线B", updated_at=old, created_at=old)
    add_memory(store, decision, sessions=("s1",), evidence_at=old)
    # 直接补一条 created_at=昨天 的 evidence 行（绕过 add_evidence 的 bump）
    recent_ev = MemoryEvidence(
        memory_id=decision.id, evidence_level="explicit",
        source_session_id="s2", source_message_id="m2",
        source_role="user", source_quote="还是路线B", created_at=NOW - 1 * DAY,
    )
    with store.transaction() as conn:
        store._insert_evidence(conn, recent_ev)

    result = apply_memory_decay(store, NOW)
    assert result["dormanted"] == 0
    store.close()


def test_tentative_grace_boundary(tmp_path, decay_on):
    store = MemoryStore(tmp_path / "memory.db")
    t13 = NOW - 13 * DAY
    t15 = NOW - 15 * DAY
    keep = make_record(content="先试试方案甲", memory_key="decision.chosen:keep", tentative=True, updated_at=t13, created_at=t13)
    drop = make_record(content="先试试方案乙", memory_key="decision.chosen:drop", tentative=True, updated_at=t15, created_at=t15)
    add_memory(store, keep, evidence_at=t13)
    add_memory(store, drop, evidence_at=t15)

    result = apply_memory_decay(store, NOW)
    assert result["decayed"] == 1
    assert store.get_memory(keep.id).status == MemoryStatus.ACTIVE.value
    assert store.get_memory(drop.id).status == MemoryStatus.DORMANT.value
    store.close()


def test_long_dormant_forgotten(tmp_path, decay_on):
    store = MemoryStore(tmp_path / "memory.db")
    decision = make_record(content="路线B")
    add_memory(store, decision)
    store.bulk_set_dormant([decision.id])
    conn = store._get_conn()
    conn.execute(
        "UPDATE memories SET dormant_at=? WHERE id=?",
        (NOW - 181 * DAY, decision.id),
    )
    conn.commit()

    result = apply_memory_decay(store, NOW)
    assert result["forgotten"] == 1
    got = store.get_memory(decision.id)
    assert got.status == MemoryStatus.FORGOTTEN.value
    assert got.content == "[forgotten]"
    store.close()


def test_dry_run_mutates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("ethan.memory.decay.DECAY_ENABLED", True)
    monkeypatch.setattr("ethan.memory.decay.DECAY_DRY_RUN", True)
    store = MemoryStore(tmp_path / "memory.db")
    old = NOW - 22 * DAY
    decision = make_record(content="路线B", updated_at=old, created_at=old, confidence=0.6)
    add_memory(store, decision, sessions=("s1", "s2", "s3", "s4", "s5"), evidence_at=old)

    result = apply_memory_decay(store, NOW)

    # 计数真实（会休眠 1 条 + 晋升 1 条）……
    assert result["dormanted"] == 1
    assert result["promoted"] == 1
    # ……但状态与置信度零变更
    got = store.get_memory(decision.id)
    assert got.status == MemoryStatus.ACTIVE.value
    assert got.confidence == 0.6
    store.close()


# ── 唤醒 ────────────────────────────────────────────────────────────────────


def test_wake_scope_dormant_roundtrip(tmp_path, hash_embed):
    store = MemoryStore(tmp_path / "memory.db")
    decision = make_record(content="路线B")
    add_memory(store, decision)
    store.bulk_set_dormant([decision.id])
    assert store.get_memory(decision.id).status == MemoryStatus.DORMANT.value

    woken = wake_scope_dormant(store, "project", "proj_a")
    assert woken == 1
    got = store.get_memory(decision.id)
    assert got.status == MemoryStatus.ACTIVE.value and got.dormant_at is None
    assert store.search_memories("路线", statuses=["active"])  # FTS 恢复
    store.close()


def test_wake_requires_dormant(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    decision = make_record(content="路线B")
    add_memory(store, decision)
    # active 记忆不会被重复"唤醒"
    assert store.wake_memories([decision.id]) == 0
    store.close()


# ── 强化晋升 ────────────────────────────────────────────────────────────────


def test_parse_ladder_and_target():
    ladder = _parse_ladder("2:0.8,3:0.9,5:0.95")
    assert ladder == [(2, 0.8), (3, 0.9), (5, 0.95)]
    assert ladder_target(1, ladder) is None
    assert ladder_target(2, ladder) == 0.8
    assert ladder_target(3, ladder) == 0.9
    assert ladder_target(5, ladder) == 0.95
    assert ladder_target(9, ladder) == 0.95
    # 非法条目静默跳过
    assert _parse_ladder("x:y,2:0.8,0:1.5") == [(2, 0.8)]


def test_promotion_by_distinct_sessions(tmp_path):
    """多次独立 session 证据 → 置信度阶梯晋升（60% 卡死 case 的自愈路径）。"""
    store = MemoryStore(tmp_path / "memory.db")
    pref = make_record(
        content="精读论文做成PPT", memory_type="preference",
        dimension="preference.content", scope_type="user", scope_id="self",
        confidence=0.6,
    )
    corrected = make_record(
        content="定稿验收标准", memory_key="decision.chosen:std",
        confidence=1.0, updated_at=NOW - 10 * DAY, created_at=NOW - 10 * DAY,
    )
    add_memory(store, pref, sessions=("s1", "s2", "s3", "s4", "s5"))
    add_memory(store, corrected, sessions=("s1", "s2", "s3", "s4", "s5"))

    promoted = apply_confidence_promotion(store, NOW)

    assert promoted == 1  # 0.6 → 0.95 晋升；1.0 已封顶不动
    assert store.get_memory(pref.id).confidence == 0.95
    assert store.get_memory(corrected.id).confidence == 1.0
    store.close()


def test_promotion_does_not_touch_updated_at(tmp_path):
    """关键回归：晋升刷新 updated_at 会让 scope 休眠计时永久归零。"""
    store = MemoryStore(tmp_path / "memory.db")
    old = NOW - 22 * DAY
    decision = make_record(content="路线B", updated_at=old, created_at=old, confidence=0.6)
    add_memory(store, decision, sessions=("s1", "s2", "s3"), evidence_at=old)
    before = store.get_memory(decision.id).updated_at

    apply_confidence_promotion(store, NOW)

    after = store.get_memory(decision.id)
    assert after.updated_at == before
    assert after.confidence == 0.9
    store.close()


def test_promotion_companion_exempt(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    comp = make_record(
        content="用户被倾听后情绪缓解", memory_type="companion",
        dimension="companion.emotional_event", scope_type="mode", scope_id="companion",
        confidence=0.6,
    )
    add_memory(store, comp, sessions=("s1", "s2", "s3", "s4", "s5"))

    assert apply_confidence_promotion(store, NOW) == 0
    assert store.get_memory(comp.id).confidence == 0.6
    store.close()


# ── 迁移 ────────────────────────────────────────────────────────────────────


def test_v3_db_upgrades_to_v4(tmp_path):
    db = tmp_path / "old_v3.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE structured_memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL DEFAULT '', memory_type TEXT NOT NULL,
            dimension TEXT NOT NULL, memory_key TEXT NOT NULL, content TEXT NOT NULL,
            structured_data TEXT NOT NULL DEFAULT '{}', scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
            memory_domain TEXT NOT NULL DEFAULT 'general', memory_role TEXT NOT NULL DEFAULT 'task_context',
            status TEXT NOT NULL, evidence_level TEXT NOT NULL, confidence REAL NOT NULL,
            importance REAL NOT NULL, sensitivity TEXT NOT NULL DEFAULT 'normal',
            valid_from REAL, valid_until REAL, source_session_id TEXT, source_message_id TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, last_recalled_at REAL,
            superseded_by TEXT, forgotten_at REAL);
        INSERT INTO memories VALUES ('m1','','decision','decision.chosen','k1','旧记忆','{}',
            'project','ppt','general','decision','active','explicit',0.9,0.5,'normal',
            NULL,NULL,'s','m',1.0,1.0,NULL,NULL,NULL);
    """)
    conn.commit()
    conn.close()

    store = MemoryStore(db)
    cols = {
        row[1] for row in store._get_conn().execute("PRAGMA table_info(memories)")
    }
    assert "dormant_at" in cols
    old = store.get_memory("m1")
    assert old is not None and old.content == "旧记忆" and old.dormant_at is None
    assert store.get_meta("schema_version") == "4"
    store.close()


def test_apply_memory_decay_disabled_by_default(monkeypatch, tmp_path):
    """DECAY_ENABLED 默认关：不读库零归档，但晋升独立生效。"""
    monkeypatch.setattr("ethan.memory.decay.DECAY_ENABLED", False)
    store = MemoryStore(tmp_path / "memory.db")
    old = NOW - 22 * DAY
    decision = make_record(content="路线B", updated_at=old, created_at=old)
    add_memory(store, decision, evidence_at=old)

    result = apply_memory_decay(store, NOW)
    assert result["dormanted"] == 0
    assert store.get_memory(decision.id).status == MemoryStatus.ACTIVE.value
    store.close()


# ── 阶段3：提取器 tentative 标记 ────────────────────────────────────────────


def _build_one(item: dict, *, content: str = "先试试因子动量方案A", quote: str | None = None):
    from ethan.memory.extractors import SourceMessage, StructuredMemoryExtractor

    source = SourceMessage(session_id="s1", message_id=1, role="user", content=content)
    return StructuredMemoryExtractor()._build_one(
        {**item, "quote": quote if quote is not None else content},
        by_id={"1": source}, session_id="s1", user_id="", job_key="", is_companion=False,
    )


def _decision_item(**overrides) -> dict:
    item = {
        "memory_type": "decision", "dimension": "decision.chosen",
        "memory_key": "decision.chosen:plan", "content": "先试试因子动量方案A",
        "evidence_level": "explicit", "scope_type": "project", "scope_id": "proj_a",
        "message_id": "1", "confidence": 0.9, "importance": 0.7, "structured": {},
    }
    item.update(overrides)
    return item


def test_extractor_tentative_true_marks_decision():
    cand = _build_one(_decision_item(tentative=True))
    assert cand.structured_data.get("tentative") is True
    assert memory_tier(cand) == TIER_C


def test_extractor_tentative_string_forms_accepted():
    for raw in ("true", "1", "yes", "True"):
        cand = _build_one(_decision_item(tentative=raw))
        assert cand.structured_data.get("tentative") is True, raw


def test_extractor_tentative_dropped_for_non_tentative_types():
    # preference 没有"临时"语义：即使模型标了也静默丢弃
    pref = _build_one(_decision_item(
        memory_type="preference", dimension="preference.content", tentative=True,
    ))
    assert "tentative" not in pref.structured_data
    assert memory_tier(pref) == TIER_A
    # false/缺省 → 不标
    for raw in (False, None, "false", ""):
        assert "tentative" not in _build_one(_decision_item(tentative=raw)).structured_data


# ── 阶段3：跨 scope 偏好配对 ────────────────────────────────────────────────


def _pref_candidate(
    *, content: str = "精读的论文要做成PPT", scope_type: str = "project",
    scope_id: str = "proj_ppt", level: str = "explicit",
    dimension: str = "preference.content", structured: dict | None = None,
    session: str = "s2",
):
    from ethan.memory.records import MemoryCandidate

    return MemoryCandidate(
        memory_type="preference", dimension=dimension,
        memory_key=f"{dimension}:{content[:8]}", content=content,
        scope_type=scope_type, scope_id=scope_id, memory_domain="general",
        evidence_level=level, source_session_id=session, source_message_id="9",
        source_role="user", source_quote=content,
        confidence=0.9, importance=0.8,
        structured_data=structured or {},
    )


def _seed_user_preference(store: MemoryStore, content: str = "精读的论文要做成PPT") -> str:
    """user scope 既有偏好，走完整准入（顺带建好向量索引）。"""
    from ethan.memory.admission import run_incremental_admission
    from ethan.memory.records import MemoryCandidate

    seed = MemoryCandidate(
        memory_type="preference", dimension="preference.content",
        memory_key="preference.content:ppt", content=content,
        scope_type="user", scope_id="self", memory_domain="general",
        evidence_level="explicit", source_session_id="s0", source_message_id="1",
        source_role="user", source_quote=content, confidence=0.9, importance=0.8,
    )
    store.create_candidate_batch([seed])
    result = run_incremental_admission(store, [seed])
    assert len(result.admitted) == 1
    return result.admitted[0]


def test_cross_scope_preference_reinforces_user_memory(tmp_path, hash_embed, monkeypatch):
    """project 偏好候选配到 user 级既有偏好 → 只补证据，不新建 project 副本。"""
    from ethan.memory.admission import run_incremental_admission

    store = MemoryStore(tmp_path / "memory.db")
    user_mem_id = _seed_user_preference(store)

    cand = _pref_candidate()  # 同文同维度，project scope
    store.create_candidate_batch([cand])
    result = run_incremental_admission(store, [cand])

    assert result.merged == [user_mem_id], "应跨 scope 合并进 user 级偏好"
    assert len(store.list_memories(status="active")) == 1  # 无 project 副本
    reason = store.get_candidate(cand.id).processing_reason
    assert reason.startswith("cross_scope_reinforced:"), reason
    assert len(store.list_evidence(user_mem_id)) == 2  # 证据挂到 user 级记忆
    store.close()


def test_cross_scope_pair_guards(tmp_path, hash_embed, monkeypatch):
    """护栏：非 preference 维度 / corrected / 维度不相等 → 不跨 scope，走正常准入。"""
    from ethan.memory.admission import run_incremental_admission
    from ethan.memory.records import MemoryCandidate

    store = MemoryStore(tmp_path / "memory.db")
    user_mem_id = _seed_user_preference(store)

    # corrected：替换语义不走"只补证据"通道
    corrected = _pref_candidate(level="corrected", scope_id="proj_c")
    store.create_candidate_batch([corrected])
    r = run_incremental_admission(store, [corrected])
    assert len(r.admitted) == 1 and r.admitted[0] != user_mem_id
    assert store.get_memory(r.admitted[0]).scope_type == "project"

    # 维度严格相等：preference.format ≠ preference.content 不配
    # （各 case 独立 scope，避免同 scope 语义配对互相干扰）
    diff_dim = _pref_candidate(dimension="preference.format", scope_id="proj_d", session="s3")
    store.create_candidate_batch([diff_dim])
    r2 = run_incremental_admission(store, [diff_dim])
    assert len(r2.admitted) == 1 and r2.admitted[0] != user_mem_id

    # 非偏好维度（decision）从不跨 scope
    decision = MemoryCandidate(
        memory_type="decision", dimension="decision.chosen",
        memory_key="decision.chosen:x", content="精读的论文要做成PPT",
        scope_type="project", scope_id="proj_e", memory_domain="general",
        evidence_level="explicit", source_session_id="s4", source_message_id="2",
        source_role="user", source_quote="精读的论文要做成PPT",
        confidence=0.9, importance=0.8,
    )
    store.create_candidate_batch([decision])
    r3 = run_incremental_admission(store, [decision])
    assert len(r3.admitted) == 1 and r3.admitted[0] != user_mem_id
    assert len(store.list_evidence(user_mem_id)) == 1  # user 级记忆零污染
    store.close()


def test_cross_scope_pair_excludes_observed(tmp_path, hash_embed, monkeypatch):
    """observed 噪声不跨 scope：单 session observed 落 pending，不碰 user 级记忆。"""
    from ethan.memory.admission import run_incremental_admission

    store = MemoryStore(tmp_path / "memory.db")
    user_mem_id = _seed_user_preference(store)

    obs = _pref_candidate(level="observed")
    store.create_candidate_batch([obs])
    r = run_incremental_admission(store, [obs])
    assert not r.admitted and not r.merged
    assert store.get_candidate(obs.id).processing_status == "pending"
    assert len(store.list_evidence(user_mem_id)) == 1
    store.close()


# ── 阶段3：tentative 清标 + project 唤醒钩子 ────────────────────────────────


def _decision_candidate(
    *, content: str = "先试试因子动量方案A", scope_id: str = "proj_factor",
    session: str = "s1", structured: dict | None = None,
    memory_key: str = "decision.chosen:plan",
):
    from ethan.memory.records import MemoryCandidate

    return MemoryCandidate(
        memory_type="decision", dimension="decision.chosen",
        memory_key=memory_key, content=content,
        scope_type="project", scope_id=scope_id, memory_domain="general",
        evidence_level="explicit", source_session_id=session, source_message_id="9",
        source_role="user", source_quote=content, confidence=0.9, importance=0.8,
        structured_data=structured or {},
    )


def test_reinforce_clears_tentative_flag(tmp_path):
    """tentative 记忆被非临时候选强化 → 清标退出 Tier C，且 updated_at 重置。"""
    from ethan.memory.admission import run_incremental_admission

    store = MemoryStore(tmp_path / "memory.db")
    first = _decision_candidate(session="s1", structured={"tentative": True})
    store.create_candidate_batch([first])
    mem_id = run_incremental_admission(store, [first]).admitted[0]
    assert store.get_memory(mem_id).structured_data.get("tentative") is True
    before = store.get_memory(mem_id).updated_at

    final = _decision_candidate(session="s2")  # 同 key 同文，无 tentative
    store.create_candidate_batch([final])
    r2 = run_incremental_admission(store, [final])

    assert r2.merged == [mem_id]
    got = store.get_memory(mem_id)
    assert got.structured_data.get("tentative") is None, "定稿强化应清标"
    assert memory_tier(got) == TIER_B  # 退出快速衰减轨道
    assert got.updated_at >= before
    assert len(store.list_evidence(mem_id)) == 2
    store.close()


def test_tentative_candidate_keeps_flag_on_tentative_existing(tmp_path):
    """候选本身也是 tentative（先试 A 又说再试试 A）→ 不清标。"""
    from ethan.memory.admission import run_incremental_admission

    store = MemoryStore(tmp_path / "memory.db")
    first = _decision_candidate(session="s1", structured={"tentative": True})
    store.create_candidate_batch([first])
    mem_id = run_incremental_admission(store, [first]).admitted[0]

    again = _decision_candidate(session="s2", structured={"tentative": True})
    store.create_candidate_batch([again])
    run_incremental_admission(store, [again])

    assert store.get_memory(mem_id).structured_data.get("tentative") is True
    assert memory_tier(store.get_memory(mem_id)) == TIER_C
    store.close()


def test_project_admission_wakes_dormant_scope(tmp_path, hash_embed):
    """project scope 有新候选落地 → 该 scope 的 dormant 记忆自动唤醒。"""
    from ethan.memory.admission import run_incremental_admission
    from ethan.memory.records import MemoryCandidate

    store = MemoryStore(tmp_path / "memory.db")
    old = MemoryCandidate(
        memory_type="decision", dimension="decision.chosen",
        memory_key="decision.chosen:old", content="路线B定稿",
        scope_type="project", scope_id="proj_ppt", memory_domain="general",
        evidence_level="explicit", source_session_id="s1", source_message_id="1",
        source_role="user", source_quote="路线B定稿", confidence=0.9, importance=0.8,
    )
    store.create_candidate_batch([old])
    old_id = run_incremental_admission(store, [old]).admitted[0]
    store.bulk_set_dormant([old_id])
    assert store.get_memory(old_id).status == MemoryStatus.DORMANT.value

    fresh = MemoryCandidate(
        memory_type="decision", dimension="decision.chosen",
        memory_key="decision.chosen:fresh", content="补充口径：风险来自验证层",
        scope_type="project", scope_id="proj_ppt", memory_domain="general",
        evidence_level="explicit", source_session_id="s2", source_message_id="2",
        source_role="user", source_quote="补充口径：风险来自验证层",
        confidence=0.9, importance=0.7,
    )
    store.create_candidate_batch([fresh])
    run_incremental_admission(store, [fresh])

    got = store.get_memory(old_id)
    assert got.status == MemoryStatus.ACTIVE.value and got.dormant_at is None
    store.close()
