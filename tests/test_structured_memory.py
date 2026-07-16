"""Tests for the structured memory pipeline (Phases 1-9)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
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

    async def chat(self, messages, tools=None, system=None):
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
