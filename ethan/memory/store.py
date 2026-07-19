"""SQLite storage for typed, source-backed memory records.

The structured tables live beside sqlite-vec's ``vec_items``/``vec_index`` in
per-profile ``memory.db``.  This module deliberately uses ordinary sqlite3 and
never loads or mutates the vector extension tables.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ethan.memory.records import (
    CandidateStatus,
    ConsolidationJob,
    DailySummary,
    JobStatus,
    MemoryCandidate,
    MemoryEvidence,
    MemoryRecord,
    MemoryStatus,
)

_SCHEMA_VERSION = "1"


class MemoryStore:
    """Canonical store for structured memories and their evidence."""

    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            from ethan.core.paths import user_vectors_db_path
            db_path = user_vectors_db_path()
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._fts_available = False

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            self._conn = conn
            self._init_schema()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "MemoryStore":
        self._get_conn()
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._get_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS structured_memory_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                memory_type TEXT NOT NULL,
                dimension TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                content TEXT NOT NULL,
                structured_data TEXT NOT NULL DEFAULT '{}',
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                memory_domain TEXT NOT NULL DEFAULT 'general',
                status TEXT NOT NULL,
                evidence_level TEXT NOT NULL,
                confidence REAL NOT NULL,
                importance REAL NOT NULL,
                sensitivity TEXT NOT NULL DEFAULT 'normal',
                valid_from REAL,
                valid_until REAL,
                source_session_id TEXT,
                source_message_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_recalled_at REAL,
                superseded_by TEXT,
                forgotten_at REAL,
                FOREIGN KEY (superseded_by) REFERENCES memories(id)
            );
            CREATE INDEX IF NOT EXISTS idx_memories_status_domain_type
                ON memories(status, memory_domain, memory_type);
            CREATE INDEX IF NOT EXISTS idx_memories_scope
                ON memories(scope_type, scope_id, status);
            CREATE INDEX IF NOT EXISTS idx_memories_key_scope
                ON memories(memory_key, scope_type, scope_id, memory_domain);
            CREATE INDEX IF NOT EXISTS idx_memories_validity
                ON memories(valid_until, status);
            CREATE INDEX IF NOT EXISTS idx_memories_updated
                ON memories(updated_at DESC);

            CREATE TABLE IF NOT EXISTS memory_evidence (
                id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                candidate_id TEXT,
                evidence_level TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                source_message_id TEXT,
                source_role TEXT NOT NULL,
                source_quote TEXT NOT NULL,
                quote_hash TEXT NOT NULL,
                observed_at REAL,
                extractor_version TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                UNIQUE(memory_id, source_session_id, source_message_id, quote_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_memory
                ON memory_evidence(memory_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_source
                ON memory_evidence(source_session_id, source_message_id);

            CREATE TABLE IF NOT EXISTS memory_candidates (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                memory_type TEXT NOT NULL,
                dimension TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                content TEXT NOT NULL,
                structured_data TEXT NOT NULL DEFAULT '{}',
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                memory_domain TEXT NOT NULL,
                evidence_level TEXT NOT NULL,
                confidence REAL NOT NULL,
                importance REAL NOT NULL,
                sensitivity TEXT NOT NULL,
                valid_from REAL,
                valid_until REAL,
                source_session_id TEXT NOT NULL,
                source_message_id TEXT,
                source_role TEXT NOT NULL,
                source_quote TEXT NOT NULL,
                extractor_name TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                extraction_job_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE,
                processing_status TEXT NOT NULL,
                processing_reason TEXT NOT NULL DEFAULT '',
                admitted_memory_id TEXT,
                created_at REAL NOT NULL,
                processed_at REAL,
                FOREIGN KEY (admitted_memory_id) REFERENCES memories(id)
            );
            CREATE INDEX IF NOT EXISTS idx_candidates_status
                ON memory_candidates(processing_status, created_at);
            CREATE INDEX IF NOT EXISTS idx_candidates_key_scope
                ON memory_candidates(memory_key, scope_type, scope_id, memory_domain);

            CREATE TABLE IF NOT EXISTS daily_summaries (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                local_date TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                memory_domain TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                structured_data TEXT NOT NULL DEFAULT '{}',
                source_from REAL,
                source_until REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(user_id, local_date, pipeline_version, memory_domain)
            );

            CREATE TABLE IF NOT EXISTS consolidation_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                job_type TEXT NOT NULL,
                job_key TEXT NOT NULL UNIQUE,
                pipeline_version TEXT NOT NULL,
                status TEXT NOT NULL,
                source_from REAL,
                source_until REAL,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                started_at REAL NOT NULL,
                completed_at REAL,
                error_message TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}'
            );
        """)
        conn.execute(
            "INSERT OR REPLACE INTO structured_memory_meta(key, value) VALUES ('schema_version', ?)",
            (_SCHEMA_VERSION,),
        )
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED,
                    content,
                    memory_key,
                    dimension,
                    searchable_data
                )
            """)
            self._fts_available = True
        except sqlite3.DatabaseError:
            self._fts_available = False
        conn.commit()

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _quote_hash(quote: str) -> str:
        return hashlib.sha256(quote.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _candidate_fingerprint(candidate: MemoryCandidate) -> str:
        raw = "\x1f".join([
            candidate.extractor_version,
            candidate.source_session_id,
            candidate.source_message_id,
            candidate.memory_key.lower(),
            candidate.scope_type,
            candidate.scope_id.lower(),
            candidate.memory_domain,
            MemoryStore._quote_hash(candidate.source_quote),
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _sync_fts(self, conn: sqlite3.Connection, record: MemoryRecord) -> None:
        if not self._fts_available:
            return
        conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (record.id,))
        if record.status in {MemoryStatus.ACTIVE.value, MemoryStatus.DISPUTED.value}:
            searchable = " ".join(self._flatten(record.structured_data))
            conn.execute(
                "INSERT INTO memory_fts(memory_id, content, memory_key, dimension, searchable_data) VALUES (?, ?, ?, ?, ?)",
                (record.id, record.content, record.memory_key, record.dimension, searchable),
            )

    @classmethod
    def _flatten(cls, value: Any) -> list[str]:
        if isinstance(value, dict):
            out: list[str] = []
            for key, item in value.items():
                out.append(str(key))
                out.extend(cls._flatten(item))
            return out
        if isinstance(value, list):
            out = []
            for item in value:
                out.extend(cls._flatten(item))
            return out
        if value is None:
            return []
        return [str(value)]

    def create_candidate_batch(self, candidates: list[MemoryCandidate]) -> list[str]:
        inserted: list[str] = []
        with self.transaction() as conn:
            for c in candidates:
                fingerprint = self._candidate_fingerprint(c)
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO memory_candidates(
                        id,user_id,memory_type,dimension,memory_key,content,structured_data,
                        scope_type,scope_id,memory_domain,evidence_level,confidence,importance,
                        sensitivity,valid_from,valid_until,source_session_id,source_message_id,
                        source_role,source_quote,extractor_name,extractor_version,extraction_job_key,
                        fingerprint,processing_status,processing_reason,admitted_memory_id,created_at,processed_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    c.id,c.user_id,c.memory_type,c.dimension,c.memory_key,c.content,self._json(c.structured_data),
                    c.scope_type,c.scope_id,c.memory_domain,c.evidence_level,c.confidence,c.importance,
                    c.sensitivity,c.valid_from,c.valid_until,c.source_session_id,c.source_message_id,
                    c.source_role,c.source_quote,c.extractor_name,c.extractor_version,c.extraction_job_key,
                    fingerprint,c.processing_status,c.processing_reason,c.admitted_memory_id,c.created_at,c.processed_at,
                ))
                if cursor.rowcount:
                    inserted.append(c.id)
        return inserted

    def list_pending_candidates(
        self, *, memory_key: str | None = None, scope_type: str | None = None,
        scope_id: str | None = None, memory_domain: str | None = None, limit: int = 200
    ) -> list[MemoryCandidate]:
        clauses = ["processing_status=?"]
        params: list[Any] = [CandidateStatus.PENDING.value]
        for column, value in (
            ("memory_key", memory_key), ("scope_type", scope_type),
            ("scope_id", scope_id), ("memory_domain", memory_domain),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        params.append(limit)
        rows = self._get_conn().execute(
            f"SELECT * FROM memory_candidates WHERE {' AND '.join(clauses)} ORDER BY created_at LIMIT ?",
            params,
        ).fetchall()
        return [self._candidate_from_row(r) for r in rows]

    def get_candidate(self, candidate_id: str) -> MemoryCandidate | None:
        row = self._get_conn().execute(
            "SELECT * FROM memory_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        return self._candidate_from_row(row) if row else None

    def create_memory_with_evidence(
        self, record: MemoryRecord, evidence: list[MemoryEvidence]
    ) -> str:
        if record.status == MemoryStatus.ACTIVE.value and not evidence:
            raise ValueError("active memory requires evidence")
        with self.transaction() as conn:
            if record.status == MemoryStatus.ACTIVE.value:
                current = conn.execute("""
                    SELECT id FROM memories WHERE memory_key=? AND scope_type=? AND scope_id=?
                      AND memory_domain=? AND status=?
                """, (
                    record.memory_key, record.scope_type, record.scope_id,
                    record.memory_domain, MemoryStatus.ACTIVE.value,
                )).fetchone()
                if current:
                    raise ValueError("active memory already exists for key and scope")
            self._insert_record(conn, record)
            for item in evidence:
                if item.memory_id != record.id:
                    raise ValueError("evidence memory_id does not match record")
                self._insert_evidence(conn, item)
            self._sync_fts(conn, record)
        return record.id

    def _insert_record(self, conn: sqlite3.Connection, r: MemoryRecord) -> None:
        conn.execute("""
            INSERT INTO memories(
                id,user_id,memory_type,dimension,memory_key,content,structured_data,scope_type,
                scope_id,memory_domain,status,evidence_level,confidence,importance,sensitivity,
                valid_from,valid_until,source_session_id,source_message_id,created_at,updated_at,
                last_recalled_at,superseded_by,forgotten_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r.id,r.user_id,r.memory_type,r.dimension,r.memory_key,r.content,self._json(r.structured_data),
            r.scope_type,r.scope_id,r.memory_domain,r.status,r.evidence_level,r.confidence,r.importance,
            r.sensitivity,r.valid_from,r.valid_until,r.source_session_id,r.source_message_id,
            r.created_at,r.updated_at,r.last_recalled_at,r.superseded_by,r.forgotten_at,
        ))

    def _insert_evidence(self, conn: sqlite3.Connection, e: MemoryEvidence) -> None:
        conn.execute("""
            INSERT OR IGNORE INTO memory_evidence(
                id,memory_id,candidate_id,evidence_level,source_session_id,source_message_id,
                source_role,source_quote,quote_hash,observed_at,extractor_version,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            e.id,e.memory_id,e.candidate_id,e.evidence_level,e.source_session_id,e.source_message_id,
            e.source_role,e.source_quote,self._quote_hash(e.source_quote),e.observed_at,
            e.extractor_version,e.created_at,
        ))

    def add_evidence(self, evidence: MemoryEvidence) -> None:
        with self.transaction() as conn:
            self._insert_evidence(conn, evidence)

    def find_current_by_key_scope(
        self, memory_key: str, scope_type: str, scope_id: str, memory_domain: str
    ) -> MemoryRecord | None:
        row = self._get_conn().execute("""
            SELECT * FROM memories WHERE memory_key=? AND scope_type=? AND scope_id=?
              AND memory_domain=? AND status=? ORDER BY updated_at DESC LIMIT 1
        """, (memory_key, scope_type, scope_id, memory_domain, MemoryStatus.ACTIVE.value)).fetchone()
        return self._record_from_row(row) if row else None

    def supersede_and_create(
        self, old_id: str, record: MemoryRecord, evidence: list[MemoryEvidence]
    ) -> str:
        if record.status != MemoryStatus.ACTIVE.value or not evidence:
            raise ValueError("replacement must be active and source-backed")
        with self.transaction() as conn:
            old_row = conn.execute("SELECT * FROM memories WHERE id=?", (old_id,)).fetchone()
            if not old_row:
                raise KeyError(old_id)
            old = self._record_from_row(old_row)
            identity = ("memory_key", "scope_type", "scope_id", "memory_domain")
            if any(getattr(old, k) != getattr(record, k) for k in identity):
                raise ValueError("supersession requires identical key, scope, and domain")
            conn.execute(
                "UPDATE memories SET status=?, updated_at=? WHERE id=?",
                (MemoryStatus.SUPERSEDED.value, time.time(), old_id),
            )
            old.status = MemoryStatus.SUPERSEDED.value
            self._sync_fts(conn, old)
            self._insert_record(conn, record)
            # Point the old record at its replacement only after the replacement row exists,
            # so the memories.superseded_by foreign key is satisfied.
            conn.execute(
                "UPDATE memories SET superseded_by=? WHERE id=?",
                (record.id, old_id),
            )
            for item in evidence:
                if item.memory_id != record.id:
                    raise ValueError("evidence memory_id does not match replacement")
                self._insert_evidence(conn, item)
            self._sync_fts(conn, record)
        return record.id

    def mark_disputed(self, memory_ids: list[str]) -> int:
        if not memory_ids:
            return 0
        with self.transaction() as conn:
            changed = 0
            for memory_id in memory_ids:
                row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
                if not row:
                    continue
                record = self._record_from_row(row)
                record.status = MemoryStatus.DISPUTED.value
                record.updated_at = time.time()
                conn.execute(
                    "UPDATE memories SET status=?, updated_at=? WHERE id=?",
                    (record.status, record.updated_at, memory_id),
                )
                self._sync_fts(conn, record)
                changed += 1
        return changed

    def list_memories(
        self, *, memory_type: str | None = None, dimension: str | None = None,
        scope_type: str | None = None, scope_id: str | None = None,
        memory_domain: str | None = None, status: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[MemoryRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("memory_type", memory_type), ("dimension", dimension),
            ("scope_type", scope_type), ("scope_id", scope_id),
            ("memory_domain", memory_domain), ("status", status),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self._get_conn().execute(
            f"SELECT * FROM memories {where} ORDER BY updated_at DESC, id LIMIT ? OFFSET ?", params
        ).fetchall()
        return [self._record_from_row(r) for r in rows]

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        row = self._get_conn().execute(
            "SELECT * FROM memories WHERE id=?", (memory_id,)
        ).fetchone()
        return self._record_from_row(row) if row else None

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        structured_data: dict[str, Any] | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        valid_from: float | None = None,
        valid_until: float | None = None,
        clear_valid_from: bool = False,
        clear_valid_until: bool = False,
    ) -> MemoryRecord:
        """Update user-editable fields and keep FTS in sync.

        Identity fields (type/key/scope/domain/status) are intentionally not
        editable in place: changing those would bypass the admission and
        supersession invariants.
        """
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                raise KeyError(memory_id)
            current = self._record_from_row(row)
            updated = MemoryRecord(
                id=current.id,
                user_id=current.user_id,
                memory_type=current.memory_type,
                dimension=current.dimension,
                memory_key=current.memory_key,
                content=content if content is not None else current.content,
                structured_data=structured_data if structured_data is not None else current.structured_data,
                scope_type=current.scope_type,
                scope_id=current.scope_id,
                memory_domain=current.memory_domain,
                status=current.status,
                evidence_level=current.evidence_level,
                confidence=confidence if confidence is not None else current.confidence,
                importance=importance if importance is not None else current.importance,
                sensitivity=current.sensitivity,
                valid_from=(None if clear_valid_from else valid_from) if (clear_valid_from or valid_from is not None) else current.valid_from,
                valid_until=(None if clear_valid_until else valid_until) if (clear_valid_until or valid_until is not None) else current.valid_until,
                source_session_id=current.source_session_id,
                source_message_id=current.source_message_id,
                created_at=current.created_at,
                updated_at=time.time(),
                last_recalled_at=current.last_recalled_at,
                superseded_by=current.superseded_by,
                forgotten_at=current.forgotten_at,
            )
            conn.execute(
                """UPDATE memories SET content=?, structured_data=?, confidence=?, importance=?,
                   valid_from=?, valid_until=?, updated_at=? WHERE id=?""",
                (
                    updated.content, self._json(updated.structured_data), updated.confidence,
                    updated.importance, updated.valid_from, updated.valid_until,
                    updated.updated_at, memory_id,
                ),
            )
            self._sync_fts(conn, updated)
        return updated

    def list_evidence(self, memory_id: str, *, redact_restricted: bool = False) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM memory_evidence WHERE memory_id=? ORDER BY created_at", (memory_id,)
        ).fetchall()
        result = [dict(r) for r in rows]
        if redact_restricted:
            record = self.get_memory(memory_id)
            if record and record.sensitivity == "restricted":
                for item in result:
                    item["source_quote"] = "[redacted]"
        return result

    def search_memories(
        self, query: str = "", *, memory_types: list[str] | None = None,
        memory_domain: str | None = None, statuses: list[str] | None = None,
        scope_pairs: list[tuple[str, str]] | None = None, limit: int = 20,
    ) -> list[MemoryRecord]:
        conn = self._get_conn()
        clauses: list[str] = []
        params: list[Any] = []
        if memory_types:
            clauses.append(f"m.memory_type IN ({','.join('?' * len(memory_types))})")
            params.extend(memory_types)
        if statuses:
            clauses.append(f"m.status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        if memory_domain is not None:
            clauses.append("m.memory_domain=?")
            params.append(memory_domain)
        if scope_pairs:
            pieces = []
            for scope_type, scope_id in scope_pairs:
                pieces.append("(m.scope_type=? AND m.scope_id=?)")
                params.extend([scope_type, scope_id])
            clauses.append(f"({' OR '.join(pieces)})")
        now = time.time()
        clauses.append("(m.valid_from IS NULL OR m.valid_from<=?)")
        clauses.append("(m.valid_until IS NULL OR m.valid_until>=?)")
        params.extend([now, now])
        where = " AND ".join(clauses)

        if query.strip() and self._fts_available:
            try:
                sql = f"""
                    SELECT m.* FROM memory_fts f JOIN memories m ON m.id=f.memory_id
                    WHERE memory_fts MATCH ? AND {where}
                    ORDER BY bm25(memory_fts), m.importance DESC, m.confidence DESC,
                             m.updated_at DESC, m.id LIMIT ?
                """
                rows = conn.execute(sql, [query.strip(), *params, limit]).fetchall()
                return [self._record_from_row(r) for r in rows]
            except sqlite3.DatabaseError:
                pass
        if query.strip():
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where += " AND (m.content LIKE ? ESCAPE '\\' OR m.memory_key LIKE ? ESCAPE '\\')"
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        rows = conn.execute(
            f"SELECT m.* FROM memories m WHERE {where} ORDER BY m.importance DESC, "
            "m.confidence DESC, m.updated_at DESC, m.id LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [self._record_from_row(r) for r in rows]

    def set_status(self, memory_id: str, status: str) -> None:
        status = MemoryStatus(status).value
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                raise KeyError(memory_id)
            record = self._record_from_row(row)
            if status == MemoryStatus.ACTIVE.value:
                evidence = conn.execute(
                    "SELECT 1 FROM memory_evidence WHERE memory_id=? LIMIT 1", (memory_id,)
                ).fetchone()
                if not evidence:
                    raise ValueError("active memory requires evidence")
            record.status = status
            record.updated_at = time.time()
            conn.execute(
                "UPDATE memories SET status=?, updated_at=? WHERE id=?",
                (status, record.updated_at, memory_id),
            )
            self._sync_fts(conn, record)

    def forget_memory(self, memory_id: str) -> None:
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                raise KeyError(memory_id)
            now = time.time()
            conn.execute("""
                UPDATE memories SET status=?, content='[forgotten]', structured_data='{}',
                    forgotten_at=?, updated_at=? WHERE id=?
            """, (MemoryStatus.FORGOTTEN.value, now, now, memory_id))
            conn.execute(
                "UPDATE memory_evidence SET source_quote='[forgotten]', quote_hash=? WHERE memory_id=?",
                (self._quote_hash("[forgotten]"), memory_id),
            )
            if self._fts_available:
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))

    def delete_memory(self, memory_id: str) -> bool:
        with self.transaction() as conn:
            if self._fts_available:
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            cursor = conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        return cursor.rowcount > 0

    def touch_recalled(self, memory_ids: list[str]) -> None:
        if not memory_ids:
            return
        placeholders = ",".join("?" for _ in memory_ids)
        conn = self._get_conn()
        conn.execute(
            f"UPDATE memories SET last_recalled_at=? WHERE id IN ({placeholders})",
            (time.time(), *memory_ids),
        )
        conn.commit()

    def upsert_daily_summary(self, summary: DailySummary) -> str:
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO daily_summaries(
                    id,user_id,local_date,pipeline_version,memory_domain,summary_text,
                    structured_data,source_from,source_until,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id,local_date,pipeline_version,memory_domain) DO UPDATE SET
                    summary_text=excluded.summary_text,
                    structured_data=excluded.structured_data,
                    source_from=excluded.source_from,
                    source_until=excluded.source_until,
                    updated_at=excluded.updated_at
            """, (
                summary.id,summary.user_id,summary.local_date,summary.pipeline_version,
                summary.memory_domain,summary.summary_text,self._json(summary.structured_data),
                summary.source_from,summary.source_until,summary.created_at,summary.updated_at,
            ))
            row = conn.execute("""
                SELECT id FROM daily_summaries WHERE user_id=? AND local_date=?
                  AND pipeline_version=? AND memory_domain=?
            """, (summary.user_id, summary.local_date, summary.pipeline_version, summary.memory_domain)).fetchone()
        return row["id"]

    def list_daily_summaries(
        self, *, memory_domain: str | None = None, limit: int = 30, offset: int = 0
    ) -> list[dict[str, Any]]:
        if memory_domain:
            rows = self._get_conn().execute("""
                SELECT * FROM daily_summaries WHERE memory_domain=?
                ORDER BY local_date DESC LIMIT ? OFFSET ?
            """, (memory_domain, limit, offset)).fetchall()
        else:
            rows = self._get_conn().execute("""
                SELECT * FROM daily_summaries ORDER BY local_date DESC, memory_domain
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["structured_data"] = json.loads(item["structured_data"] or "{}")
            result.append(item)
        return result

    def get_daily_summary(
        self, local_date: str, *, memory_domain: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self.list_daily_summaries(memory_domain=memory_domain, limit=366)
        return [row for row in rows if row["local_date"] == local_date]

    def claim_job(self, job: ConsolidationJob) -> bool:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT status, attempt_count FROM consolidation_jobs WHERE job_key=?", (job.job_key,)
            ).fetchone()
            if row and row["status"] in {JobStatus.COMPLETED.value, JobStatus.RUNNING.value}:
                return False
            if row:
                conn.execute("""
                    UPDATE consolidation_jobs SET status=?, attempt_count=?, started_at=?,
                        completed_at=NULL,error_message='',source_from=?,source_until=? WHERE job_key=?
                """, (
                    JobStatus.RUNNING.value,row["attempt_count"]+1,time.time(),
                    job.source_from,job.source_until,job.job_key,
                ))
            else:
                conn.execute("""
                    INSERT INTO consolidation_jobs(
                        id,user_id,job_type,job_key,pipeline_version,status,source_from,source_until,
                        attempt_count,started_at,completed_at,error_message,result_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    job.id,job.user_id,job.job_type,job.job_key,job.pipeline_version,
                    JobStatus.RUNNING.value,job.source_from,job.source_until,job.attempt_count,
                    job.started_at,None,"",self._json(job.result),
                ))
        return True

    def complete_job(self, job_key: str, result: dict[str, Any]) -> None:
        conn = self._get_conn()
        cursor = conn.execute("""
            UPDATE consolidation_jobs SET status=?,completed_at=?,error_message='',result_json=?
            WHERE job_key=?
        """, (JobStatus.COMPLETED.value,time.time(),self._json(result),job_key))
        conn.commit()
        if not cursor.rowcount:
            raise KeyError(job_key)

    def fail_job(self, job_key: str, error_message: str) -> None:
        conn = self._get_conn()
        cursor = conn.execute("""
            UPDATE consolidation_jobs SET status=?,completed_at=?,error_message=? WHERE job_key=?
        """, (JobStatus.FAILED.value,time.time(),error_message[:1000],job_key))
        conn.commit()
        if not cursor.rowcount:
            raise KeyError(job_key)

    def last_completed_incremental_boundary(self, session_id: str) -> float | None:
        row = self._get_conn().execute("""
            SELECT source_until FROM consolidation_jobs
            WHERE job_type='incremental_extraction' AND status='completed'
              AND job_key LIKE ? ORDER BY source_until DESC LIMIT 1
        """, (f"incremental:%:{session_id}:%",)).fetchone()
        return row["source_until"] if row else None

    def mark_candidate_processed(
        self, candidate_id: str, status: str, reason: str = "", memory_id: str | None = None
    ) -> None:
        status = CandidateStatus(status).value
        conn = self._get_conn()
        cursor = conn.execute("""
            UPDATE memory_candidates SET processing_status=?,processing_reason=?,
                admitted_memory_id=?,processed_at=? WHERE id=?
        """, (status,reason[:1000],memory_id,time.time(),candidate_id))
        conn.commit()
        if not cursor.rowcount:
            raise KeyError(candidate_id)

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],user_id=row["user_id"],memory_type=row["memory_type"],
            dimension=row["dimension"],memory_key=row["memory_key"],content=row["content"],
            structured_data=json.loads(row["structured_data"] or "{}"),scope_type=row["scope_type"],
            scope_id=row["scope_id"],memory_domain=row["memory_domain"],status=row["status"],
            evidence_level=row["evidence_level"],confidence=row["confidence"],importance=row["importance"],
            sensitivity=row["sensitivity"],valid_from=row["valid_from"],valid_until=row["valid_until"],
            source_session_id=row["source_session_id"] or "",source_message_id=row["source_message_id"] or "",
            created_at=row["created_at"],updated_at=row["updated_at"],last_recalled_at=row["last_recalled_at"],
            superseded_by=row["superseded_by"],forgotten_at=row["forgotten_at"],
        )

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> MemoryCandidate:
        return MemoryCandidate(
            id=row["id"],user_id=row["user_id"],memory_type=row["memory_type"],
            dimension=row["dimension"],memory_key=row["memory_key"],content=row["content"],
            structured_data=json.loads(row["structured_data"] or "{}"),scope_type=row["scope_type"],
            scope_id=row["scope_id"],memory_domain=row["memory_domain"],evidence_level=row["evidence_level"],
            confidence=row["confidence"],importance=row["importance"],sensitivity=row["sensitivity"],
            valid_from=row["valid_from"],valid_until=row["valid_until"],
            source_session_id=row["source_session_id"],source_message_id=row["source_message_id"] or "",
            source_role=row["source_role"],source_quote=row["source_quote"],
            extractor_name=row["extractor_name"],extractor_version=row["extractor_version"],
            extraction_job_key=row["extraction_job_key"],processing_status=row["processing_status"],
            processing_reason=row["processing_reason"],admitted_memory_id=row["admitted_memory_id"],
            created_at=row["created_at"],processed_at=row["processed_at"],
        )
