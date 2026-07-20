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
    fail_daily,
    run_daily_admission,
)
from ethan.memory.records import DailySummary, MemoryDomain, MemoryStatus
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


# 兜底扫描门槛：3 轮实时提取漏掉的短会话，在 12 点补一次
_BACKFILL_MIN_CHARS = 500          # user 消息累计字符数（≈125 token）门槛，过滤 hi/hello/天气类短问答
_BACKFILL_MAX_USER_TURNS = 2       # 只补 user_turns <= 2 的 session（3 轮已能实时触发）


async def _backfill_short_sessions(
    target_date: date,
    start_ts: float,
    end_ts: float,
    model: str,
    user_id: str,
) -> int:
    """12 点兜底扫描：对当日 user_turns < 3 但内容有价值的 session 补一次提取。

    解决场景：用户每个 session 只问 1-2 次但跨多天问了同一主题——
    实时链路的 % 3 门槛永远无法触发，这些 session 会被漏掉。

    过滤：
    - 跳过 heartbeat / midnight 等 system session
    - user_turns >= 3 的 session 已经实时触发过，跳过
    - user 消息累计字符 < _BACKFILL_MIN_CHARS 视为闲聊，跳过（避免浪费 LLM token）
    - _run_structured_extraction 内部还有 claim_job + 水位线检查，已提取过的会自动 return

    返回本次兜底扫描尝试提取的 session 数。
    """
    from ethan.core.paths import user_sessions_db_path
    from ethan.interface.routers.tasks import _run_structured_extraction
    from ethan.memory.session import SessionStore

    sess_store = SessionStore(db_path=user_sessions_db_path())
    await sess_store.init()
    tried = 0
    try:
        sessions = await sess_store.list_in_range(
            start_ts, end_ts,
            exclude_sources=["heartbeat"],
            exclude_title_prefixes=["[心跳]", "[午夜]"],
        )
        for sess_meta in sessions:
            full_sess = await sess_store.load(sess_meta.id)
            if not full_sess:
                continue
            user_msgs = [m for m in full_sess.messages if m.role == "user" and m.content]
            if len(user_msgs) >= 3:
                continue  # 已能被实时链路触发
            if len(user_msgs) > _BACKFILL_MAX_USER_TURNS:
                continue
            total_chars = sum(len(m.content) for m in user_msgs)
            if total_chars < _BACKFILL_MIN_CHARS:
                continue  # 闲聊过滤
            try:
                await _run_structured_extraction(
                    full_sess, model, user_id, len(user_msgs), force=True,
                )
                tried += 1
            except Exception:
                logger.warning(
                    "[StructuredConsolidation] backfill failed for session=%s",
                    sess_meta.id, exc_info=True,
                )
        return tried
    finally:
        await sess_store.close()


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

    5 轮实时抽取已覆盖当日 session 的提取职责，12 点任务不再重提取。
    本函数只做：pending 跨 session 复评 + TTL 过期 + 按域日摘要。
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
        "backfilled": 0,
        "skipped": False,
    }

    memory_store = MemoryStore()
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

        # 当日 session 重提取已删除：3 轮实时抽取（_run_structured_extraction）
        # 已在对话过程中完成提取+准入，12 点不再重复处理当日 session。

        # 兜底扫描：补一次 user_turns < 3 的短会话（3 轮实时门槛漏掉的场景）
        # 在跨 session 复评之前跑——这样兜底产生的 pending 候选能被下面的复评处理
        try:
            from ethan.core.config import get_config
            backfill_model = get_config().defaults.model
            backfilled = await _backfill_short_sessions(
                d, start_ts, end_ts, backfill_model, user_id,
            )
            result["backfilled"] = backfilled
            if backfilled:
                logger.info("[StructuredConsolidation] backfilled %d short sessions for %s",
                            backfilled, local_date)
        except Exception:
            logger.warning("[StructuredConsolidation] backfill scan failed for %s",
                           local_date, exc_info=True)
            result["backfilled"] = 0

        # Re-evaluate observations from multiple sessions. 3 轮抽取产生的
        # pending candidates 在这里做跨 session 复评，observed → inferred.
        pending = memory_store.list_pending_candidates(limit=2000)
        if pending:
            admitted = run_daily_admission(memory_store, pending)
            result["admitted"] += len(admitted.admitted)
            result["merged"] += len(admitted.merged)
            result["rejected"] += len(admitted.rejected)
            result["disputed"] += len(admitted.disputed)

        result["expired"] = _expire_memories(memory_store, time.time())

        # 日摘要：基于当日准入的 memories（而非重提取的 candidates）
        for domain in (MemoryDomain.GENERAL.value, MemoryDomain.COMPANION.value):
            domain_memories = memory_store.list_memories(
                memory_domain=domain,
                status=MemoryStatus.ACTIVE.value,
                limit=5000,
            )
            day_memories = [
                m for m in domain_memories
                if start_ts <= (m.created_at or 0) < end_ts
            ]
            if not day_memories:
                continue
            data = await _summarize_candidates(day_memories, domain=domain)
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
        memory_store.close()
