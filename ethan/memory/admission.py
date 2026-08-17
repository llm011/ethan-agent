"""Deterministic admission policy for structured memory candidates.

The LLM proposes candidates; this module decides what becomes an active
memory. Embedding similarity is used only to *suggest* pairs (semantic
near-neighbors); every merge/supersede decision follows deterministic rules
(same-dimension + content divergence for supersession, exact key/scope/domain
matching otherwise) and is recorded in ``processing_reason`` for audit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ethan.memory.records import (
    CandidateStatus,
    ConsolidationJob,
    EvidenceLevel,
    MemoryCandidate,
    MemoryDomain,
    MemoryEvidence,
    MemoryRecord,
    MemoryStatus,
    new_id,
)
from ethan.memory.store import MemoryStore

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "v1"

# observed 准入模式(环境变量 ETHAN_ADMISSION_OBSERVED_MODE 切换):
# - gate(默认):单 session observed 留 pending,≥2 独立 session 才晋升(噪声闸)
# - accrual:单 session observed 即建 active 但 confidence 封 0.5(召回排序自然靠后),
#   再次出现按晋升处理。A/B 由 golden live 评测决定默认值,当前默认 gate。
import os as _os  # noqa: E402

OBSERVED_MODE = _os.environ.get("ETHAN_ADMISSION_OBSERVED_MODE", "gate")

# Minimum number of independent sessions of consistent evidence to promote an
# observed candidate to an active inferred memory.
PROMOTION_SESSION_THRESHOLD = 2

# 跨 scope 偏好配对（ETHAN_MEMORY_PAIR_CROSS_L2）：project 内沉淀的偏好候选
# → user 级既有偏好的强化通道。场景：「论文做成PPT」在每个项目里都以 project
# scope 候选出现，同 scope 配对永远配不上 user 级既有偏好——偏好本该在 user
# 级被反复强化（evidence 独立 session 数 → confidence 晋升）。只补证据永不
# supersede；阈值比同 scope 配对（0.7）更严。
CROSS_SCOPE_PAIR_L2 = float(_os.environ.get("ETHAN_MEMORY_PAIR_CROSS_L2", "0.6"))
# cross-scope 偏好配对的目标 scope 类型 = Tier A 豁免的 user 级 scope。
# 与 decay.EXEMPT_SCOPE_TYPES 同源，共用一处定义。
from ethan.memory.decay import EXEMPT_SCOPE_TYPES as CROSS_SCOPE_SCOPE_TYPES  # noqa: E402


@dataclass
class AdmissionResult:
    admitted: list[str]
    merged: list[str]
    rejected: list[str]
    disputed: list[str]


# Outcome labels returned by admit_candidate alongside the memory_id, so the
# batch driver can classify each candidate into admitted/merged/rejected/pending
# without re-reading the candidates table.
OUTCOME_ADMITTED = "admitted"
OUTCOME_MERGED = "merged"
OUTCOME_REJECTED = "rejected"
OUTCOME_PENDING = "pending"


class AdmissionPolicy:
    """Decides candidate -> memory transitions inside a MemoryStore transaction."""

    def __init__(self, store: MemoryStore):
        self._store = store
        self._last_same_scope: bool | None = None  # admit_candidate 后可读取

    def admit_candidate(self, candidate: MemoryCandidate) -> tuple[str | None, str]:
        """Admit one candidate.

        Returns ``(memory_id | None, outcome)`` where outcome is one of
        ``admitted``/``merged``/``rejected``/``pending``. ``memory_id`` is the
        active memory the candidate landed in (new or existing), or None when
        the candidate stays pending (observed not yet promotable) or was
        rejected. The candidate row is marked processed for every terminal
        outcome; pending candidates are left untouched so the next sweep can
        re-evaluate them.
        """
        # 语义配对（embedding 只做建议，决策规则保持确定性）:
        # 同 scope+domain 的最近邻 active 命中阈值时,按 evidence_level 走
        # 确定性的 merge/supersede,避免"住在深圳"和"家在深圳南山"各存一条。
        # companion 域不参与(情感记忆的语义合并风险高于收益)。
        if candidate.memory_domain == MemoryDomain.GENERAL.value:
            self._last_same_scope = None  # 重置上一轮状态，避免泄漏
            pair = self._semantic_pair(candidate)
            if pair is not None:
                return self._admit_with_pair(candidate, *pair)
            cross = self._cross_scope_preference_pair(candidate)
            if cross is not None:
                return self._reinforce_cross_scope(candidate, *cross)
        level = candidate.evidence_level
        if level in (EvidenceLevel.EXPLICIT.value, EvidenceLevel.CORRECTED.value):
            return self._admit_explicit(candidate)
        if level == EvidenceLevel.INFERRED.value:
            return self._admit_inferred(candidate)
        # observed: stays a candidate unless repeated evidence already satisfies promotion.
        return self._maybe_promote_observed(candidate)

    # ------------------------------------------------------------------
    # 语义配对(向量索引只做配对建议;所有决策规则确定、reason 留痕)
    # ------------------------------------------------------------------

    def _semantic_pair(self, candidate: MemoryCandidate) -> tuple[MemoryRecord, float] | None:
        from ethan.memory.memory_vectors import MERGE_L2_THRESHOLD, semantic_neighbors

        hits = semantic_neighbors(
            content=candidate.content,
            scope_type=candidate.scope_type,
            scope_id=candidate.scope_id,
            memory_domain=candidate.memory_domain,
            db_path=self._store.db_path,
        )
        for hit in hits:
            if hit["distance"] > MERGE_L2_THRESHOLD:
                continue
            existing = self._store.get_memory(hit["id"])
            if existing and existing.status == MemoryStatus.ACTIVE.value:
                return existing, hit["distance"]
        return None

    def _cross_scope_preference_pair(
        self, candidate: MemoryCandidate
    ) -> tuple[MemoryRecord, float] | None:
        """project scope 偏好候选 → user 级既有偏好的跨 scope 配对（只建议，决策护栏全在这里）。

        护栏（全部确定性）：
        1. 候选必须是 preference.* 维度 + project scope——decision/activity 跨
           scope 会把项目决策误灌进 user 级偏好；
        2. evidence ∈ {explicit, inferred}：corrected 的替换语义不该走"只补证据"
           通道，observed 噪声不值得跨 scope；
        3. 只找 user/user_domain/user_skill scope 的 active 近邻（Tier A 豁免域，
           不会反向把 user 偏好灌进别的项目）；
        4. 既有记忆 dimension 与候选严格相等；
        5. L2 <= CROSS_SCOPE_PAIR_L2（默认 0.6，比同 scope 的 0.7 严——跨 scope
           误合并的代价更高）。
        """
        if candidate.scope_type != "project":
            return None
        if not candidate.dimension.startswith("preference."):
            return None
        if candidate.evidence_level not in (
            EvidenceLevel.EXPLICIT.value, EvidenceLevel.INFERRED.value,
        ):
            return None
        from ethan.memory.memory_vectors import semantic_neighbors

        hits = semantic_neighbors(
            content=candidate.content,
            memory_domain=candidate.memory_domain,
            db_path=self._store.db_path,
            limit=16,
        )
        for hit in hits:
            if hit["distance"] > CROSS_SCOPE_PAIR_L2:
                continue
            existing = self._store.get_memory(hit["id"])
            if existing is None or existing.status != MemoryStatus.ACTIVE.value:
                continue
            if existing.scope_type not in CROSS_SCOPE_SCOPE_TYPES:
                continue
            if existing.dimension != candidate.dimension:
                continue
            return existing, hit["distance"]
        return None

    def _reinforce_cross_scope(
        self, candidate: MemoryCandidate, existing: MemoryRecord, distance: float
    ) -> tuple[str | None, str]:
        """跨 scope 强化：只补证据，永不 supersede。

        project 候选配到 user 级偏好 → 证据挂到 user 级记忆上（evidence 独立
        session 数随之增长，夜间 confidence 晋升自愈"多次发生仍卡 60%"），
        不新建 project 副本污染项目 scope。
        """
        tag = f"cross_scope_reinforced:l2={distance:.3f}"
        self._store.add_evidence(self._evidence_from_candidate(candidate, existing.id))
        self._maybe_clear_tentative(existing, candidate)
        self._store.mark_candidate_processed(
            candidate.id, CandidateStatus.MERGED.value, tag, existing.id)
        # 标记是否同 scope 合并：cross-scope 合并不触发 project scope 唤醒
        self._last_same_scope = (existing.scope_type == candidate.scope_type)
        return existing.id, OUTCOME_MERGED

    def _maybe_clear_tentative(
        self, existing: MemoryRecord, candidate: MemoryCandidate
    ) -> None:
        """tentative 记忆被非临时候选强化 → 清标。

        「先试试方案A」后来被定稿表述强化（同 scope merge 或跨 scope 配对）时
        清掉 tentative，退出 Tier C 快速衰减轨道。update_memory 顺带 bump
        updated_at——清标本身就是强化信号，衰减锚点应重置（decay 不变量 4）。
        """
        if existing.structured_data.get("tentative") is not True:
            return
        if candidate.structured_data.get("tentative") is True:
            return
        data = dict(existing.structured_data)
        data.pop("tentative", None)
        try:
            self._store.update_memory(existing.id, structured_data=data)
        except Exception:
            logger.warning("clear tentative flag failed for %s", existing.id, exc_info=True)

    def _admit_with_pair(
        self, candidate: MemoryCandidate, existing: MemoryRecord, distance: float
    ) -> tuple[str | None, str]:
        """语义配对命中后的确定性决策。

        - explicit/corrected + 同 dimension + 内容发散 → supersede(用户更新了
          该方面的事实,与同 key 发散规则一致);corrected 无视内容是否发散
        - explicit/corrected 跨 dimension 或内容一致 → 只补证据(reinforce)
        - inferred → 只补证据(模型猜测无权替换既有记忆)
        - observed → 仍须过 ≥2 session 门;晋升时并入近邻而非新建(去重)
        """
        level = candidate.evidence_level
        tag = f"semantic_pair:l2={distance:.3f}"
        if level in (EvidenceLevel.EXPLICIT.value, EvidenceLevel.CORRECTED.value):
            divergent = level == EvidenceLevel.CORRECTED.value or _content_diverges(existing, candidate)
            if divergent and existing.dimension == candidate.dimension:
                confidence = 1.0 if level == EvidenceLevel.CORRECTED.value else max(candidate.confidence, 0.95)
                record = self._record_from_candidate(candidate, status=MemoryStatus.ACTIVE.value, confidence=confidence)
                # 同一事实的新旧表述应收敛到同一身份:继承既有记忆的 key 四元组,
                # supersede_and_create 要求 identity 一致(语义配对正是跨 key 场景)
                record.memory_key = existing.memory_key
                record.scope_type = existing.scope_type
                record.scope_id = existing.scope_id
                record.memory_domain = existing.memory_domain
                evidence = self._evidence_from_candidate(candidate, record.id)
                try:
                    self._store.supersede_and_create(existing.id, record, [evidence])
                except (ValueError, KeyError) as exc:
                    logger.info("semantic supersession rejected (%s): %s", exc, candidate.memory_key)
                    self._store.mark_candidate_processed(candidate.id, CandidateStatus.REJECTED.value, str(exc))
                    return None, OUTCOME_REJECTED
                self._deindex(existing.id)
                self._index_new(record)
                self._store.mark_candidate_processed(
                    candidate.id, CandidateStatus.ADMITTED.value, f"semantic_superseded:{tag}", record.id)
                return record.id, OUTCOME_ADMITTED
            self._store.add_evidence(self._evidence_from_candidate(candidate, existing.id))
            self._maybe_clear_tentative(existing, candidate)
            self._store.mark_candidate_processed(
                candidate.id, CandidateStatus.MERGED.value, f"semantic_reinforced:{tag}", existing.id)
            return existing.id, OUTCOME_MERGED
        if level == EvidenceLevel.INFERRED.value:
            self._store.add_evidence(self._evidence_from_candidate(candidate, existing.id))
            self._maybe_clear_tentative(existing, candidate)
            self._store.mark_candidate_processed(
                candidate.id, CandidateStatus.MERGED.value, f"semantic_merged:{tag}", existing.id)
            return existing.id, OUTCOME_MERGED
        # observed: 门槛不放松——先凑齐 ≥2 独立 session,晋升时并入近邻而非新建
        sessions = self._distinct_consistent_sessions(candidate)
        if len(sessions) < PROMOTION_SESSION_THRESHOLD:
            return None, OUTCOME_PENDING
        self._store.add_evidence(
            self._evidence_from_candidate(candidate, existing.id, EvidenceLevel.INFERRED.value))
        self._maybe_clear_tentative(existing, candidate)
        self._store.mark_candidate_processed(
            candidate.id, CandidateStatus.MERGED.value, f"semantic_promoted_merge:{tag}", existing.id)
        return existing.id, OUTCOME_MERGED

    def _index_new(self, record: MemoryRecord) -> None:
        from ethan.memory.memory_vectors import index_memory
        index_memory(record, db_path=self._store.db_path)

    def _deindex(self, memory_id: str) -> None:
        from ethan.memory.memory_vectors import remove_memory_index
        remove_memory_index(memory_id, db_path=self._store.db_path)

    # ------------------------------------------------------------------
    def _admit_explicit(self, candidate: MemoryCandidate) -> tuple[str | None, str]:
        confidence = 1.0 if candidate.evidence_level == EvidenceLevel.CORRECTED.value else max(candidate.confidence, 0.95)
        existing = self._store.find_current_by_key_scope(
            candidate.memory_key, candidate.scope_type, candidate.scope_id, candidate.memory_domain
        )
        record = self._record_from_candidate(candidate, status=MemoryStatus.ACTIVE.value, confidence=confidence)
        evidence = self._evidence_from_candidate(candidate, record.id)
        if existing is None:
            try:
                self._store.create_memory_with_evidence(record, [evidence])
            except ValueError as exc:
                logger.info("explicit admission rejected (%s): %s", exc, candidate.memory_key)
                self._store.mark_candidate_processed(candidate.id, CandidateStatus.REJECTED.value, str(exc))
                return None, OUTCOME_REJECTED
            self._index_new(record)
            self._store.mark_candidate_processed(candidate.id, CandidateStatus.ADMITTED.value, "", record.id)
            return record.id, OUTCOME_ADMITTED
        if candidate.evidence_level == EvidenceLevel.CORRECTED.value or _content_diverges(existing, candidate):
            try:
                self._store.supersede_and_create(existing.id, record, [evidence])
            except (ValueError, KeyError) as exc:
                logger.info("supersession rejected (%s): %s", exc, candidate.memory_key)
                self._store.mark_candidate_processed(candidate.id, CandidateStatus.REJECTED.value, str(exc))
                return None, OUTCOME_REJECTED
            self._deindex(existing.id)
            self._index_new(record)
            self._store.mark_candidate_processed(candidate.id, CandidateStatus.ADMITTED.value, "superseded", record.id)
            return record.id, OUTCOME_ADMITTED
        # Same explicit content already active — reinforce with additional evidence.
        self._store.add_evidence(self._evidence_from_candidate(candidate, existing.id))
        self._maybe_clear_tentative(existing, candidate)
        self._store.mark_candidate_processed(candidate.id, CandidateStatus.MERGED.value, "reinforced", existing.id)
        return existing.id, OUTCOME_MERGED

    def _admit_inferred(self, candidate: MemoryCandidate) -> tuple[str | None, str]:
        existing = self._store.find_current_by_key_scope(
            candidate.memory_key, candidate.scope_type, candidate.scope_id, candidate.memory_domain
        )
        if existing is None:
            record = self._record_from_candidate(candidate, status=MemoryStatus.ACTIVE.value)
            evidence = self._evidence_from_candidate(candidate, record.id)
            try:
                self._store.create_memory_with_evidence(record, [evidence])
            except ValueError as exc:
                logger.info("inferred admission rejected (%s): %s", exc, candidate.memory_key)
                self._store.mark_candidate_processed(candidate.id, CandidateStatus.REJECTED.value, str(exc))
                return None, OUTCOME_REJECTED
            self._index_new(record)
            self._store.mark_candidate_processed(candidate.id, CandidateStatus.ADMITTED.value, "", record.id)
            return record.id, OUTCOME_ADMITTED
        # Reinforce existing active record.
        self._store.add_evidence(self._evidence_from_candidate(candidate, existing.id))
        self._maybe_clear_tentative(existing, candidate)
        self._store.mark_candidate_processed(candidate.id, CandidateStatus.MERGED.value, "reinforced", existing.id)
        return existing.id, OUTCOME_MERGED

    def _maybe_promote_observed(self, candidate: MemoryCandidate) -> tuple[str | None, str]:
        """Promote an observed candidate only when >=2 independent sessions agree.

        accrual 模式(ETHAN_ADMISSION_OBSERVED_MODE=accrual):单 session 即建
        active 但 confidence 封 0.5,召回排序自然靠后;再次出现走正常晋升。
        """
        sessions = self._distinct_consistent_sessions(candidate)
        if len(sessions) < PROMOTION_SESSION_THRESHOLD:
            if OBSERVED_MODE == "accrual":
                record = self._record_from_candidate(
                    candidate, status=MemoryStatus.ACTIVE.value,
                    confidence=min(candidate.confidence, 0.5),
                )
                evidence = self._evidence_from_candidate(candidate, record.id)
                try:
                    self._store.create_memory_with_evidence(record, [evidence])
                except ValueError:
                    existing = self._store.find_current_by_key_scope(
                        candidate.memory_key, candidate.scope_type, candidate.scope_id, candidate.memory_domain
                    )
                    if existing:
                        self._store.add_evidence(self._evidence_from_candidate(candidate, existing.id))
                        self._maybe_clear_tentative(existing, candidate)
                        self._store.mark_candidate_processed(candidate.id, CandidateStatus.MERGED.value, "reinforced", existing.id)
                        return existing.id, OUTCOME_MERGED
                    self._store.mark_candidate_processed(candidate.id, CandidateStatus.REJECTED.value, "race")
                    return None, OUTCOME_REJECTED
                self._index_new(record)
                self._store.mark_candidate_processed(candidate.id, CandidateStatus.ADMITTED.value, "accrual_low_confidence", record.id)
                return record.id, OUTCOME_ADMITTED
            # gate: stays pending — do NOT mark processed; daily sweep may promote it later.
            return None, OUTCOME_PENDING
        record = self._record_from_candidate(
            candidate, status=MemoryStatus.ACTIVE.value,
            evidence_level=EvidenceLevel.INFERRED.value, confidence=min(candidate.confidence + 0.2, 0.85),
        )
        evidence = self._evidence_from_candidate(candidate, record.id, evidence_level=EvidenceLevel.INFERRED.value)
        try:
            self._store.create_memory_with_evidence(record, [evidence])
        except ValueError:
            existing = self._store.find_current_by_key_scope(
                candidate.memory_key, candidate.scope_type, candidate.scope_id, candidate.memory_domain
            )
            if existing:
                self._store.add_evidence(self._evidence_from_candidate(candidate, existing.id, EvidenceLevel.INFERRED.value))
                self._maybe_clear_tentative(existing, candidate)
                self._store.mark_candidate_processed(candidate.id, CandidateStatus.MERGED.value, "reinforced", existing.id)
                return existing.id, OUTCOME_MERGED
            self._store.mark_candidate_processed(candidate.id, CandidateStatus.REJECTED.value, "race")
            return None, OUTCOME_REJECTED
        self._index_new(record)
        self._store.mark_candidate_processed(candidate.id, CandidateStatus.ADMITTED.value, "promoted", record.id)
        return record.id, OUTCOME_ADMITTED

    def _distinct_consistent_sessions(self, candidate: MemoryCandidate) -> set[str]:
        """Sessions (including the candidate's own) that produced pending evidence for this key+scope."""
        pending = self._store.list_pending_candidates(
            memory_key=candidate.memory_key, scope_type=candidate.scope_type,
            scope_id=candidate.scope_id, memory_domain=candidate.memory_domain, limit=500,
        )
        sessions = {candidate.source_session_id}
        for other in pending:
            if other.id == candidate.id:
                continue
            if _content_compatible(other.content, candidate.content):
                sessions.add(other.source_session_id)
        # Also check evidence already attached to any existing active record.
        existing = self._store.find_current_by_key_scope(
            candidate.memory_key, candidate.scope_type, candidate.scope_id, candidate.memory_domain
        )
        if existing:
            for ev in self._store.list_evidence(existing.id):
                sessions.add(ev["source_session_id"])
        return sessions

    # ------------------------------------------------------------------
    def admit_batch(self, candidates: list[MemoryCandidate]) -> AdmissionResult:
        admitted: list[str] = []
        merged: list[str] = []
        rejected: list[str] = []
        disputed: list[str] = []
        # 收集需要唤醒的 project scope，循环后一次性唤醒（避免逐 candidate 重复扫描）
        scopes_to_wake: set[tuple[str, str]] = set()
        for candidate in candidates:
            try:
                memory_id, outcome = self.admit_candidate(candidate)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("admission failure for candidate %s", candidate.id)
                try:
                    self._store.mark_candidate_processed(candidate.id, CandidateStatus.REJECTED.value, str(exc)[:200])
                except Exception:
                    pass
                rejected.append(candidate.id)
                continue
            if outcome == OUTCOME_PENDING:
                # Observed candidate not yet promotable stays pending.
                continue
            if outcome == OUTCOME_REJECTED:
                rejected.append(candidate.id)
                continue
            if outcome == OUTCOME_MERGED:
                if memory_id:
                    merged.append(memory_id)
                    # 只有同 scope 合并才唤醒 project scope；
                    # cross-scope 合并（_reinforce_cross_scope）只是往 user scope 补证据，
                    # project scope 没有新活动，不需要唤醒
                    if (candidate.scope_type == "project" and candidate.scope_id
                            and self._last_same_scope is not False):
                        scopes_to_wake.add(("project", candidate.scope_id))
                continue
            # OUTCOME_ADMITTED — a new/active memory was produced.
            if memory_id is None:
                continue
            admitted.append(memory_id)
            if candidate.scope_type == "project" and candidate.scope_id:
                scopes_to_wake.add(("project", candidate.scope_id))
            key_scope = (candidate.memory_key, candidate.scope_type, candidate.scope_id, candidate.memory_domain)
            if self._has_conflicting_evidence(key_scope, exclude_memory_id=memory_id):
                disputed.append(memory_id)
        # 统一唤醒所有有新候选落地的 project scope（一次扫描，避免逐 candidate 重复）
        if scopes_to_wake:
            from ethan.memory.decay import wake_scope_dormant
            for scope_type, scope_id in scopes_to_wake:
                wake_scope_dormant(self._store, scope_type, scope_id)
        return AdmissionResult(admitted=admitted, merged=merged, rejected=rejected, disputed=disputed)

    def _has_conflicting_evidence(self, key_scope: tuple[str, str, str, str], *, exclude_memory_id: str) -> bool:
        memory_key, scope_type, scope_id, domain = key_scope
        records = self._store.list_memories(
            scope_type=scope_type, scope_id=scope_id, memory_domain=domain, limit=50
        )
        relevant = [r for r in records if r.memory_key == memory_key and r.id != exclude_memory_id and r.status == MemoryStatus.ACTIVE.value]
        return bool(relevant)

    # ------------------------------------------------------------------
    @staticmethod
    def _record_from_candidate(
        candidate: MemoryCandidate, *, status: str,
        evidence_level: str | None = None, confidence: float | None = None,
    ) -> MemoryRecord:
        return MemoryRecord(
            id=new_id("mem"),
            memory_type=candidate.memory_type,
            dimension=candidate.dimension,
            memory_key=candidate.memory_key,
            content=candidate.content,
            structured_data=candidate.structured_data,
            scope_type=candidate.scope_type,
            scope_id=candidate.scope_id,
            memory_domain=candidate.memory_domain,
            status=status,
            evidence_level=evidence_level or candidate.evidence_level,
            confidence=confidence if confidence is not None else candidate.confidence,
            importance=candidate.importance,
            sensitivity=candidate.sensitivity,
            user_id=candidate.user_id,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
            source_session_id=candidate.source_session_id,
            source_message_id=candidate.source_message_id,
        )

    @staticmethod
    def _evidence_from_candidate(
        candidate: MemoryCandidate, memory_id: str, evidence_level: str | None = None
    ) -> MemoryEvidence:
        return MemoryEvidence(
            memory_id=memory_id,
            candidate_id=candidate.id,
            evidence_level=evidence_level or candidate.evidence_level,
            source_session_id=candidate.source_session_id,
            source_message_id=candidate.source_message_id,
            source_role=candidate.source_role,
            source_quote=candidate.source_quote,
            observed_at=candidate.created_at,
            extractor_version=candidate.extractor_version,
        )


def _content_diverges(existing: MemoryRecord, candidate: MemoryCandidate) -> bool:
    """A corrected candidate supersedes when its content differs from the active record."""
    return existing.content.strip() != candidate.content.strip()


def _content_compatible(a: str, b: str) -> bool:
    """Loose compatibility for grouping observed evidence. Not used to decide conflicts."""
    return a.strip() == b.strip()


def incremental_job_key(user_id: str, session_id: str, message_id: str | int) -> str:
    return f"incremental:{user_id or 'default'}:{session_id}:{message_id}:{PIPELINE_VERSION}"


def daily_job_key(user_id: str, local_date: str) -> str:
    return f"daily:{user_id or 'default'}:{local_date}:{PIPELINE_VERSION}"


def run_incremental_admission(store: MemoryStore, candidates: list[MemoryCandidate]) -> AdmissionResult:
    """Insert candidates and run the admission policy. Safe to call after candidate insertion."""
    policy = AdmissionPolicy(store)
    return policy.admit_batch(candidates)


def run_daily_admission(store: MemoryStore, candidates: list[MemoryCandidate]) -> AdmissionResult:
    """Re-run deterministic admission during the daily consolidation sweep."""
    return AdmissionPolicy(store).admit_batch(candidates)


def claim_incremental(store: MemoryStore, *, user_id: str, session_id: str, message_id: str | int, source_until: float) -> bool:
    job = ConsolidationJob(
        user_id=user_id,
        job_type="incremental_extraction",
        job_key=incremental_job_key(user_id, session_id, str(message_id)),
        pipeline_version=PIPELINE_VERSION,
        source_until=source_until,
    )
    return store.claim_job(job)


def complete_incremental(store: MemoryStore, *, user_id: str, session_id: str, message_id: str | int, result: dict[str, Any]) -> None:
    store.complete_job(incremental_job_key(user_id, session_id, str(message_id)), result)


def fail_incremental(store: MemoryStore, *, user_id: str, session_id: str, message_id: str | int, error: str) -> None:
    store.fail_job(incremental_job_key(user_id, session_id, str(message_id)), error)


def claim_daily(store: MemoryStore, *, user_id: str, local_date: str, source_until: float) -> bool:
    job = ConsolidationJob(
        user_id=user_id,
        job_type="daily_consolidation",
        job_key=daily_job_key(user_id, local_date),
        pipeline_version=PIPELINE_VERSION,
        source_until=source_until,
    )
    return store.claim_job(job)


def complete_daily(store: MemoryStore, *, user_id: str, local_date: str, result: dict[str, Any]) -> None:
    store.complete_job(daily_job_key(user_id, local_date), result)


def fail_daily(store: MemoryStore, *, user_id: str, local_date: str, error: str) -> None:
    store.fail_job(daily_job_key(user_id, local_date), error)
