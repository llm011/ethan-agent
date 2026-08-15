"""memories 语义向量索引 — 准入配对建议与混合召回的底层。

设计红线（融合方案）：embedding 只做"配对建议"，merge/supersede 决策规则
保持确定性；配对结果全部写入 candidate.processing_reason 可审计。

索引条目：type="memory"，id 与 memories.id 一致，metadata 带
scope/domain/dimension 供过滤。同步策略：
- 准入转换（create/supersede）时由 AdmissionPolicy 精确同步
- 夜间做梦前 reindex_all 全量重建自愈（覆盖迁移/手工编辑/forget 漂移）

BGE-small-zh 归一化 512 维向量，cos = 1 - L2²/2。
同义改写 L2 通常 0.56~0.81（见 daily_consolidation 的标定注释）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 语义配对阈值：
# - merge（observed/inferred 补证据）用宽松阈值，误判代价低（多一条证据行）
# - supersede（explicit/corrected 替换）在同模块校验时要求同 dimension，
#   阈值即 MERGE_L2_THRESHOLD（配对发现），确定性规则在 admission 里
MERGE_L2_THRESHOLD = float(os.environ.get("ETHAN_MEMORY_PAIR_L2", "0.7"))

# 召回向量通道的截断：L2 > 阈值视为无关，在 recall_neighbors 里丢弃。
#
# 默认 1.3（曾为 1.1）。实测 1200 条 golden recall 集（见
# tests/memory_eval/sweep_threshold.py 的阈值扫描）：1.1 时命中率 89.0%，
# 1.3 时 100%，且泄漏率全程 0%——leak 由域隔离（companion 域在非 companion
# 模式不召回）+ restricted 不注入保证，与阈值无关，故阈值可安全放宽。
#
# 失败根因：同维度前缀的并列事实（"我是谁，做什么的"应召回 name+occupation+
# expertise 三条），BGE 对其中 2 条打分落在 1.15~1.20，1.1 截断把它们丢了。
# 1.3 是达到 100% 命中的最低工作点（留余量，不取 1.4 以免无谓放大候选）。
# 召回条目数实测 1.1→1.3 仅从均值 1.41 升到 1.60、上限不变（跟 seed 数走），
# 不产生噪声泛滥。
RECALL_L2_MAX = float(os.environ.get("ETHAN_MEMORY_RECALL_L2", "1.3"))


def _vector_store(db_path: Path | None = None):
    from ethan.memory.vector_store import VectorStore

    if db_path is None:
        # 必须用 user_vectors_db_path()，与 MemoryStore 同库（db/memory.db）；
        # 否则准入配对/召回读到的向量索引与 memories 表不在同一文件。
        from ethan.core.paths import user_vectors_db_path
        db_path = user_vectors_db_path()
    return VectorStore(db_path=db_path)


def index_memory(record: Any, *, db_path: Path | None = None) -> None:
    """把 active memory 写入向量索引（embed_sync 同步编码，BGE ~10ms）。

    失败不抛——索引缺失只会降低语义配对/召回质量，不能阻塞写入链路。
    """
    from ethan.memory.records import MemoryStatus

    if record.status != MemoryStatus.ACTIVE.value:
        return
    try:
        from ethan.memory.embeddings import embed_sync

        vec = _vector_store(db_path)
        try:
            vec.add(
                id=record.id,
                text=record.content,
                embedding=embed_sync(record.content),
                metadata={
                    "type": "memory",
                    "scope_type": record.scope_type,
                    "scope_id": record.scope_id,
                    "memory_domain": record.memory_domain,
                    "memory_role": record.memory_role,
                    "dimension": record.dimension,
                    "memory_type": record.memory_type,
                },
            )
        finally:
            vec.close()
    except Exception:
        logger.warning("[MemoryVectors] index failed for %s", record.id, exc_info=True)


def remove_memory_index(memory_id: str, *, db_path: Path | None = None) -> None:
    try:
        vec = _vector_store(db_path)
        try:
            vec.remove(memory_id)
        finally:
            vec.close()
    except Exception:
        logger.warning("[MemoryVectors] remove failed for %s", memory_id, exc_info=True)


def semantic_neighbors(
    *,
    content: str,
    scope_type: str | None = None,
    scope_id: str | None = None,
    memory_domain: str,
    db_path: Path | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """查最近邻记忆向量，返回 [{id, distance, text, metadata}]。

    供准入配对建议用。scope_type/scope_id 传 None 表示不按该维度过滤
    （跨 scope 配对：先全量取近邻，由调用方按护栏筛 scope）。任何失败返回
    空列表（降级为纯精确 key 匹配）。
    """
    try:
        from ethan.memory.embeddings import embed_sync

        metadata_filter: dict[str, Any] = {
            "type": "memory",
            "memory_domain": memory_domain,
        }
        if scope_type is not None:
            metadata_filter["scope_type"] = scope_type
        if scope_id is not None:
            metadata_filter["scope_id"] = scope_id
        vec = _vector_store(db_path)
        try:
            return vec.search(
                query_embedding=embed_sync(content),
                limit=limit,
                filter=metadata_filter,
                update_access=False,
            )
        finally:
            vec.close()
    except Exception:
        logger.debug("[MemoryVectors] neighbor search failed", exc_info=True)
        return []


def recall_neighbors(
    *,
    query: str,
    memory_domain: str,
    db_path: Path | None = None,
    limit: int = 16,
    memory_role: str | None = None,
) -> list[tuple[str, float]]:
    """召回向量通道：返回 [(memory_id, l2_distance)]，截断到 RECALL_L2_MAX。

    memory_role 非空时按 role 过滤（召回层 intent→role 映射），None 则不过滤
    （unknown intent 走全量）。失败返回空列表（召回降级为纯 FTS/LIKE）。
    """
    try:
        from ethan.memory.embeddings import embed_sync

        vec = _vector_store(db_path)
        try:
            metadata_filter: dict[str, Any] = {
                "type": "memory",
                "memory_domain": memory_domain,
            }
            if memory_role is not None:
                metadata_filter["memory_role"] = memory_role
            hits = vec.search(
                query_embedding=embed_sync(query),
                limit=limit,
                filter=metadata_filter,
                update_access=False,
            )
            return [(h["id"], h["distance"]) for h in hits if h["distance"] <= RECALL_L2_MAX]
        finally:
            vec.close()
    except Exception:
        logger.debug("[MemoryVectors] recall search failed", exc_info=True)
        return []


def reindex_all(*, db_path: Path | None = None) -> int:
    """全量重建 memory 向量索引（夜间自愈）。返回重建条数。"""
    from ethan.memory.embeddings import embed_sync
    from ethan.memory.records import MemoryStatus
    from ethan.memory.store import MemoryStore

    store = MemoryStore(db_path=db_path)
    vec = _vector_store(db_path)
    rebuilt = 0
    try:
        vec.delete_by_type("memory")
        for record in store.list_memories(status=MemoryStatus.ACTIVE.value, limit=10000):
            try:
                vec.add(
                    id=record.id,
                    text=record.content,
                    embedding=embed_sync(record.content),
                    metadata={
                        "type": "memory",
                        "scope_type": record.scope_type,
                        "scope_id": record.scope_id,
                        "memory_domain": record.memory_domain,
                        "memory_role": record.memory_role,
                        "dimension": record.dimension,
                        "memory_type": record.memory_type,
                    },
                )
                rebuilt += 1
            except Exception:
                logger.warning("[MemoryVectors] reindex failed for %s", record.id, exc_info=True)
    finally:
        vec.close()
        store.close()
    logger.info("[MemoryVectors] reindexed %d active memories", rebuilt)
    return rebuilt
