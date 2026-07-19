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

# 召回向量通道的截断：L2 > 1.1 视为完全无关（标定同 daily_consolidation）
RECALL_L2_MAX = float(os.environ.get("ETHAN_MEMORY_RECALL_L2", "1.1"))


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
    scope_type: str,
    scope_id: str,
    memory_domain: str,
    db_path: Path | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """查同 scope+domain 的最近邻记忆向量，返回 [{id, distance, text, metadata}]。

    供准入配对建议用。任何失败返回空列表（降级为纯精确 key 匹配）。
    """
    try:
        from ethan.memory.embeddings import embed_sync

        vec = _vector_store(db_path)
        try:
            return vec.search(
                query_embedding=embed_sync(content),
                limit=limit,
                filter={
                    "type": "memory",
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "memory_domain": memory_domain,
                },
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
) -> list[tuple[str, float]]:
    """召回向量通道：返回 [(memory_id, l2_distance)]，截断到 RECALL_L2_MAX。

    失败返回空列表（召回降级为纯 FTS/LIKE）。
    """
    try:
        from ethan.memory.embeddings import embed_sync

        vec = _vector_store(db_path)
        try:
            hits = vec.search(
                query_embedding=embed_sync(query),
                limit=limit,
                filter={"type": "memory", "memory_domain": memory_domain},
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
