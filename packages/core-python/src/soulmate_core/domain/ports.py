"""Infrastructure-independent repository contracts."""

from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from soulmate_core.domain.models import (
    AuditEvent,
    Conversation,
    DerivedModel,
    Evidence,
    Job,
    Message,
    Preference,
    Profile,
    RawEvent,
    Source,
    UserModelSnapshot,
)


class ProfileRepository(Protocol):
    def add(self, profile: Profile) -> None: ...

    def get(self, profile_id: str) -> Profile | None: ...


class SourceRepository(Protocol):
    def add(self, source: Source) -> None: ...

    def get(self, source_id: str) -> Source | None: ...


class RawEventRepository(Protocol):
    def add(self, event: RawEvent) -> None: ...

    def get(self, event_id: str) -> RawEvent | None: ...


class ConversationRepository(Protocol):
    def add(self, conversation: Conversation) -> None: ...

    def get(self, conversation_id: str) -> Conversation | None: ...

    def touch(self, conversation_id: str, updated_at: datetime) -> None: ...


class MessageRepository(Protocol):
    def add(self, message: Message) -> None: ...

    def get(self, message_id: str) -> Message | None: ...

    def list_for_conversation(self, conversation_id: str) -> tuple[Message, ...]: ...


class EvidenceRepository(Protocol):
    def add(self, evidence: Evidence) -> None: ...

    def get(self, evidence_id: str) -> Evidence | None: ...

    def list_for_profile(self, profile_id: str) -> tuple[Evidence, ...]: ...

    def list_for_profile_with_revision(
        self, profile_id: str
    ) -> tuple[tuple[Evidence, ...], int]: ...

    def list_for_target(self, profile_id: str, target_key: str) -> tuple[Evidence, ...]: ...

    def remove(self, evidence_id: str) -> bool: ...

    def current_revision(self, profile_id: str) -> int: ...


class PersonalModelRepository(Protocol):
    def replace(
        self,
        profile_id: str,
        model: DerivedModel,
        evidence_revision: int,
        algorithm_version: str,
        created_at: datetime,
    ) -> UserModelSnapshot: ...

    def latest_snapshot(self, profile_id: str) -> UserModelSnapshot | None: ...

    def list_preferences(self, profile_id: str) -> tuple[Preference, ...]: ...

    def get_preferences(self, profile_id: str, key: str) -> tuple[Preference, ...]: ...


class AuditEventRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...

    def get(self, event_id: str) -> AuditEvent | None: ...


class JobRepository(Protocol):
    def enqueue(self, job: Job) -> None: ...

    def get(self, job_id: str) -> Job | None: ...

    def claim_next(
        self, now: datetime, stale_before: datetime, job_types: Collection[str]
    ) -> Job | None: ...

    def mark_succeeded(self, job_id: str, completed_at: datetime) -> None: ...

    def mark_failed(self, job_id: str, error: str, failed_at: datetime) -> None: ...


class SystemMetadataRepository(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, updated_at: datetime) -> None: ...

    def get_or_create(self, key: str, value: str, updated_at: datetime) -> str: ...
