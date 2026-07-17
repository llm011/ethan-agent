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
    statuses = [MemoryStatus.ACTIVE.value]
    if query.strip():
        hits = store.search_memories(query, memory_domain=domain, statuses=statuses, limit=max_items)
        hits = [memory for memory in hits if memory.sensitivity != "restricted"]
        if hits:
            return hits
    # Fall back to the most important active memories when there is no query
    # or the query matches nothing — keeps identity facts available.
    return [
        memory
        for memory in store.list_memories(
            memory_domain=domain, status=MemoryStatus.ACTIVE.value, limit=max_items * 3
        )
        if memory.sensitivity != "restricted"
    ][:max_items]


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
