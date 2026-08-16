"""SQLite storage for typed, source-backed memory records.

The structured tables live beside sqlite-vec's ``vec_items``/``vec_index`` in
per-profile ``memory.db``.  This module deliberately uses ordinary sqlite3 and
never loads or mutates the vector extension tables.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
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

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "4"


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

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # busy_timeout 对齐 SessionStore（30s）：三者写同一 sessions.db，
            # DELETE 模式下写会阻塞读，_maybe_consolidate / collect_signals
            # 与召回/心跳并发时 5s 不够。
            conn = sqlite3.connect(str(self._db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
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
                memory_role TEXT NOT NULL DEFAULT 'task_context',
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
                dormant_at REAL,
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
            -- idx_memories_role_status 在下方 v3 migration 补列后建，不在这里——
            -- 旧库此列尚不存在，executescript 会因引用未定义列整体回滚。

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

        # schema v3: 加 memory_role 列（召回层 intent→role 过滤的分类轴）。
        # 必须在 FTS reindex 之前跑——_reindex_fts 里 _record_from_row 会读 memory_role，
        # 旧库若无此列会 OperationalError。CREATE TABLE IF NOT EXISTS 对已存在的表是
        # no-op，旧库靠 ALTER TABLE 补列；PRAGMA table_info 检测列是否已存在避免重复
        # ALTER 报错。补列后按 dimension 前缀回填存量记忆的 role，让旧库也能参与
        # role 过滤；新记忆在 records.__post_init__ 里已推断好。
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        # 守卫：用独立的 'v3_migrated' key 判断回填是否完成。schema_version 在上方
        # 已被无条件写为 "3"，不能用来判断回填状态——若 ALTER 成功但回填崩溃，
        # schema_version 已是 "3"、列已存在，下次启动会跳过回填。v3_migrated 只在
        # 回填全部成功后写入，保证中途崩溃时下次启动能重试。
        v3_done = conn.execute(
            "SELECT value FROM structured_memory_meta WHERE key='v3_migrated'"
        ).fetchone()
        need_v3_migrate = (
            "memory_role" not in existing_cols
            or v3_done is None
        )
        if need_v3_migrate:
            if "memory_role" not in existing_cols:
                conn.execute(
                    "ALTER TABLE memories ADD COLUMN memory_role TEXT NOT NULL DEFAULT 'task_context'"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_role_status "
                "ON memories(memory_role, status)"
            )
            # 回填：role 仍为默认 task_context 但 dimension 前缀指向其他类的行。
            # dimension 一级前缀即 role，逐前缀批量 UPDATE。companion 域由 domain 隔离，
            # 不进 role 体系，其 dimension 前缀 companion 落到 task_context 兜底无妨。
            #
            # 覆盖所有 MEMORY_ROLES 中定义的前缀（identity/activity/decision/preference/
            # methodology/skill_experience/relationship），保证新旧记忆 role 一致。
            # skill/relationship 前缀的记忆若不回填会保持 task_context，导致 emotion
            # intent（role_filter=task_context）错误召回这些 GENERAL 域的工作记忆。
            #
            # 兼容：早期 v3 回填用的是 identity_fact/decision_record/preference_rule 等
            # 旧 role 名，后改为与 dimension 前缀对齐的 identity/decision/preference。这里
            # 先把旧名重置成 task_context，再按前缀统一回填，保证升级到新命名口径。
            conn.execute(
                "UPDATE memories SET memory_role='task_context' WHERE memory_role IN "
                "('identity_fact','decision_record','preference_rule')"
            )
            for prefix in (
                "identity", "activity", "decision", "preference",
                "methodology", "skill_experience", "relationship",
            ):
                conn.execute(
                    "UPDATE memories SET memory_role=? WHERE memory_role='task_context' "
                    "AND lower(dimension) LIKE ?",
                    (prefix, f"{prefix}%"),
                )
            conn.execute(
                "INSERT OR REPLACE INTO structured_memory_meta(key, value) "
                "VALUES ('v3_migrated', '1')"
            )

        # schema v4: 加 dormant_at 列（记忆休眠归档时间戳，遗忘/衰减功能）。
        # 与 v3 同理放在 FTS reindex 之前；索引必须在 ALTER 补列之后建，不能进
        # executescript——旧库此列尚不存在，executescript 会因引用未定义列整体回滚。
        # 无需回填——旧行 NULL 即"从未休眠"。守卫只看列存在性；仍写 v4_migrated
        # meta key 保持与 v3 相同的防御模式（本迁移无回填步骤，key 用于审计）。
        if "dormant_at" not in existing_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN dormant_at REAL")
            logger.info("schema v4: added memories.dormant_at")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_dormant "
            "ON memories(status, dormant_at)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO structured_memory_meta(key, value) "
            "VALUES ('v4_migrated', '1')"
        )

        try:
            # schema v2: 修中文词法通道。v1 用默认 unicode61 tokenizer + 原文索引，
            # CJK 整段是单个 token，FTS5 是 token 相等匹配不做子串 → 中文 query 全 0
            # 命中，词法通道形同虚设，召回全压在向量一路。
            #
            # 探针（probe_lexical.py）实测四种方案：trigram + OR 三字仍是 0 命中；
            # 唯一有效的是 **unicode61 + 二字索引 + OR 二字查询**（59.2% 精度 / 24%
            # case 覆盖）。所以这里保持默认 unicode61 tokenizer，但在写入时把
            # content/memory_key/searchable_data 都转成 bigram 串（CJK 切二字、ASCII
            # 词整取），查询侧同样用 bigram OR。token 相等匹配于是能在 bigram 粒度
            # 命中：「用户偏好用中文交流」→ 索引含「用户」「户偏」「偏好」…，查询
            # 「中文」→ OR「中文」，命中。
            #
            # FTS5 不支持 ALTER，只能 DROP + 重建；数据在 memories 表，重建无损。
            fts_ver = conn.execute(
                "SELECT value FROM structured_memory_meta WHERE key='fts_version'"
            ).fetchone()
            need_reindex = fts_ver is None or fts_ver[0] != "2"
            if need_reindex:
                conn.execute("DROP TABLE IF EXISTS memory_fts")
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
            if need_reindex:
                # DROP+重建后 FTS 表空了，旧库的 active/disputed 记忆不会自动回流——
                # _sync_fts 只在写入时触发。这里把现存记忆重建索引，否则升级后词法
                # 通道会在首次写入前持续 0 命中。
                #
                # 迁移**必须原子**：fts_version 等 reindex 全部成功后才写。若先写
                # fts_version=2 再 reindex，_reindex_fts 因某行损坏的 structured_data
                # 抛异常（见下方 except）时 meta 已标记 v2、索引却半残，下次启动
                # need_reindex 为 False，词法通道永久降级。后置写入保证失败时旧版本
                # 仍在 meta，下次启动能重试。
                self._reindex_fts(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO structured_memory_meta(key, value) "
                    "VALUES ('fts_version', '2')"
                )
        except Exception:
            # 不只 DatabaseError：_reindex_fts 里 _record_from_row 的 json.loads 可能
            # 因某行损坏的 structured_data 抛 JSONDecodeError（非 sqlite 异常）。
            # 任何异常都置 FTS 不可用，回退 LIKE 通道；fts_version 保持旧值（后置写入
            # 保证的），下次启动 need_reindex 仍为 True，能重试，不会永久降级。
            self._fts_available = False
            logger.warning("memory FTS 初始化失败，回退 LIKE 通道", exc_info=True)
        conn.commit()

    def _reindex_fts(self, conn: sqlite3.Connection) -> None:
        """从 memories 表把所有 active/disputed 记忆重建进 memory_fts。

        只在 schema v2 升级时调一次。逐行取 record 再走 _sync_fts，复用 bigram
        索引逻辑，保证迁移后的索引与正常运行时一致。
        """
        if not self._fts_available:
            return
        rows = conn.execute(
            "SELECT * FROM memories WHERE status IN (?, ?)",
            (MemoryStatus.ACTIVE.value, MemoryStatus.DISPUTED.value),
        ).fetchall()
        for row in rows:
            self._sync_fts(conn, self._record_from_row(row))

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _quote_hash(quote: str) -> str:
        return hashlib.sha256(quote.strip().encode("utf-8")).hexdigest()

    # CJK 连续段（含扩展 A 区及常用标点外的表意文字）与 ASCII 词元分别抽取。
    # 与 tests/memory_eval/probe_lexical.py 的 CJK/ASCII_WORD 保持同口径，避免
    # 索引侧与查询侧分词不一致导致 MATCH 永远错位。
    _CJK_RE = re.compile(r"[\u3400-\u9fff]+")
    _ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
    # bigram 查询项数上限：长 CJK query 会被拆成几百个 bigram，LIKE 兜底每项 2 个
    # 参数，超 SQLite 默认 999 变量上限会抛 "too many SQL variables"。FTS MATCH
    # 的 OR 项过多也会让查询规划器退化。200 个 bigram 覆盖 ~400 字 CJK query，
    # 远超召回 query 的正常长度；取前 200（去重保序后）足够覆盖语义。
    _MAX_QUERY_BIGRAMS = 200

    @classmethod
    def _ngrams(cls, text: str, n: int) -> list[str]:
        """CJK 段切 n-gram，ASCII 词整取，去重保序。

        这是 FTS 词法通道的索引/查询共用分词器。probe 实测：unicode61 tokenizer
        对整段 CJK 不分词，trigram（n=3）OR 查询在 120 case 上 0 命中；只有
        n=2（bigram）能把「用户偏好用中文交流」这类 query 拆成可命中记忆的 token
        （59.2% 精度 / 15.3% recall / 24% case 覆盖）。所以索引列存 bigram 串、
        查询侧也用 bigram OR，两侧必须用同一个函数。
        """
        out: list[str] = []
        for run in cls._CJK_RE.findall(text):
            if len(run) <= n:
                out.append(run)
            else:
                out.extend(run[i : i + n] for i in range(len(run) - n + 1))
        out.extend(cls._ASCII_WORD_RE.findall(text.lower()))
        return list(dict.fromkeys(out))

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
            # 索引列存 bigram 串而非原文：见 _init_schema 里 schema v2 的说明。
            # content/memory_key 用 bigram；dimension 是离散枚举值，原文整取即可。
            searchable = " ".join(self._flatten(record.structured_data))
            conn.execute(
                "INSERT INTO memory_fts(memory_id, content, memory_key, dimension, searchable_data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.id,
                    " ".join(self._ngrams(record.content, 2)),
                    " ".join(self._ngrams(record.memory_key, 2)),
                    record.dimension,
                    " ".join(self._ngrams(searchable, 2)),
                ),
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
                scope_id,memory_domain,memory_role,status,evidence_level,confidence,importance,
                sensitivity,valid_from,valid_until,source_session_id,source_message_id,created_at,
                updated_at,last_recalled_at,superseded_by,forgotten_at,dormant_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r.id,r.user_id,r.memory_type,r.dimension,r.memory_key,r.content,self._json(r.structured_data),
            r.scope_type,r.scope_id,r.memory_domain,r.memory_role,r.status,r.evidence_level,r.confidence,
            r.importance,r.sensitivity,r.valid_from,r.valid_until,r.source_session_id,r.source_message_id,
            r.created_at,r.updated_at,r.last_recalled_at,r.superseded_by,r.forgotten_at,r.dormant_at,
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
        """补证据 = 强化 = 活跃信号：插入 evidence 行后同事务 bump updated_at。

        不 bump 的话，Tier B scope 休眠检测（project_scope_last_activity 含
        MAX(updated_at)）会漏掉 merge 强化，把仍在被反复印证的项目误判休眠。
        """
        with self.transaction() as conn:
            self._insert_evidence(conn, evidence)
            conn.execute(
                "UPDATE memories SET updated_at=? WHERE id=?",
                (time.time(), evidence.memory_id),
            )

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
        memory_role: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[MemoryRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("memory_type", memory_type), ("dimension", dimension),
            ("scope_type", scope_type), ("scope_id", scope_id),
            ("memory_domain", memory_domain), ("status", status),
            ("memory_role", memory_role),
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
                dormant_at=current.dormant_at,
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
        memory_role: str | None = None,
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
        if memory_role is not None:
            clauses.append("m.memory_role=?")
            params.append(memory_role)
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
                # bigram OR 查询：把 query 切成 2 字符 n-gram（CJK）+ ASCII 整词，
                # OR 拼 MATCH。与索引侧（_sync_fts 写 bigram 串）同口径，token 相等
                # 匹配才能命中。OR 意味着 query 的任意一个 bigram 出现在文档里就命中，
                # 比 AND（默认）宽松，CJK 子串匹配终于能工作。探针实测 trigram(n=3) 全
                # 0 命中，只有 n=2 有效。
                terms = self._ngrams(query, 2)
                if terms:
                    if len(terms) > self._MAX_QUERY_BIGRAMS:
                        terms = terms[: self._MAX_QUERY_BIGRAMS]
                    expr = " OR ".join(f'"{t}"' for t in terms)
                    sql = f"""
                        SELECT m.* FROM memory_fts f JOIN memories m ON m.id=f.memory_id
                        WHERE memory_fts MATCH ? AND {where}
                        ORDER BY bm25(memory_fts), m.importance DESC, m.confidence DESC,
                                 m.updated_at DESC, m.id LIMIT ?
                    """
                    rows = conn.execute(sql, [expr, *params, limit]).fetchall()
                    if rows:
                        return [self._record_from_row(r) for r in rows]
                # bigram 为空（极短 query）或 FTS 0 命中，落到下面的 LIKE 兜底
            except sqlite3.DatabaseError:
                pass
        if query.strip():
            # LIKE 兜底：2 字符 bigram OR 匹配。比整串 LIKE 宽松——query 的任意
            # 2 字符子串出现在 content 或 memory_key 里就命中。bigram FTS 对 query
            # 与文档无 2 字符重叠时会漏（理论上极少，因为 bigram 粒度够细），这里兜住，
            # 也兜住 FTS 表不可用的环境。
            bigrams = self._ngrams(query, 2)
            if bigrams:
                if len(bigrams) > self._MAX_QUERY_BIGRAMS:
                    bigrams = bigrams[: self._MAX_QUERY_BIGRAMS]
                like_parts = ["(m.content LIKE ? ESCAPE '\\' OR m.memory_key LIKE ? ESCAPE '\\')"] * len(bigrams)
                where += f" AND ({' OR '.join(like_parts)})"
                escaped = [bg.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for bg in bigrams]
                for bg in escaped:
                    params.extend([f"%{bg}%", f"%{bg}%"])
            else:
                # 纯 ASCII 单词或单字 query，ngrams 退化为整词，回退整串子串
                escaped_q = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                where += " AND (m.content LIKE ? ESCAPE '\\' OR m.memory_key LIKE ? ESCAPE '\\')"
                params.extend([f"%{escaped_q}%", f"%{escaped_q}%"])
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
            now = time.time()
            record.status = status
            record.updated_at = now
            if status == MemoryStatus.DORMANT.value:
                # 转入休眠写时间戳——180 天硬遗忘窗口（decay._forget_long_dormant）靠它判定
                record.dormant_at = now
                conn.execute(
                    "UPDATE memories SET status=?, dormant_at=?, updated_at=? WHERE id=?",
                    (status, now, now, memory_id),
                )
            elif row["dormant_at"] is not None:
                # 从 dormant 迁出（唤醒/转 expired 等）时清掉休眠时间戳
                record.dormant_at = None
                conn.execute(
                    "UPDATE memories SET status=?, dormant_at=NULL, updated_at=? WHERE id=?",
                    (status, now, memory_id),
                )
            else:
                conn.execute(
                    "UPDATE memories SET status=?, updated_at=? WHERE id=?",
                    (status, now, memory_id),
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
        # 向量索引同步删除:vec_items.text 留有原文,不删等于没脱敏
        from ethan.memory.memory_vectors import remove_memory_index
        remove_memory_index(memory_id, db_path=self._db_path)

    def delete_memory(self, memory_id: str) -> bool:
        with self.transaction() as conn:
            if self._fts_available:
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            cursor = conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        from ethan.memory.memory_vectors import remove_memory_index
        remove_memory_index(memory_id, db_path=self._db_path)
        return cursor.rowcount > 0

    def bulk_set_dormant(self, memory_ids: list[str]) -> int:
        """active → dormant 批量（Tier B 项目休眠归档）。单事务 bulk UPDATE + 批量
        FTS 删除；向量索引不动——同夜 reindex_all 只重灌 active 自然清除，召回侧
        status 复查兜住白天窗口。只迁移 status=active 的行，幂等。返回实际迁移数。
        """
        if not memory_ids:
            return 0
        now = time.time()
        with self.transaction() as conn:
            changed = 0
            for start in range(0, len(memory_ids), 500):  # SQLite 999 变量上限防御
                ids = memory_ids[start : start + 500]
                placeholders = ",".join("?" * len(ids))
                cursor = conn.execute(
                    f"UPDATE memories SET status=?, dormant_at=?, updated_at=? "
                    f"WHERE id IN ({placeholders}) AND status=?",
                    (MemoryStatus.DORMANT.value, now, now, *ids, MemoryStatus.ACTIVE.value),
                )
                changed += cursor.rowcount
                if self._fts_available:
                    conn.execute(
                        f"DELETE FROM memory_fts WHERE memory_id IN ({placeholders})", ids
                    )
        return changed

    def wake_memories(self, memory_ids: list[str]) -> int:
        """dormant → active。逐条走 set_status（含 evidence 完整性检查与 FTS 恢复），
        再显式重建向量索引——set_status 不碰向量，等夜间 reindex 最多滞后 24h，
        唤醒的记忆应立即参与语义召回。返回唤醒数。
        """
        woken = 0
        for memory_id in memory_ids:
            record = self.get_memory(memory_id)
            if record is None or record.status != MemoryStatus.DORMANT.value:
                continue
            try:
                self.set_status(memory_id, MemoryStatus.ACTIVE.value)
            except (ValueError, KeyError) as exc:
                # ValueError: evidence 被清（理论上 dormant 不脱敏不会发生）
                # KeyError: record 并发删除（极端场景）
                # 两种情况跳过而非中断整批
                logger.warning("wake skipped for %s: %s: %s", memory_id, type(exc).__name__, exc)
                continue
            try:
                from ethan.memory.memory_vectors import index_memory

                index_memory(self.get_memory(memory_id), db_path=self._db_path)
            except Exception:
                # sqlite-vec 虚拟表 UNIQUE 约束等异常在 index_memory 内部未必被
                # 完全吞掉（virtual table 的 OperationalError 有时穿透 Python
                # try/except）。唤醒失败只意味着该记忆晚一步再索引，不阻塞主链路。
                logger.debug("[MemoryStore] reindex failed for %s during wake", memory_id, exc_info=True)
            woken += 1
        return woken

    def wake_scope(self, scope_type: str, scope_id: str) -> int:
        """唤醒一个 scope 下全部 dormant 记忆（项目回归时 admission 唤醒钩子 / UI 批量恢复用）。"""
        ids = [
            record.id
            for record in self.list_memories(
                scope_type=scope_type, scope_id=scope_id,
                status=MemoryStatus.DORMANT.value, limit=1000,
            )
        ]
        return self.wake_memories(ids)

    def evidence_session_counts(self, *, status: str | None = None) -> dict[str, int]:
        """按 memory_id 聚合 distinct evidence session 数。夜间批量晋升用——
        一趟 GROUP BY 拿全量，避免逐条 COUNT。status=None 不过滤（默认只查 active
        由调用方传）。"""
        sql = (
            "SELECT e.memory_id AS memory_id, COUNT(DISTINCT e.source_session_id) AS sessions "
            "FROM memory_evidence e JOIN memories m ON m.id=e.memory_id"
        )
        params: list[Any] = []
        if status is not None:
            sql += " WHERE m.status=?"
            params.append(status)
        sql += " GROUP BY e.memory_id"
        rows = self._get_conn().execute(sql, params).fetchall()
        return {row["memory_id"]: row["sessions"] for row in rows}

    def last_evidence_at(self, memory_id: str) -> float | None:
        row = self._get_conn().execute(
            "SELECT MAX(created_at) AS t FROM memory_evidence WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        return row["t"] if row else None

    def batch_last_evidence_at(self, memory_ids: list[str]) -> dict[str, float]:
        """批量查询多条记忆的最后 evidence 时间，返回 {memory_id: timestamp}。

        替代逐条 last_evidence_at 调用，消除 N+1 查询。
        """
        if not memory_ids:
            return {}
        result: dict[str, float] = {}
        placeholders = ",".join("?" for _ in memory_ids)
        rows = self._get_conn().execute(
            f"SELECT memory_id, MAX(created_at) AS t FROM memory_evidence "
            f"WHERE memory_id IN ({placeholders}) GROUP BY memory_id",
            memory_ids,
        ).fetchall()
        for row in rows:
            if row["t"] is not None:
                result[row["memory_id"]] = float(row["t"])
        return result

    def project_scope_last_activity(self) -> list[tuple[str, float]]:
        """每个 project scope 的最后活跃时间（用于休眠检测）。

        四路信号取 MAX：updated_at（编辑/强化 bump）、created_at（新准入）、
        last_recalled_at（召回 touch）、evidence.created_at（兜住历史上
        add_evidence 不 bump updated_at 的存量数据——没有这路上线首跑会把
        真实活跃的老项目误判休眠）。
        """
        rows = self._get_conn().execute("""
            SELECT m.scope_id AS scope_id,
                   MAX(m.updated_at) AS lu, MAX(m.created_at) AS lc,
                   MAX(m.last_recalled_at) AS lr, MAX(e.created_at) AS le
            FROM memories m LEFT JOIN memory_evidence e ON e.memory_id=m.id
            WHERE m.scope_type=? AND m.status=?
            GROUP BY m.scope_id
        """, ("project", MemoryStatus.ACTIVE.value)).fetchall()
        return [
            (row["scope_id"], max(row["lu"] or 0.0, row["lc"] or 0.0, row["lr"] or 0.0, row["le"] or 0.0))
            for row in rows
        ]

    def list_active_tentative(self) -> list[MemoryRecord]:
        """active 且 structured_data 带 tentative 的 decision/activity（Tier C 扫描集）。
        LIKE 预筛 + Python 精判（structured_data.get("tentative") is True），
        decision/activity 子集小。"""
        rows = self._get_conn().execute(
            "SELECT * FROM memories WHERE status=? AND memory_type IN ('decision','activity') "
            "AND structured_data LIKE '%\"tentative\"%' ORDER BY updated_at",
            (MemoryStatus.ACTIVE.value,),
        ).fetchall()
        return [r for r in (self._record_from_row(row) for row in rows)
                if r.structured_data.get("tentative") is True]

    def set_confidence_quiet(self, memory_id: str, confidence: float) -> None:
        """只动 confidence，不动 updated_at。

        夜间晋升阶梯的关键不变量：批量晋升若刷新 updated_at 会永久重置 Tier B
        scope 休眠计时（scope 活跃信号含 MAX(updated_at)），休眠检测失效。
        """
        conn = self._get_conn()
        conn.execute(
            "UPDATE memories SET confidence=? WHERE id=?",
            (min(1.0, max(0.0, float(confidence))), memory_id),
        )
        conn.commit()

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

    def get_meta(self, key: str) -> str | None:
        row = self._get_conn().execute(
            "SELECT value FROM structured_memory_meta WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO structured_memory_meta(key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()

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
            scope_id=row["scope_id"],memory_domain=row["memory_domain"],
            memory_role=row["memory_role"],status=row["status"],
            evidence_level=row["evidence_level"],confidence=row["confidence"],importance=row["importance"],
            sensitivity=row["sensitivity"],valid_from=row["valid_from"],valid_until=row["valid_until"],
            source_session_id=row["source_session_id"] or "",source_message_id=row["source_message_id"] or "",
            created_at=row["created_at"],updated_at=row["updated_at"],last_recalled_at=row["last_recalled_at"],
            superseded_by=row["superseded_by"],forgotten_at=row["forgotten_at"],
            dormant_at=row["dormant_at"],
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
