"""Daily structured-memory consolidation.

This is the second half of the structured-memory pipeline. Incremental
extraction runs every five turns; the daily pass fills gaps from short
sessions, re-evaluates pending observations across sessions, expires TTL
records, and writes general/companion daily summaries separately.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

from ethan.core.context import get_user_id
from ethan.memory.admission import (
    PIPELINE_VERSION,
    claim_daily,
    complete_daily,
    daily_job_key,
    fail_daily,
    run_daily_admission,
)
from ethan.memory.extractors import SourceMessage, StructuredMemoryExtractor
from ethan.memory.records import DailySummary, MemoryDomain, MemoryStatus
from ethan.memory.session import SessionStore
from ethan.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_SUMMARY_KEYS = (
    "activities",
    "outcomes",
    "decisions",
    "personal_updates",
    "methodology_evidence",
    "skill_learnings",
    "open_loops",
)

_SUMMARY_SYSTEM = (
    "你是结构化记忆每日摘要器。只输出严格 JSON，不要 markdown 或解释文字。"
    "不得创造来源中不存在的事实，不得把单次行为或情绪升级为稳定特征。"
)


def _day_bounds(d: date) -> tuple[float, float]:
    from ethan.core.timezone import get_local_timezone

    tz = get_local_timezone()
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def _candidate_payload(candidates: list) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        payload.append({
            "id": candidate.id,
            "memory_type": candidate.memory_type,
            "dimension": candidate.dimension,
            "content": candidate.content,
            "structured_data": candidate.structured_data,
            "scope_type": candidate.scope_type,
            "scope_id": candidate.scope_id,
            "evidence_level": candidate.evidence_level,
            "source_session_id": candidate.source_session_id,
            "source_message_id": candidate.source_message_id,
            "source_quote": candidate.source_quote,
        })
    return payload


def _fallback_summary(candidates: list, *, domain: str) -> dict[str, Any]:
    """Build a conservative, source-backed summary when the LLM is unavailable."""
    result: dict[str, Any] = {key: [] for key in _SUMMARY_KEYS}
    for candidate in candidates:
        item = {
            "content": candidate.content,
            "memory_type": candidate.memory_type,
            "source_session_id": candidate.source_session_id,
            "source_message_id": candidate.source_message_id,
        }
        if candidate.memory_type == "activity":
            result["activities"].append(item)
        elif candidate.memory_type == "decision":
            result["decisions"].append(item)
        elif candidate.memory_type in {"personal_information", "preference", "relationship"}:
            result["personal_updates"].append(item)
        elif candidate.memory_type == "methodology":
            result["methodology_evidence"].append(item)
        elif candidate.memory_type == "skill_experience":
            result["skill_learnings"].append(item)
        elif domain == MemoryDomain.COMPANION.value:
            result["outcomes"].append(item)
    return result


async def _summarize_candidates(candidates: list, *, domain: str) -> dict[str, Any]:
    if not candidates:
        return {key: [] for key in _SUMMARY_KEYS}
    fallback = _fallback_summary(candidates, domain=domain)
    try:
        from ethan.memory.consolidator import get_lite_model
        from ethan.providers.base import Message
        from ethan.providers.manager import create_provider

        prompt = (
            "请把以下来源明确的记忆候选压缩为每日摘要。输出 JSON 对象，键必须为："
            + ", ".join(_SUMMARY_KEYS)
            + "。每个值必须为数组；每项保留 content 与 source_session_id/source_message_id。"
            + ("这是苏念 companion 域，只能总结情绪事件/支持偏好/边界。" if domain == MemoryDomain.COMPANION.value else "不得包含 companion 情感内容。")
            + "\n候选：\n"
            + json.dumps(_candidate_payload(candidates), ensure_ascii=False)
        )
        provider = create_provider(get_lite_model())
        response = await provider.chat(
            [Message(role="user", content=prompt)],
            system=_SUMMARY_SYSTEM,
        )
        raw = (response.content or "").strip()
        if "```" in raw:
            return fallback
        data = json.loads(raw)
        if not isinstance(data, dict):
            return fallback
        normalized: dict[str, Any] = {}
        for key in _SUMMARY_KEYS:
            value = data.get(key, [])
            normalized[key] = value if isinstance(value, list) else []
        return normalized
    except Exception:
        logger.warning("[StructuredConsolidation] summary LLM failed; using fallback", exc_info=True)
        return fallback


def _summary_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    labels = {
        "activities": "活动",
        "outcomes": "结果",
        "decisions": "决定",
        "personal_updates": "个人更新",
        "methodology_evidence": "方法论证据",
        "skill_learnings": "技能经验",
        "open_loops": "待继续",
    }
    for key in _SUMMARY_KEYS:
        items = data.get(key) or []
        if not items:
            continue
        parts.append(f"## {labels[key]}")
        for item in items:
            if isinstance(item, dict):
                content = str(item.get("content", "")).strip()
            else:
                content = str(item).strip()
            if content:
                parts.append(f"- {content}")
    return "\n".join(parts)


def _expire_memories(store: MemoryStore, now: float) -> int:
    expired = 0
    for memory in store.list_memories(status=MemoryStatus.ACTIVE.value, limit=5000):
        if memory.valid_until is not None and memory.valid_until < now:
            store.set_status(memory.id, MemoryStatus.EXPIRED.value)
            expired += 1
    return expired


async def run_structured_consolidation(target_date: date | None = None) -> dict[str, Any]:
    """Consolidate structured memories for one local day and current user.

    The current user is resolved from ``ETHAN_USER_ID`` through the per-user
    path helpers. A DB job keyed by user/date/pipeline provides idempotency;
    failed jobs remain retryable and completed/running jobs are skipped.
    """
    d = target_date or (date.today() - timedelta(days=1))
    local_date = d.isoformat()
    start_ts, end_ts = _day_bounds(d)
    user_id = get_user_id()
    result: dict[str, Any] = {
        "date": local_date,
        "sessions": 0,
        "candidates": 0,
        "admitted": 0,
        "merged": 0,
        "rejected": 0,
        "disputed": 0,
        "expired": 0,
        "summaries": 0,
        "skipped": False,
    }

    memory_store = MemoryStore()
    session_store = SessionStore()
    claimed = False
    try:
        claimed = claim_daily(
            memory_store,
            user_id=user_id,
            local_date=local_date,
            source_until=end_ts,
        )
        if not claimed:
            result["skipped"] = True
            return result

        await session_store.init()
        sessions = await session_store.list_in_range(
            start_ts,
            end_ts,
            exclude_sources=["heartbeat"],
            exclude_title_prefixes=["[心跳]", "[定时]", "[后台]"],
        )
        result["sessions"] = len(sessions)
        extractor = StructuredMemoryExtractor()
        day_candidates = []
        job_key = daily_job_key(user_id, local_date)

        for session_meta in sessions:
            session = await session_store.load(session_meta.id)
            if not session:
                continue
            source_messages = [
                SourceMessage.from_message(message, session.id)
                for message in session.messages
                if message.role in {"user", "assistant"} and message.content and message.id is not None
            ]
            if not source_messages:
                continue
            candidates = await extractor.extract(
                source_messages,
                session_id=session.id,
                user_id=user_id,
                mode=session.mode,
                job_key=job_key,
            )
            inserted_ids = set(memory_store.create_candidate_batch(candidates))
            inserted = [candidate for candidate in candidates if candidate.id in inserted_ids]
            day_candidates.extend(inserted)
            result["candidates"] += len(inserted)
            admitted = run_daily_admission(memory_store, inserted)
            result["admitted"] += len(admitted.admitted)
            result["merged"] += len(admitted.merged)
            result["rejected"] += len(admitted.rejected)
            result["disputed"] += len(admitted.disputed)

        # Re-evaluate observations from multiple sessions. Newly admitted ones
        # are already processed, so only genuinely pending candidates remain.
        pending = memory_store.list_pending_candidates(limit=2000)
        if pending:
            admitted = run_daily_admission(memory_store, pending)
            result["admitted"] += len(admitted.admitted)
            result["merged"] += len(admitted.merged)
            result["rejected"] += len(admitted.rejected)
            result["disputed"] += len(admitted.disputed)

        result["expired"] = _expire_memories(memory_store, time.time())

        for domain in (MemoryDomain.GENERAL.value, MemoryDomain.COMPANION.value):
            domain_candidates = [c for c in day_candidates if c.memory_domain == domain]
            if not domain_candidates:
                continue
            data = await _summarize_candidates(domain_candidates, domain=domain)
            summary = DailySummary(
                user_id=user_id,
                local_date=local_date,
                pipeline_version=PIPELINE_VERSION,
                memory_domain=domain,
                summary_text=_summary_text(data),
                structured_data=data,
                source_from=start_ts,
                source_until=end_ts,
            )
            memory_store.upsert_daily_summary(summary)
            result["summaries"] += 1

        complete_daily(memory_store, user_id=user_id, local_date=local_date, result=result)
        return result
    except Exception as exc:
        if claimed:
            try:
                fail_daily(
                    memory_store,
                    user_id=user_id,
                    local_date=local_date,
                    error=str(exc),
                )
            except Exception:
                logger.exception("[StructuredConsolidation] failed to record job failure")
        raise
    finally:
        try:
            await session_store.close()
        except Exception:
            pass
        memory_store.close()
