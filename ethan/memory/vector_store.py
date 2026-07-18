"""sqlite-vec backed vector store for semantic search.

Stores float32 embeddings alongside JSON metadata.  Per-user DB lives at
~/.ethan/memory/memory.db (旧名 vectors.db，自动迁移)。
"""
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

import sqlite_vec

from ethan.memory.embeddings import EMBEDDING_DIM

logger = logging.getLogger(__name__)

# LRU 过期：3 个月未被访问的条目在 cleanup 时清除
EXPIRE_SECONDS = 90 * 86400  # 90 天

# 永久保留的类型——不参与 LRU 清理。
# 第五层定位是"永久记忆"：insight_*（repetition/error/success_path）是"做梦"沉淀下来的洞察，
# fact_sync 是 facts.json/playbook.json 的镜像（每次"做梦"前全量重建）。
# 两类均豁免 LRU。cleanup_expired 仅作为安全阀清理未知类型的孤儿条目。
PERMANENT_TYPES = frozenset({"repetition", "error", "success_path", "fact_sync"})


class VectorStore:
    """Persistent vector store backed by sqlite-vec."""

    def __init__(self, db_path: Path | None = None):
        # 每次按当前 user contextvar 求值，避免模块级缓存击穿 per-user 隔离
        if db_path is None:
            from ethan.core.paths import user_vectors_db_path
            db_path = user_vectors_db_path()
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ── Connection management ──────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # timeout/busy_timeout/WAL 对齐 MemoryStore：两者写同一 db 文件，
            # 共享 WAL；busy_timeout 是 per-connection，VectorStore 也要设，
            # 否则夜间 reindex 与召回/心跳并发时会踩 "database is locked"。
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            self._conn = conn
            self._init_schema()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Schema ─────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        conn = self._conn
        assert conn is not None

        # Metadata table (source of truth for item data)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vec_items (
                id            TEXT PRIMARY KEY,
                text          TEXT NOT NULL,
                metadata      TEXT NOT NULL DEFAULT '{}',
                last_accessed REAL NOT NULL DEFAULT 0
            )
        """)

        # 迁移：旧表没有 last_accessed 列
        cols = {row[1] for row in conn.execute("PRAGMA table_info(vec_items)").fetchall()}
        if "last_accessed" not in cols:
            conn.execute("ALTER TABLE vec_items ADD COLUMN last_accessed REAL NOT NULL DEFAULT 0")
            # 旧数据用 created_at（从 metadata 取）或当前时间兜底
            conn.execute("""
                UPDATE vec_items SET last_accessed = COALESCE(
                    json_extract(metadata, '$.created_at'),
                    0
                )
            """)
            logger.info("[VectorStore] Migrated vec_items: added last_accessed column")

        # Virtual table for ANN search
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_index
            USING vec0(
                id      TEXT PRIMARY KEY,
                embedding FLOAT[{EMBEDDING_DIM}]
            )
        """)

        conn.commit()

    # ── Write ──────────────────────────────────────────────────────────────

    def add(
        self,
        id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or replace a vector + metadata entry."""
        conn = self._get_conn()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        now = time.time()

        conn.execute(
            "INSERT OR REPLACE INTO vec_items (id, text, metadata, last_accessed) VALUES (?, ?, ?, ?)",
            (id, text, meta_json, now),
        )

        # sqlite-vec expects bytes
        import sqlite_vec as sv
        emb_bytes = sv.serialize_float32(embedding)

        conn.execute(
            "INSERT OR REPLACE INTO vec_index (id, embedding) VALUES (?, ?)",
            (id, emb_bytes),
        )
        conn.commit()

    def remove(self, id: str) -> None:
        """Delete a vector entry by id."""
        conn = self._get_conn()
        conn.execute("DELETE FROM vec_items WHERE id = ?", (id,))
        conn.execute("DELETE FROM vec_index WHERE id = ?", (id,))
        conn.commit()

    def update_metadata(self, id: str, metadata: dict[str, Any]) -> bool:
        """只更新 metadata JSON（不动 embedding/vec_index）。

        用于 daily_consolidation 标记 reflected=True 等场景——避免对 vec_index
        虚拟表做 INSERT OR REPLACE（sqlite-vec 的 vec0 不支持 REPLACE 语义）。
        返回是否找到并更新了条目。
        """
        conn = self._get_conn()
        meta_json = json.dumps(metadata, ensure_ascii=False)
        cursor = conn.execute(
            "UPDATE vec_items SET metadata = ? WHERE id = ?",
            (meta_json, id),
        )
        conn.commit()
        return cursor.rowcount > 0

    # ── Read ───────────────────────────────────────────────────────────────

    def search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        filter: dict[str, Any] | None = None,
        update_access: bool = True,
    ) -> list[dict[str, Any]]:
        """Return up to *limit* closest items (L2 distance via sqlite-vec).

        *filter* is matched against the stored JSON metadata.  Only simple
        equality filters on top-level keys are supported (post-filter step).

        *update_access*: 命中时更新 last_accessed（LRU 依据）。写入去重等
        场景可设为 False 避免误刷新。
        """
        import sqlite_vec as sv

        conn = self._get_conn()
        emb_bytes = sv.serialize_float32(query_embedding)

        # Fetch more candidates than needed when filtering so we can post-filter
        fetch_limit = limit * 10 if filter else limit

        rows = conn.execute(
            """
            SELECT vi.id, vi.distance,
                   it.text, it.metadata
            FROM vec_index vi
            JOIN vec_items it ON it.id = vi.id
            WHERE vi.embedding MATCH ?
              AND vi.k = ?
            ORDER BY vi.distance
            """,
            (emb_bytes, fetch_limit),
        ).fetchall()

        results: list[dict[str, Any]] = []
        hit_ids: list[str] = []
        for row in rows:
            meta = json.loads(row["metadata"])
            if filter:
                if not all(meta.get(k) == v for k, v in filter.items()):
                    continue
            results.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "distance": row["distance"],
                    "metadata": meta,
                }
            )
            hit_ids.append(row["id"])
            if len(results) >= limit:
                break

        # LRU：更新命中条目的 last_accessed
        if update_access and hit_ids:
            now = time.time()
            placeholders = ",".join("?" * len(hit_ids))
            conn.execute(
                f"UPDATE vec_items SET last_accessed = ? WHERE id IN ({placeholders})",
                (now, *hit_ids),
            )
            conn.commit()

        return results

    def cleanup_expired(self, expire_seconds: int = EXPIRE_SECONDS) -> int:
        """删除超过 expire_seconds 未访问的**未知类型**孤儿条目，返回删除数量。

        第五层是"永久记忆"，insight_*（repetition/error/success_path）和 fact_sync
        两类已知类型均豁免清理。本方法仅作为安全阀，清理类型不在 PERMANENT_TYPES 中
        的孤儿条目，防止历史脏数据/未来未知类型堆积。
        """
        conn = self._get_conn()
        cutoff = time.time() - expire_seconds

        # 先查出要删的 id（用于删 vec_index）
        # 只删类型不在 PERMANENT_TYPES 中的孤儿条目
        not_in = ",".join("?" * len(PERMANENT_TYPES))
        expired_ids = [
            row[0] for row in
            conn.execute(
                f"""SELECT id FROM vec_items
                   WHERE last_accessed < ?
                     AND json_extract(metadata, '$.type') NOT IN ({not_in})""",
                (cutoff, *PERMANENT_TYPES),
            ).fetchall()
        ]
        if not expired_ids:
            return 0

        placeholders = ",".join("?" * len(expired_ids))
        conn.execute(f"DELETE FROM vec_items WHERE id IN ({placeholders})", expired_ids)
        conn.execute(f"DELETE FROM vec_index WHERE id IN ({placeholders})", expired_ids)
        conn.commit()

        logger.info("[VectorStore] Cleaned up %d orphan entries (older than %ds)", len(expired_ids), expire_seconds)
        return len(expired_ids)

    def count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()
        return row[0] if row else 0

    # ── Metadata-based queries（公开 API，替代外部直接访问 _get_conn） ──────

    def delete_by_type(self, type: str) -> int:
        """删除 metadata.type == type 的所有条目。返回删除数量。

        用于 daily_consolidation 的 fact_sync 全量重建：先删旧的同 type 条目再写入。
        """
        conn = self._get_conn()
        ids = [
            row[0] for row in
            conn.execute(
                "SELECT id FROM vec_items WHERE json_extract(metadata, '$.type') = ?",
                (type,),
            ).fetchall()
        ]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM vec_items WHERE id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM vec_index WHERE id IN ({placeholders})", ids)
        conn.commit()
        return len(ids)

    def count_items(self, exclude_types: list[str] | None = None) -> int:
        """计数条目，可排除指定 type（如排除 fact_sync 镜像条目）。"""
        conn = self._get_conn()
        if not exclude_types:
            return conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()[0]
        placeholders = ",".join("?" * len(exclude_types))
        return conn.execute(
            f"""SELECT COUNT(*) FROM vec_items
               WHERE json_extract(metadata, '$.type') NOT IN ({placeholders})""",
            exclude_types,
        ).fetchone()[0]

    def list_items(
        self,
        exclude_types: list[str] | None = None,
        date: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """分页列出条目（按 rowid 倒序），可按 type 排除、按 metadata.date 过滤。

        用于 daily_consolidation 的 get_all_memories / get_memories_by_date。
        """
        conn = self._get_conn()
        where = []
        params: list = []
        if exclude_types:
            placeholders = ",".join("?" * len(exclude_types))
            where.append(f"json_extract(metadata, '$.type') NOT IN ({placeholders})")
            params.extend(exclude_types)
        if date:
            where.append("json_extract(metadata, '$.date') = ?")
            params.append(date)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"""SELECT id, text, metadata FROM vec_items{where_sql}
               ORDER BY rowid DESC LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        items = []
        for row in rows:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            items.append({"id": row["id"], "text": row["text"], "metadata": meta})
        return items
