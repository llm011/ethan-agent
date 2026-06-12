"""sqlite-vec backed vector store for semantic search.

Stores float32 embeddings alongside JSON metadata.  One shared DB lives at
~/.ethan/memory/vectors.db.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any

import sqlite_vec

from ethan.memory.embeddings import EMBEDDING_DIM, embed_sync

_DB_PATH = Path.home() / ".ethan" / "memory" / "vectors.db"


class VectorStore:
    """Persistent vector store backed by sqlite-vec."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ── Connection management ──────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
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
                id       TEXT PRIMARY KEY,
                text     TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)

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

        conn.execute(
            "INSERT OR REPLACE INTO vec_items (id, text, metadata) VALUES (?, ?, ?)",
            (id, text, meta_json),
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

    # ── Read ───────────────────────────────────────────────────────────────

    def search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to *limit* closest items (cosine distance via sqlite-vec).

        *filter* is matched against the stored JSON metadata.  Only simple
        equality filters on top-level keys are supported (post-filter step).
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
            if len(results) >= limit:
                break

        return results

    def count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()
        return row[0] if row else 0
