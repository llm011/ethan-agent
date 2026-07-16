"""Typed records for the structured memory subsystem."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MemoryType(StrEnum):
    PERSONAL_INFORMATION = "personal_information"
    PREFERENCE = "preference"
    METHODOLOGY = "methodology"
    ACTIVITY = "activity"
    DECISION = "decision"
    RELATIONSHIP = "relationship"
    COMPANION = "companion"
    SKILL_EXPERIENCE = "skill_experience"


class MemoryDomain(StrEnum):
    GENERAL = "general"
    COMPANION = "companion"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    FORGOTTEN = "forgotten"


class EvidenceLevel(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    EXPLICIT = "explicit"
    CORRECTED = "corrected"


class ScopeType(StrEnum):
    USER = "user"
    USER_DOMAIN = "user_domain"
    USER_SKILL = "user_skill"
    PROJECT = "project"
    MODE = "mode"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    ADMITTED = "admitted"
    MERGED = "merged"
    REJECTED = "rejected"


class JobStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _enum_value(value: str | StrEnum, enum_type: type[StrEnum], field_name: str) -> str:
    try:
        return enum_type(value).value
    except ValueError as exc:
        allowed = ", ".join(e.value for e in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


def _bounded_text(value: str, field_name: str, max_length: int, *, required: bool = True) -> str:
    value = (value or "").strip()
    if required and not value:
        raise ValueError(f"{field_name} is required")
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return value


def _score(value: float, field_name: str) -> float:
    value = float(value)
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


def _json_object(value: dict[str, Any] | None, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    # Fail early for values that cannot be persisted as JSON.
    json.dumps(value, ensure_ascii=False)
    return value


@dataclass(slots=True)
class MemoryRecord:
    memory_type: str
    dimension: str
    memory_key: str
    content: str
    scope_type: str = ScopeType.USER.value
    scope_id: str = "self"
    memory_domain: str = MemoryDomain.GENERAL.value
    status: str = MemoryStatus.CANDIDATE.value
    evidence_level: str = EvidenceLevel.OBSERVED.value
    confidence: float = 0.5
    importance: float = 0.5
    sensitivity: str = Sensitivity.NORMAL.value
    structured_data: dict[str, Any] = field(default_factory=dict)
    user_id: str = ""
    valid_from: float | None = None
    valid_until: float | None = None
    source_session_id: str = ""
    source_message_id: str = ""
    id: str = field(default_factory=lambda: new_id("mem"))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_recalled_at: float | None = None
    superseded_by: str | None = None
    forgotten_at: float | None = None

    def __post_init__(self) -> None:
        self.memory_type = _enum_value(self.memory_type, MemoryType, "memory_type")
        self.memory_domain = _enum_value(self.memory_domain, MemoryDomain, "memory_domain")
        self.status = _enum_value(self.status, MemoryStatus, "status")
        self.evidence_level = _enum_value(self.evidence_level, EvidenceLevel, "evidence_level")
        self.scope_type = _enum_value(self.scope_type, ScopeType, "scope_type")
        self.sensitivity = _enum_value(self.sensitivity, Sensitivity, "sensitivity")
        self.dimension = _bounded_text(self.dimension, "dimension", 160)
        self.memory_key = _bounded_text(self.memory_key, "memory_key", 240)
        self.content = _bounded_text(self.content, "content", 4000)
        self.scope_id = _bounded_text(self.scope_id, "scope_id", 240)
        self.user_id = _bounded_text(self.user_id, "user_id", 128, required=False)
        self.source_session_id = _bounded_text(
            self.source_session_id, "source_session_id", 128, required=False
        )
        self.source_message_id = _bounded_text(
            str(self.source_message_id or ""), "source_message_id", 128, required=False
        )
        self.confidence = _score(self.confidence, "confidence")
        self.importance = _score(self.importance, "importance")
        self.structured_data = _json_object(self.structured_data, "structured_data")
        if self.valid_from is not None:
            self.valid_from = float(self.valid_from)
        if self.valid_until is not None:
            self.valid_until = float(self.valid_until)
        if self.valid_from is not None and self.valid_until is not None:
            if self.valid_until < self.valid_from:
                raise ValueError("valid_until cannot precede valid_from")
        if self.memory_domain == MemoryDomain.COMPANION.value:
            if self.memory_type != MemoryType.COMPANION.value:
                raise ValueError("companion domain requires companion memory_type")
        elif self.memory_type == MemoryType.COMPANION.value:
            raise ValueError("companion memory_type requires companion domain")


@dataclass(slots=True)
class MemoryEvidence:
    memory_id: str
    evidence_level: str
    source_session_id: str
    source_message_id: str
    source_role: str
    source_quote: str
    candidate_id: str | None = None
    observed_at: float | None = None
    extractor_version: str = "v1"
    id: str = field(default_factory=lambda: new_id("evidence"))
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.memory_id = _bounded_text(self.memory_id, "memory_id", 128)
        self.evidence_level = _enum_value(
            self.evidence_level, EvidenceLevel, "evidence_level"
        )
        self.source_session_id = _bounded_text(
            self.source_session_id, "source_session_id", 128
        )
        self.source_message_id = _bounded_text(
            str(self.source_message_id or ""), "source_message_id", 128, required=False
        )
        self.source_role = _bounded_text(self.source_role, "source_role", 32)
        if self.source_role not in {"user", "assistant", "tool", "api"}:
            raise ValueError("source_role must be user, assistant, tool, or api")
        self.source_quote = _bounded_text(self.source_quote, "source_quote", 1000)
        self.extractor_version = _bounded_text(
            self.extractor_version, "extractor_version", 64
        )


@dataclass(slots=True)
class MemoryCandidate:
    memory_type: str
    dimension: str
    memory_key: str
    content: str
    scope_type: str
    scope_id: str
    memory_domain: str
    evidence_level: str
    source_session_id: str
    source_message_id: str
    source_role: str
    source_quote: str
    confidence: float = 0.5
    importance: float = 0.5
    sensitivity: str = Sensitivity.NORMAL.value
    structured_data: dict[str, Any] = field(default_factory=dict)
    valid_from: float | None = None
    valid_until: float | None = None
    extractor_name: str = "structured_memory"
    extractor_version: str = "v1"
    extraction_job_key: str = ""
    user_id: str = ""
    id: str = field(default_factory=lambda: new_id("candidate"))
    processing_status: str = CandidateStatus.PENDING.value
    processing_reason: str = ""
    admitted_memory_id: str | None = None
    created_at: float = field(default_factory=time.time)
    processed_at: float | None = None

    def __post_init__(self) -> None:
        # Reuse MemoryRecord's semantic validation without activating the candidate.
        normalized = MemoryRecord(
            id="validation",
            memory_type=self.memory_type,
            dimension=self.dimension,
            memory_key=self.memory_key,
            content=self.content,
            structured_data=self.structured_data,
            scope_type=self.scope_type,
            scope_id=self.scope_id,
            memory_domain=self.memory_domain,
            status=MemoryStatus.CANDIDATE.value,
            evidence_level=self.evidence_level,
            confidence=self.confidence,
            importance=self.importance,
            sensitivity=self.sensitivity,
            user_id=self.user_id,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            source_session_id=self.source_session_id,
            source_message_id=str(self.source_message_id or ""),
        )
        self.memory_type = normalized.memory_type
        self.dimension = normalized.dimension
        self.memory_key = normalized.memory_key
        self.content = normalized.content
        self.structured_data = normalized.structured_data
        self.scope_type = normalized.scope_type
        self.scope_id = normalized.scope_id
        self.memory_domain = normalized.memory_domain
        self.evidence_level = normalized.evidence_level
        self.confidence = normalized.confidence
        self.importance = normalized.importance
        self.sensitivity = normalized.sensitivity
        self.user_id = normalized.user_id
        self.valid_from = normalized.valid_from
        self.valid_until = normalized.valid_until
        self.source_session_id = normalized.source_session_id
        self.source_message_id = normalized.source_message_id
        self.source_role = _bounded_text(self.source_role, "source_role", 32)
        if self.source_role not in {"user", "assistant", "tool", "api"}:
            raise ValueError("source_role must be user, assistant, tool, or api")
        self.source_quote = _bounded_text(self.source_quote, "source_quote", 1000)
        self.processing_status = _enum_value(
            self.processing_status, CandidateStatus, "processing_status"
        )
        self.extractor_name = _bounded_text(self.extractor_name, "extractor_name", 64)
        self.extractor_version = _bounded_text(
            self.extractor_version, "extractor_version", 64
        )
        self.extraction_job_key = _bounded_text(
            self.extraction_job_key, "extraction_job_key", 240, required=False
        )


@dataclass(slots=True)
class DailySummary:
    user_id: str
    local_date: str
    pipeline_version: str
    memory_domain: str
    summary_text: str
    structured_data: dict[str, Any]
    source_from: float | None = None
    source_until: float | None = None
    id: str = field(default_factory=lambda: new_id("daily"))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.memory_domain = _enum_value(
            self.memory_domain, MemoryDomain, "memory_domain"
        )
        self.local_date = _bounded_text(self.local_date, "local_date", 10)
        self.pipeline_version = _bounded_text(
            self.pipeline_version, "pipeline_version", 64
        )
        self.summary_text = _bounded_text(
            self.summary_text, "summary_text", 12000, required=False
        )
        self.structured_data = _json_object(self.structured_data, "structured_data")


@dataclass(slots=True)
class ConsolidationJob:
    user_id: str
    job_type: str
    job_key: str
    pipeline_version: str
    status: str = JobStatus.RUNNING.value
    source_from: float | None = None
    source_until: float | None = None
    attempt_count: int = 1
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error_message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("job"))

    def __post_init__(self) -> None:
        if self.job_type not in {"incremental_extraction", "daily_consolidation"}:
            raise ValueError("unsupported job_type")
        self.status = _enum_value(self.status, JobStatus, "status")
        self.job_key = _bounded_text(self.job_key, "job_key", 300)
        self.pipeline_version = _bounded_text(
            self.pipeline_version, "pipeline_version", 64
        )
        self.error_message = _bounded_text(
            self.error_message, "error_message", 1000, required=False
        )
        self.result = _json_object(self.result, "result")
