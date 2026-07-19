"""Recall structured memories into the agent's system prompt.

这是对话时长期记忆的唯一召回入口（flat-facts 系统已退役）。Companion-domain
memories are recalled only in companion mode so emotional data never leaks into
other sessions. Restricted memories are never injected.
"""
from __future__ import annotations

import logging
from typing import Any

from ethan.memory.records import MemoryDomain, MemoryStatus
from ethan.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_TYPE_LABELS = {
    "personal_information": "个人信息",
    "preference": "偏好",
    "methodology": "方法论",
    "activity": "正在做的事",
    "decision": "决定",
    "relationship": "约定",
    "skill_experience": "技能经验",
}


def _is_companion_mode(mode: str) -> bool:
    try:
        from ethan.core.modes import resolve_mode

        return resolve_mode(mode).key == "companion"
    except Exception:
        return mode in {"companion", "苏念", "陪伴"}


def _format_block(memory: Any) -> str:
    label = _TYPE_LABELS.get(memory.memory_type, memory.memory_type)
    quote = f" (来源: session={memory.source_session_id or '?'} msg={memory.source_message_id or '?'})" if memory.source_session_id else ""
    return f"[{label}] {memory.content}{quote}"


def _collect(
    store: MemoryStore,
    query: str,
    *,
    domain: str,
    max_items: int,
) -> list[Any]:
    """召回候选集：FTS/LIKE 精确通道 + 向量语义通道，RRF 融合排序。

    向量通道补齐 FTS 的 CJK 分词短板与语义泛化（"住哪" 命中 "家在深圳"）；
    两通道都空时回退 importance top-N，保证身份类事实始终可用。
    """
    statuses = [MemoryStatus.ACTIVE.value]
    fts_hits: list[Any] = []
    vec_hits: list[tuple[str, float]] = []
    if query.strip():
        fts_hits = [
            memory
            for memory in store.search_memories(query, memory_domain=domain, statuses=statuses, limit=max_items)
            if memory.sensitivity != "restricted"
        ]
        from ethan.memory.memory_vectors import recall_neighbors
        vec_hits = recall_neighbors(
            query=query, memory_domain=domain, db_path=store.db_path, limit=max_items * 2
        )

    if not fts_hits and not vec_hits:
        # Fall back to the most important active memories when there is no query
        # or the query matches nothing — keeps identity facts available.
        return [
            memory
            for memory in store.list_memories(
                memory_domain=domain, status=MemoryStatus.ACTIVE.value, limit=max_items * 3
            )
            if memory.sensitivity != "restricted"
        ][:max_items]

    # Reciprocal Rank Fusion(k=60):对两通道的排名取倒数求和,无需标定分数量纲
    import time as _time

    now = _time.time()
    scores: dict[str, float] = {}
    by_id: dict[str, Any] = {}
    for rank, memory in enumerate(fts_hits):
        scores[memory.id] = scores.get(memory.id, 0.0) + 1.0 / (61 + rank)
        by_id[memory.id] = memory
    for rank, (memory_id, _distance) in enumerate(vec_hits):
        memory = by_id.get(memory_id)
        if memory is None:
            memory = store.get_memory(memory_id)
            if memory is None or memory.status != MemoryStatus.ACTIVE.value:
                continue
            if memory.sensitivity == "restricted":
                continue
            if memory.valid_from is not None and memory.valid_from > now:
                continue
            if memory.valid_until is not None and memory.valid_until < now:
                continue
            by_id[memory_id] = memory
        scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (61 + rank)

    merged = sorted(
        by_id.values(),
        key=lambda m: (-scores[m.id], -m.importance, -m.confidence),
    )
    return merged[:max_items]


def build_structured_recall(query: str, *, mode: str = "", max_items: int = 8) -> str:
    """Build a system-prompt memory block from structured memories.

    Returns an empty string when there is nothing to recall so callers can
    cheaply skip injection. Any storage failure is swallowed — recall must
    never break the main conversation.
    """
    try:
        store = MemoryStore()
    except Exception:
        logger.debug("structured recall: store unavailable", exc_info=True)
        return ""

    try:
        general = _collect(store, query, domain=MemoryDomain.GENERAL.value, max_items=max_items)
        companion: list[Any] = []
        if _is_companion_mode(mode):
            companion = _collect(store, query, domain=MemoryDomain.COMPANION.value, max_items=max_items)

        all_hits = general + companion
        if not all_hits:
            return ""

        try:
            store.touch_recalled([memory.id for memory in all_hits])
        except Exception:
            logger.debug("structured recall: touch_recalled failed", exc_info=True)

        lines = [_format_block(memory) for memory in all_hits]
        return "\n".join(lines)
    except Exception:
        logger.debug("structured recall failed", exc_info=True)
        return ""
    finally:
        try:
            store.close()
        except Exception:
            pass
