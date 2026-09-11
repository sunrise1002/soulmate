"""Domain records shared by persistence ports and application services."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


def _require_utc_aware(*values: datetime | None) -> None:
    if any(
        value is not None and (value.tzinfo is None or value.utcoffset() is None)
        for value in values
    ):
        raise ValueError("Domain timestamps must be timezone-aware.")


class JobStatus(StrEnum):
    """Durable job lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvidenceTargetType(StrEnum):
    """Kinds of derived Personal Model state supported by evidence."""

    FACT = "fact"
    PREFERENCE = "preference"
    GOAL = "goal"
    CONSTRAINT = "constraint"


class MessageRole(StrEnum):
    """Conversation roles persisted by the provider-neutral kernel."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Profile:
    id: str
    display_name: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    profile_id: str
    source_type: str
    name: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class RawEvent:
    """Immutable input envelope for learning inputs."""

    id: str
    profile_id: str
    source_id: str | None
    event_type: str
    content: dict[str, Any]
    created_at: datetime
    ingested_at: datetime
    sensitivity: str = "normal"

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.ingested_at)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    profile_id: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.updated_at)


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime
    provider_model: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.content:
            raise ValueError("Message content must not be empty.")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Immutable, provenance-bearing claim used to derive Personal Model state."""

    id: str
    profile_id: str
    target_type: EvidenceTargetType
    target_key: str
    value: object
    strength: float
    confidence: float
    context: dict[str, object]
    source_type: str
    source_event_id: str
    extractor_version: str
    created_at: datetime
    extractor_model: str | None = None
    source_message_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.target_key:
            raise ValueError("Evidence target_key must not be empty.")
        if not self.source_type or not self.source_event_id or not self.extractor_version:
            raise ValueError("Evidence provenance fields must not be empty.")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("Evidence strength must be between 0 and 1.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Evidence confidence must be between 0 and 1.")
        if self.target_type is EvidenceTargetType.PREFERENCE and (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not -1.0 <= float(self.value) <= 1.0
        ):
            raise ValueError("Preference evidence value must be numeric and between -1 and 1.")


@dataclass(frozen=True, slots=True)
class Preference:
    key: str
    value: float
    uncertainty: float
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class Fact:
    key: str
    value: object
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class Goal:
    key: str
    value: object
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class Constraint:
    key: str
    value: object
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class DerivedModel:
    """Deterministically aggregated model content before persistence versioning."""

    preferences: tuple[Preference, ...]
    facts: tuple[Fact, ...]
    goals: tuple[Goal, ...]
    constraints: tuple[Constraint, ...]


@dataclass(frozen=True, slots=True)
class UserModelSnapshot:
    profile_id: str
    version: int
    algorithm_version: str
    evidence_revision: int
    model: DerivedModel
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    action: str
    actor_type: str
    created_at: datetime
    profile_id: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    job_type: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    locked_at: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.available_at, self.created_at, self.updated_at, self.locked_at)
