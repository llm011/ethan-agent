"""Recall structured memories into the agent's system prompt.

这是对话时长期记忆的唯一召回入口（flat-facts 系统已退役）。Companion-domain
memories are recalled only in companion mode so emotional data never leaks into
other sessions. Restricted memories are never injected.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
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


def _collect_split(
    store: MemoryStore, query: str, mode: str, max_items: int
) -> tuple[list[Any], list[Any]]:
    """分域收候选，**不合并**。domain 隔离是硬门控——companion 只在 companion 模式取。

    保持分域返回是为了 fallback 能逐域截断：同步版从不对并集做最终截断，
    companion 模式下 general 和 companion 各拿满 max_items。若在并集上截断，
    general 满额时 companion 会被整段砍掉。
    """
    general = _collect(store, query, domain=MemoryDomain.GENERAL.value, max_items=max_items)
    companion: list[Any] = []
    if _is_companion_mode(mode):
        companion = _collect(
            store, query, domain=MemoryDomain.COMPANION.value, max_items=max_items
        )
    return general, companion


def _finalize(store: MemoryStore, hits: list[Any]) -> "RecallResult":
    """标记已召回 + 格式化。

    touch_recalled 必须在切点之后：被重排砍掉的候选**从未进入 prompt**，若把它们
    也记上 last_recalled_at/recall_count，召回统计就失真，而这套统计会反过来喂
    importance 排序，形成自我强化。
    """
    try:
        store.touch_recalled([memory.id for memory in hits])
    except Exception:
        logger.debug("structured recall: touch_recalled failed", exc_info=True)
    lines = [_format_block(memory) for memory in hits]
    return RecallResult(text="\n".join(lines), count=len(lines), items=lines)


@dataclass
class RecallResult:
    """Structured recall result with metadata for tool-timeline visibility."""
    text: str  # 格式化后注入 system prompt 的多行文本
    count: int  # 召回条数
    items: list[str]  # 每条召回内容的格式化行（前端展开可见）

    def __bool__(self) -> bool:
        return self.count > 0


def build_structured_recall(query: str, *, mode: str = "", max_items: int = 8) -> RecallResult:
    """Build a system-prompt memory block from structured memories.

    Returns a RecallResult (falsy when nothing recalled). Any storage failure
    is swallowed — recall must never break the main conversation.
    """
    empty = RecallResult(text="", count=0, items=[])
    try:
        store = MemoryStore()
    except Exception:
        logger.debug("structured recall: store unavailable", exc_info=True)
        return empty

    try:
        general, companion = _collect_split(store, query, mode, max_items)
        all_hits = general + companion
        if not all_hits:
            return empty
        return _finalize(store, all_hits)
    except Exception:
        logger.debug("structured recall failed", exc_info=True)
        return empty
    finally:
        try:
            store.close()
        except Exception:
            pass


async def build_structured_recall_async(
    query: str, *, mode: str = "", max_items: int = 8,
    fallback_keep: int | None = None, rerank: bool = True,
) -> RecallResult:
    """带 LLM 重排 + 切点的召回。异步调用方应优先用这个。

    与同步版的唯一区别是多一个重排阶段，因此 `max_items` 的语义也变了：
    同步版里它是**注入上限**，这里它是**候选预算**（宽召回，喂给判官），最终注入
    条数由 reranker 的切点 + `MAX_KEEP` 硬上限决定。

    `fallback_keep` 是判官不可用时的注入上限，应填调用方**改造前**的 max_items。
    默认取 `max_items`。两种情形的保真度不同，别混淆：

    - 判官不跑（默认关 / `rerank=False`）：候选预算也收回 `fallback_keep`，
      结果与改造前**逐条一致**（已用 18 case 验证，含 companion 双域路径）。
    - 判官跑了但失败：退回的是**宽预算候选池**的 RRF top-`fallback_keep`。它与
      改造前的窄预算召回**不保证逐条相同**——`_collect` 的 max_items 同时控制
      FTS limit 与向量 limit(*2)，池子变大后双通道命中会拿到额外 RRF 分，可能
      挤掉窄预算下靠前的单通道命中。质量不低于改造前，但不是同一个列表。

    重排在两域候选的**并集**上只做一次，不能下推到 `_collect` 里分域各做一次——
    否则 general 和 companion 会各自算出一个分数分布、各切一个断层，两边按不同
    标准砍，合起来条数还可能翻倍。domain 隔离仍由 `_collect_split` 硬门控保证。
    """
    from ethan.memory.reranker import RERANK_ENABLED, rerank_and_cut

    empty = RecallResult(text="", count=0, items=[])
    keep = max_items if fallback_keep is None else fallback_keep
    do_rerank = rerank and RERANK_ENABLED
    # 判官不跑时**不要**放宽候选预算。`_collect` 的 max_items 同时控制 FTS limit、
    # 向量 limit 和最终截断，放宽后 RRF 的 top-N 可能与窄预算下不同（多召回的双通道
    # 命中会挤掉原本靠前的单通道命中）。预算收回 keep → 默认关时逐条等于改造前。
    budget = max_items if do_rerank else keep

    try:
        store = MemoryStore()
    except Exception:
        logger.debug("structured recall: store unavailable", exc_info=True)
        return empty

    try:
        general, companion = _collect_split(store, query, mode, budget)
        all_hits = general + companion
        if not all_hits:
            return empty
        if do_rerank:
            # fallback 逐域截断，不在并集上截——companion 模式下 general 占满额度时
            # 在并集上截会把 companion 整段砍掉，与改造前不符。
            all_hits = await rerank_and_cut(
                query, all_hits, fallback=general[:keep] + companion[:keep]
            )
            if not all_hits:
                return empty
        return _finalize(store, all_hits)
    except Exception:
        logger.debug("structured recall (async) failed", exc_info=True)
        return empty
    finally:
        try:
            store.close()
        except Exception:
            pass
