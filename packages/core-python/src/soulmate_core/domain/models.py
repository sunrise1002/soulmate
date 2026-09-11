"""Phase 1 domain records shared by persistence ports and application services."""

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
    """Immutable input envelope; interpretation begins in Phase 2."""

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
