"""Tests for the structured memory pipeline (Phases 1-9)."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from ethan.core.context import ETHAN_USER_ID
from ethan.memory.admission import run_incremental_admission
from ethan.memory.extractors import SourceMessage, StructuredMemoryExtractor
from ethan.memory.recall import build_structured_recall
from ethan.memory.records import (
    ConsolidationJob,
    DailySummary,
    MemoryCandidate,
    MemoryStatus,
)
from ethan.memory.store import MemoryStore


def candidate(
    *,
    content: str = "我叫小明",
    level: str = "explicit",
    session: str = "s1",
    message: str = "1",
    memory_type: str = "personal_information",
    dimension: str = "identity.preferred_name",
    domain: str = "general",
    sensitivity: str = "normal",
    valid_until: float | None = None,
) -> MemoryCandidate:
    return MemoryCandidate(
        memory_type=memory_type,
        dimension=dimension,
        memory_key=dimension,
        content=content,
        scope_type="mode" if domain == "companion" else "user",
        scope_id="companion" if domain == "companion" else "self",
        memory_domain=domain,
        evidence_level=level,
        source_session_id=session,
        source_message_id=message,
        source_role="user",
        source_quote=content,
        confidence=0.9,
        importance=0.8,
        sensitivity=sensitivity,
        valid_until=valid_until,
        user_id="",
    )


@pytest.fixture
def isolated_paths(tmp_path):
    token = ETHAN_USER_ID.set("")
    with patch("ethan.core.paths.CONFIG_DIR", tmp_path), patch("ethan.core.config.CONFIG_DIR", tmp_path):
        yield tmp_path
    ETHAN_USER_ID.reset(token)


def test_explicit_admission_reports_and_persists(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    cand = candidate()
    assert store.create_candidate_batch([cand]) == [cand.id]

    result = run_incremental_admission(store, [cand])

    assert len(result.admitted) == 1
    memory = store.get_memory(result.admitted[0])
    assert memory is not None
    assert memory.status == MemoryStatus.ACTIVE.value
    assert memory.content == "我叫小明"
    assert store.get_candidate(cand.id).processing_status == "admitted"
    assert len(store.list_evidence(memory.id)) == 1
    store.close()


def test_candidate_dedup_and_same_content_merge(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    first = candidate()
    assert store.create_candidate_batch([first]) == [first.id]
    assert store.create_candidate_batch([first]) == []
    first_result = run_incremental_admission(store, [first])

    second = candidate(session="s2", message="2")
    store.create_candidate_batch([second])
    result = run_incremental_admission(store, [second])

    assert result.merged == first_result.admitted
    active = store.list_memories(status="active")
    assert len(active) == 1
    assert len(store.list_evidence(active[0].id)) == 2
    store.close()


def test_corrected_candidate_supersedes(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    old = candidate(content="我叫小明")
    store.create_candidate_batch([old])
    old_id = run_incremental_admission(store, [old]).admitted[0]

    corrected = candidate(content="请叫我 Calvin", level="corrected", session="s2", message="2")
    store.create_candidate_batch([corrected])
    result = run_incremental_admission(store, [corrected])

    assert len(result.admitted) == 1
    old_memory = store.get_memory(old_id)
    new_memory = store.get_memory(result.admitted[0])
    assert old_memory.status == "superseded"
    assert old_memory.superseded_by == new_memory.id
    assert new_memory.status == "active"
    assert new_memory.content == "请叫我 Calvin"
    store.close()


def test_observed_requires_two_independent_sessions(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    first = candidate(content="比较方案时先跑评测集", level="observed", session="s1", dimension="methodology.evaluation_criteria", memory_type="methodology")
    store.create_candidate_batch([first])
    result = run_incremental_admission(store, [first])
    assert result.admitted == []
    assert store.get_candidate(first.id).processing_status == "pending"

    second = candidate(content="比较方案时先跑评测集", level="observed", session="s2", message="2", dimension="methodology.evaluation_criteria", memory_type="methodology")
    store.create_candidate_batch([second])
    result = run_incremental_admission(store, [second])
    assert len(result.admitted) == 1
    assert store.get_memory(result.admitted[0]).evidence_level == "inferred"
    store.close()


def test_update_and_forget_redact_evidence(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    cand = candidate(sensitivity="restricted")
    store.create_candidate_batch([cand])
    memory_id = run_incremental_admission(store, [cand]).admitted[0]

    updated = store.update_memory(memory_id, content="请叫我 Calvin", confidence=1.0)
    assert updated.content == "请叫我 Calvin"
    assert updated.confidence == 1.0
    assert store.list_evidence(memory_id, redact_restricted=True)[0]["source_quote"] == "[redacted]"

    store.forget_memory(memory_id)
    forgotten = store.get_memory(memory_id)
    assert forgotten.status == "forgotten"
    assert forgotten.content == "[forgotten]"
    assert store.list_evidence(memory_id)[0]["source_quote"] == "[forgotten]"
    store.close()


def test_job_idempotency_and_retry(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    job = ConsolidationJob(user_id="", job_type="daily_consolidation", job_key="daily:default:2026-07-15:v1", pipeline_version="v1")
    assert store.claim_job(job) is True
    assert store.claim_job(job) is False
    store.fail_job(job.job_key, "boom")
    assert store.claim_job(job) is True
    store.complete_job(job.job_key, {"ok": True})
    assert store.claim_job(job) is False
    store.close()


class FakeProvider:
    def __init__(self, payload: dict):
        self.payload = payload

    async def chat(self, messages, tools=None, system=None, max_tokens=None):
        from ethan.providers.base import Message
        return Message(role="assistant", content=json.dumps(self.payload, ensure_ascii=False))


@pytest.mark.anyio
async def test_extractor_enforces_quote_and_companion_boundary():
    messages = [SourceMessage(session_id="s1", message_id=1, role="user", content="我叫小明")]
    payload = {
        "candidates": [{
            "memory_type": "personal_information",
            "dimension": "identity.preferred_name",
            "memory_key": "identity.preferred_name",
            "content": "用户叫小明",
            "evidence_level": "explicit",
            "scope_type": "user",
            "scope_id": "self",
            "message_id": 1,
            "quote": "并不存在的原文",
            "confidence": 1.0,
            "importance": 0.8,
            "structured": {},
        }]
    }
    extractor = StructuredMemoryExtractor(provider=FakeProvider(payload))
    assert await extractor.extract(messages, session_id="s1", mode="") == []

    payload["candidates"][0].update({
        "memory_type": "companion",
        "dimension": "companion.current_emotion",
        "memory_key": "companion.current_emotion",
        "content": "小明感到焦虑",
        "quote": "我叫小明",
    })
    extractor = StructuredMemoryExtractor(provider=FakeProvider(payload))
    assert await extractor.extract(messages, session_id="s1", mode="") == []


@pytest.mark.anyio
async def test_extractor_rejects_companion_diagnostic_terms():
    messages = [SourceMessage(session_id="s1", message_id=1, role="user", content="我今天有点低落")]
    payload = {"candidates": [{
        "memory_type": "companion",
        "dimension": "companion.current_emotion",
        "memory_key": "companion.current_emotion",
        "content": "用户有抑郁症",
        "evidence_level": "explicit",
        "scope_type": "mode",
        "scope_id": "companion",
        "message_id": 1,
        "quote": "我今天有点低落",
        "confidence": 0.9,
        "importance": 0.8,
        "structured": {},
    }]}
    extractor = StructuredMemoryExtractor(provider=FakeProvider(payload))
    assert await extractor.extract(messages, session_id="s1", mode="companion") == []


def test_recall_isolates_companion_and_restricted(isolated_paths):
    store = MemoryStore()
    general = candidate(content="我叫小明")
    companion = candidate(
        content="最近因延期感到焦虑",
        memory_type="companion",
        dimension="companion.current_emotion",
        domain="companion",
    )
    restricted = candidate(content="不应注入的秘密", sensitivity="restricted", session="s3", dimension="identity.organization")
    for cand in (general, companion, restricted):
        store.create_candidate_batch([cand])
        run_incremental_admission(store, [cand])
    store.close()

    normal = build_structured_recall("小明", mode="")
    assert "我叫小明" in normal
    assert "焦虑" not in normal
    assert "秘密" not in normal

    companion_context = build_structured_recall("焦虑", mode="companion")
    assert "焦虑" in companion_context


def test_daily_summary_upsert_is_idempotent(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    first = DailySummary(
        user_id="", local_date="2026-07-15", pipeline_version="v1",
        memory_domain="general", summary_text="first", structured_data={"activities": []},
    )
    second = DailySummary(
        user_id="", local_date="2026-07-15", pipeline_version="v1",
        memory_domain="general", summary_text="second", structured_data={"activities": ["x"]},
    )
    first_id = store.upsert_daily_summary(first)
    second_id = store.upsert_daily_summary(second)
    assert first_id == second_id
    rows = store.get_daily_summary("2026-07-15", memory_domain="general")
    assert len(rows) == 1
    assert rows[0]["summary_text"] == "second"
    store.close()


@pytest.mark.anyio
async def test_structured_consolidation_is_idempotent(isolated_paths):
    from ethan.memory.structured_consolidation import run_structured_consolidation

    result = await run_structured_consolidation(date(2026, 7, 15))
    assert result["skipped"] is False
    assert result["sessions"] == 0

    again = await run_structured_consolidation(date(2026, 7, 15))
    assert again["skipped"] is True


@pytest.mark.anyio
async def test_nightly_consolidation_orchestrates_in_order(isolated_paths):
    """夜间统一沉淀：结构化先跑（新准入记忆进入做梦的去重底库），做梦后跑。"""
    from datetime import date as _date

    import ethan.memory.nightly_consolidation as nightly

    calls = []

    async def fake_structured(d):
        calls.append(("structured", d))
        return {"date": d.isoformat(), "candidates": 3, "admitted": 2, "skipped": False}

    async def fake_daily(d):
        calls.append(("daily", d))
        return 1

    with patch("ethan.memory.structured_consolidation.run_structured_consolidation", fake_structured), \
         patch("ethan.memory.daily_consolidation.run_daily_consolidation", fake_daily):
        result = await nightly.run_nightly_consolidation(_date(2026, 7, 15))

    assert [name for name, _ in calls] == ["structured", "daily"]
    assert result["structured"]["admitted"] == 2
    assert result["insights_added"] == 1


@pytest.mark.anyio
async def test_nightly_consolidation_tolerates_step_failure(isolated_paths):
    """单步失败不影响另一步执行（各自保留 job 记录，下一夜独立重试）。"""
    from datetime import date as _date

    import ethan.memory.nightly_consolidation as nightly

    async def boom(d):
        raise RuntimeError("llm down")

    async def fake_daily(d):
        return 2

    with patch("ethan.memory.structured_consolidation.run_structured_consolidation", boom), \
         patch("ethan.memory.daily_consolidation.run_daily_consolidation", fake_daily):
        result = await nightly.run_nightly_consolidation(_date(2026, 7, 15))

    assert result["structured"] == {"error": True}
    assert result["insights_added"] == 2


# ── PR-4b: 语义配对准入 + 混合召回 ─────────────────────────────────────────

@pytest.fixture
def hash_embed():
    """强制 hash embedding（离线、确定性），与 test_dream_e2e 同一手法。"""
    import ethan.memory.embeddings as emb
    old_checked, old_encoder = emb._encoder_checked, emb._encoder
    emb._encoder = None
    emb._encoder_checked = True
    yield
    emb._encoder_checked, emb._encoder = old_checked, old_encoder


def _pair_candidate(*, content, key, level="inferred", session="s1", dimension="identity.location"):
    return MemoryCandidate(
        memory_type="personal_information",
        dimension=dimension,
        memory_key=key,
        content=content,
        scope_type="user",
        scope_id="self",
        memory_domain="general",
        evidence_level=level,
        source_session_id=session,
        source_message_id="1",
        source_role="user",
        source_quote=content,
        confidence=0.9,
        importance=0.8,
    )


def test_semantic_pair_merges_inferred(tmp_path, hash_embed, monkeypatch):
    """推断候选与既有 active 语义相近(不同 key) → 补证据合并,不新建。

    注:hash embedding 语义弱于 BGE,测试放宽阈值验证的是配对→决策的接线,
    阈值标定本身以 BGE 为准(live 评测守门)。
    """
    monkeypatch.setattr("ethan.memory.memory_vectors.MERGE_L2_THRESHOLD", 1.2)
    store = MemoryStore(tmp_path / "memory.db")
    first = _pair_candidate(content="用户住在深圳", key="loc_a", level="explicit")
    store.create_candidate_batch([first])
    r1 = run_incremental_admission(store, [first])
    assert len(r1.admitted) == 1

    second = _pair_candidate(content="用户家在深圳", key="loc_b", session="s2")
    store.create_candidate_batch([second])
    r2 = run_incremental_admission(store, [second])

    assert r2.merged == r1.admitted, f"应语义合并进既有记忆: {r2}"
    assert len(store.list_memories(status="active")) == 1
    reason = store.get_candidate(second.id).processing_reason
    assert reason.startswith("semantic_merged:"), reason
    store.close()


def test_semantic_pair_supersedes_explicit_same_dimension(tmp_path, hash_embed, monkeypatch):
    """explicit + 同维度 + 内容发散 → 语义 supersede(用户更新了该方面事实)。"""
    monkeypatch.setattr("ethan.memory.memory_vectors.MERGE_L2_THRESHOLD", 1.2)
    store = MemoryStore(tmp_path / "memory.db")
    first = _pair_candidate(content="用户住在深圳", key="loc_a", level="explicit")
    store.create_candidate_batch([first])
    r1 = run_incremental_admission(store, [first])

    second = _pair_candidate(content="用户住在深圳南山区", key="loc_b", level="explicit", session="s2")
    store.create_candidate_batch([second])
    r2 = run_incremental_admission(store, [second])

    assert len(r2.admitted) == 1 and r2.admitted != r1.admitted
    old = store.get_memory(r1.admitted[0])
    assert old.status == MemoryStatus.SUPERSEDED.value
    assert old.superseded_by == r2.admitted[0]
    assert store.get_candidate(second.id).processing_reason.startswith("semantic_superseded:")
    store.close()


def test_semantic_pair_observed_gate_preserved(tmp_path, hash_embed, monkeypatch):
    """observed 候选即使语义命中,也必须先凑齐 ≥2 session 才并入近邻。"""
    monkeypatch.setattr("ethan.memory.memory_vectors.MERGE_L2_THRESHOLD", 1.2)
    store = MemoryStore(tmp_path / "memory.db")
    first = _pair_candidate(content="用户住在深圳", key="loc_a", level="explicit")
    store.create_candidate_batch([first])
    run_incremental_admission(store, [first])

    obs = _pair_candidate(content="用户家在深圳", key="loc_b", level="observed", session="s2")
    store.create_candidate_batch([obs])
    r = run_incremental_admission(store, [obs])
    assert not r.admitted and not r.merged, "单 session observed 不得并入"
    assert store.get_candidate(obs.id).processing_status == "pending"

    obs2 = _pair_candidate(content="用户家在深圳", key="loc_b", level="observed", session="s3")
    store.create_candidate_batch([obs2])
    r2 = run_incremental_admission(store, [obs2])
    assert len(r2.merged) == 1, "凑齐 2 session 后应并入语义近邻"
    assert len(store.list_memories(status="active")) == 1
    store.close()


def test_no_pair_for_unrelated_content(tmp_path, hash_embed, monkeypatch):
    """语义无关的候选正常新建,不误配对(阈值 1.2 下 L2=1.354 仍不配对)。"""
    monkeypatch.setattr("ethan.memory.memory_vectors.MERGE_L2_THRESHOLD", 1.2)
    store = MemoryStore(tmp_path / "memory.db")
    first = _pair_candidate(content="用户住在深圳", key="loc_a", level="explicit")
    store.create_candidate_batch([first])
    run_incremental_admission(store, [first])

    other = _pair_candidate(content="用户喜欢爬山", key="hobby_a", dimension="identity.expertise")
    store.create_candidate_batch([other])
    r = run_incremental_admission(store, [other])
    assert len(r.admitted) == 1
    assert len(store.list_memories(status="active")) == 2
    store.close()


def test_hybrid_recall_vector_channel(tmp_path, hash_embed, monkeypatch):
    """FTS/LIKE 都命不中的查询,向量通道应召回(且不是 importance fallback)。"""
    from ethan.memory.recall import _collect
    monkeypatch.setattr("ethan.memory.memory_vectors.RECALL_L2_MAX", 1.2)
    store = MemoryStore(tmp_path / "memory.db")
    cand = _pair_candidate(content="用户家在深圳南山", key="loc_a", level="explicit")
    store.create_candidate_batch([cand])
    run_incremental_admission(store, [cand])
    # 高重要性无关记忆:若向量通道失效,fallback 只会返回它
    import dataclasses
    noise = _pair_candidate(content="用户喜欢爬山", key="hobby_a", dimension="identity.expertise")
    noise = dataclasses.replace(noise, importance=0.99)
    store.create_candidate_batch([noise])
    run_incremental_admission(store, [noise])

    # "深圳南山公园"不是正文子串(LIKE miss);hash embed 下目标 L2=1.088、
    # 噪音 L2=1.414 —— 阈值 1.2 时只有目标能过向量通道。
    # 若向量通道失效:fallback 按 importance 会先返回噪音(0.99),断言即失败。
    hits = _collect(store, "深圳南山公园", domain="general", max_items=8)
    contents = [h.content for h in hits]
    assert any("深圳" in c for c in contents), f"向量通道应召回语义近邻: {contents}"
    assert all("爬山" not in c for c in contents), f"fallback 不应混入高重要性噪音: {contents}"
    store.close()


def test_forget_removes_vector_index(tmp_path, hash_embed):
    """forget 脱敏必须连向量索引一起删,否则 vec_items.text 泄漏原文。"""
    from ethan.memory.memory_vectors import semantic_neighbors
    store = MemoryStore(tmp_path / "memory.db")
    cand = _pair_candidate(content="用户住在深圳", key="loc_a", level="explicit")
    store.create_candidate_batch([cand])
    r = run_incremental_admission(store, [cand])
    mem_id = r.admitted[0]

    before = semantic_neighbors(
        content="用户住在深圳", scope_type="user", scope_id="self",
        memory_domain="general", db_path=store.db_path,
    )
    assert any(h["id"] == mem_id for h in before)

    store.forget_memory(mem_id)
    after = semantic_neighbors(
        content="用户住在深圳", scope_type="user", scope_id="self",
        memory_domain="general", db_path=store.db_path,
    )
    assert all(h["id"] != mem_id for h in after)
    store.close()


def test_observed_accrual_mode_admits_low_confidence(tmp_path, monkeypatch):
    """accrual 模式:单 session observed 即建 active(confidence 封 0.5)。"""
    monkeypatch.setattr("ethan.memory.admission.OBSERVED_MODE", "accrual")
    store = MemoryStore(tmp_path / "memory.db")
    cand = candidate(level="observed")
    store.create_candidate_batch([cand])
    result = run_incremental_admission(store, [cand])
    assert len(result.admitted) == 1
    memory = store.get_memory(result.admitted[0])
    assert memory.confidence <= 0.5
    assert store.get_candidate(cand.id).processing_reason == "accrual_low_confidence"
    store.close()
