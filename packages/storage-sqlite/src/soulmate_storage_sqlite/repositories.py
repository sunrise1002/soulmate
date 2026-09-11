"""SQLAlchemy implementations of Soulmate repository ports."""

import json
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from soulmate_core.domain.models import (
    AuditEvent,
    Constraint,
    Conversation,
    DerivedModel,
    Evidence,
    EvidenceTargetType,
    Fact,
    Goal,
    Job,
    JobStatus,
    Message,
    MessageRole,
    Preference,
    Profile,
    RawEvent,
    Source,
    UserModelSnapshot,
)
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from soulmate_storage_sqlite.schema import (
    AuditEventRow,
    ConstraintRow,
    ConversationRow,
    EvidenceRevisionRow,
    EvidenceRow,
    FactRow,
    GoalRow,
    JobRow,
    MessageRow,
    PreferenceRow,
    ProfileRow,
    RawEventRow,
    SourceRow,
    SystemMetadataRow,
    UserModelSnapshotRow,
)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqliteProfileRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, profile: Profile) -> None:
        with self._sessions.begin() as session:
            session.add(
                ProfileRow(
                    id=profile.id,
                    display_name=profile.display_name,
                    created_at=profile.created_at,
                )
            )

    def get(self, profile_id: str) -> Profile | None:
        with self._sessions() as session:
            row = session.get(ProfileRow, profile_id)
            if row is None:
                return None
            return Profile(row.id, row.display_name, _utc(row.created_at))


class SqliteSourceRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, source: Source) -> None:
        with self._sessions.begin() as session:
            session.add(
                SourceRow(
                    id=source.id,
                    profile_id=source.profile_id,
                    source_type=source.source_type,
                    name=source.name,
                    created_at=source.created_at,
                )
            )

    def get(self, source_id: str) -> Source | None:
        with self._sessions() as session:
            row = session.get(SourceRow, source_id)
            if row is None:
                return None
            return Source(row.id, row.profile_id, row.source_type, row.name, _utc(row.created_at))


class SqliteRawEventRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, event: RawEvent) -> None:
        with self._sessions.begin() as session:
            session.add(
                RawEventRow(
                    id=event.id,
                    profile_id=event.profile_id,
                    source_id=event.source_id,
                    event_type=event.event_type,
                    content_json=_json_dump(event.content),
                    created_at=event.created_at,
                    ingested_at=event.ingested_at,
                    sensitivity=event.sensitivity,
                )
            )

    def get(self, event_id: str) -> RawEvent | None:
        with self._sessions() as session:
            row = session.get(RawEventRow, event_id)
            if row is None:
                return None
            return RawEvent(
                id=row.id,
                profile_id=row.profile_id,
                source_id=row.source_id,
                event_type=row.event_type,
                content=json.loads(row.content_json),
                created_at=_utc(row.created_at),
                ingested_at=_utc(row.ingested_at),
                sensitivity=row.sensitivity,
            )


class SqliteConversationRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, conversation: Conversation) -> None:
        with self._sessions.begin() as session:
            session.add(
                ConversationRow(
                    id=conversation.id,
                    profile_id=conversation.profile_id,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                )
            )

    def get(self, conversation_id: str) -> Conversation | None:
        with self._sessions() as session:
            row = session.get(ConversationRow, conversation_id)
            if row is None:
                return None
            return Conversation(row.id, row.profile_id, _utc(row.created_at), _utc(row.updated_at))

    def touch(self, conversation_id: str, updated_at: datetime) -> None:
        with self._sessions.begin() as session:
            updated_id = session.execute(
                update(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .values(updated_at=updated_at)
                .returning(ConversationRow.id)
            ).scalar_one_or_none()
            if updated_id is None:
                raise KeyError(conversation_id)


class SqliteMessageRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, message: Message) -> None:
        with self._sessions.begin() as session:
            session.add(
                MessageRow(
                    id=message.id,
                    conversation_id=message.conversation_id,
                    role=message.role.value,
                    content=message.content,
                    provider_model=message.provider_model,
                    created_at=message.created_at,
                )
            )

    def get(self, message_id: str) -> Message | None:
        with self._sessions() as session:
            row = session.get(MessageRow, message_id)
            return None if row is None else self._to_domain(row)

    def list_for_conversation(self, conversation_id: str) -> tuple[Message, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.created_at, MessageRow.id)
            )
            return tuple(self._to_domain(row) for row in rows)

    @staticmethod
    def _to_domain(row: MessageRow) -> Message:
        return Message(
            id=row.id,
            conversation_id=row.conversation_id,
            role=MessageRole(row.role),
            content=row.content,
            provider_model=row.provider_model,
            created_at=_utc(row.created_at),
        )


class SqliteEvidenceRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    @staticmethod
    def _bump_revision(session: Session, profile_id: str) -> None:
        statement = insert(EvidenceRevisionRow).values(profile_id=profile_id, revision=1)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[EvidenceRevisionRow.profile_id],
                set_={"revision": EvidenceRevisionRow.revision + 1},
            )
        )

    def add(self, evidence: Evidence) -> None:
        with self._sessions.begin() as session:
            source_event = session.get(RawEventRow, evidence.source_event_id)
            if source_event is None or source_event.profile_id != evidence.profile_id:
                raise ValueError("Evidence source event must belong to the same profile.")
            if evidence.source_message_id is not None:
                source_message = session.get(MessageRow, evidence.source_message_id)
                conversation = (
                    None
                    if source_message is None
                    else session.get(ConversationRow, source_message.conversation_id)
                )
                if conversation is None or conversation.profile_id != evidence.profile_id:
                    raise ValueError("Evidence source message must belong to the same profile.")
            session.add(
                EvidenceRow(
                    id=evidence.id,
                    profile_id=evidence.profile_id,
                    target_type=evidence.target_type.value,
                    target_key=evidence.target_key,
                    value_json=_json_dump(evidence.value),
                    strength=evidence.strength,
                    confidence=evidence.confidence,
                    context_json=_json_dump(evidence.context),
                    source_type=evidence.source_type,
                    source_event_id=evidence.source_event_id,
                    extractor_version=evidence.extractor_version,
                    extractor_model=evidence.extractor_model,
                    source_message_id=evidence.source_message_id,
                    created_at=evidence.created_at,
                )
            )
            self._bump_revision(session, evidence.profile_id)

    def get(self, evidence_id: str) -> Evidence | None:
        with self._sessions() as session:
            row = session.get(EvidenceRow, evidence_id)
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[Evidence, ...]:
        return self.list_for_profile_with_revision(profile_id)[0]

    def list_for_profile_with_revision(self, profile_id: str) -> tuple[tuple[Evidence, ...], int]:
        with self._sessions() as session:
            rows = session.scalars(
                select(EvidenceRow)
                .where(EvidenceRow.profile_id == profile_id)
                .order_by(EvidenceRow.created_at, EvidenceRow.id)
            )
            evidence = tuple(self._to_domain(row) for row in rows)
            revision = session.get(EvidenceRevisionRow, profile_id)
            return evidence, 0 if revision is None else revision.revision

    def list_for_target(self, profile_id: str, target_key: str) -> tuple[Evidence, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(EvidenceRow)
                .where(
                    EvidenceRow.profile_id == profile_id,
                    EvidenceRow.target_key == target_key,
                )
                .order_by(EvidenceRow.created_at, EvidenceRow.id)
            )
            return tuple(self._to_domain(row) for row in rows)

    def remove(self, evidence_id: str) -> bool:
        with self._sessions.begin() as session:
            row = session.get(EvidenceRow, evidence_id)
            if row is None:
                return False
            profile_id = row.profile_id
            session.delete(row)
            self._bump_revision(session, profile_id)
            return True

    def current_revision(self, profile_id: str) -> int:
        with self._sessions() as session:
            row = session.get(EvidenceRevisionRow, profile_id)
            return 0 if row is None else row.revision

    @staticmethod
    def _to_domain(row: EvidenceRow) -> Evidence:
        return Evidence(
            id=row.id,
            profile_id=row.profile_id,
            target_type=EvidenceTargetType(row.target_type),
            target_key=row.target_key,
            value=json.loads(row.value_json),
            strength=row.strength,
            confidence=row.confidence,
            context=json.loads(row.context_json),
            source_type=row.source_type,
            source_event_id=row.source_event_id,
            extractor_version=row.extractor_version,
            created_at=_utc(row.created_at),
            extractor_model=row.extractor_model,
            source_message_id=row.source_message_id,
        )


def _record_json(record: Preference | Fact | Goal | Constraint) -> dict[str, object]:
    value: object = record.value
    result: dict[str, object] = {
        "key": record.key,
        "value": value,
        "confidence": record.confidence,
        "context": record.context,
        "supporting_evidence_ids": list(record.supporting_evidence_ids),
        "updated_at": record.updated_at.isoformat(),
        "model_version": record.model_version,
    }
    if isinstance(record, Preference):
        result["uncertainty"] = record.uncertainty
    return result


def _model_json(model: DerivedModel) -> dict[str, object]:
    return {
        "preferences": [_record_json(item) for item in model.preferences],
        "facts": [_record_json(item) for item in model.facts],
        "goals": [_record_json(item) for item in model.goals],
        "constraints": [_record_json(item) for item in model.constraints],
    }


class SqlitePersonalModelRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def replace(
        self,
        profile_id: str,
        model: DerivedModel,
        evidence_revision: int,
        algorithm_version: str,
        created_at: datetime,
    ) -> UserModelSnapshot:
        with self._sessions.begin() as session:
            previous = session.scalar(
                select(func.max(UserModelSnapshotRow.version)).where(
                    UserModelSnapshotRow.profile_id == profile_id
                )
            )
            version = (previous or 0) + 1
            versioned = DerivedModel(
                preferences=tuple(
                    replace(item, model_version=version) for item in model.preferences
                ),
                facts=tuple(replace(item, model_version=version) for item in model.facts),
                goals=tuple(replace(item, model_version=version) for item in model.goals),
                constraints=tuple(
                    replace(item, model_version=version) for item in model.constraints
                ),
            )
            for row_type in (PreferenceRow, FactRow, GoalRow, ConstraintRow):
                session.execute(delete(row_type).where(row_type.profile_id == profile_id))
            session.add_all(
                [
                    PreferenceRow(
                        profile_id=profile_id,
                        key=item.key,
                        context_key=_json_dump(item.context),
                        value=item.value,
                        uncertainty=item.uncertainty,
                        confidence=item.confidence,
                        context_json=_json_dump(item.context),
                        supporting_evidence_ids_json=_json_dump(item.supporting_evidence_ids),
                        updated_at=item.updated_at,
                        model_version=version,
                    )
                    for item in versioned.preferences
                ]
            )
            self._add_categorical(session, profile_id, versioned.facts, FactRow)
            self._add_categorical(session, profile_id, versioned.goals, GoalRow)
            self._add_categorical(session, profile_id, versioned.constraints, ConstraintRow)
            session.add(
                UserModelSnapshotRow(
                    profile_id=profile_id,
                    version=version,
                    algorithm_version=algorithm_version,
                    evidence_revision=evidence_revision,
                    model_json=_json_dump(_model_json(versioned)),
                    created_at=created_at,
                )
            )
        return UserModelSnapshot(
            profile_id=profile_id,
            version=version,
            algorithm_version=algorithm_version,
            evidence_revision=evidence_revision,
            model=versioned,
            created_at=created_at,
        )

    @staticmethod
    def _add_categorical(
        session: Session,
        profile_id: str,
        records: tuple[Fact, ...] | tuple[Goal, ...] | tuple[Constraint, ...],
        row_type: type[FactRow] | type[GoalRow] | type[ConstraintRow],
    ) -> None:
        session.add_all(
            [
                row_type(
                    profile_id=profile_id,
                    key=item.key,
                    context_key=_json_dump(item.context),
                    value_json=_json_dump(item.value),
                    confidence=item.confidence,
                    context_json=_json_dump(item.context),
                    supporting_evidence_ids_json=_json_dump(item.supporting_evidence_ids),
                    updated_at=item.updated_at,
                    model_version=item.model_version,
                )
                for item in records
            ]
        )

    def latest_snapshot(self, profile_id: str) -> UserModelSnapshot | None:
        with self._sessions() as session:
            row = session.scalar(
                select(UserModelSnapshotRow)
                .where(UserModelSnapshotRow.profile_id == profile_id)
                .order_by(UserModelSnapshotRow.version.desc())
                .limit(1)
            )
            return None if row is None else self._snapshot_to_domain(row)

    def list_preferences(self, profile_id: str) -> tuple[Preference, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(PreferenceRow)
                .where(PreferenceRow.profile_id == profile_id)
                .order_by(PreferenceRow.key, PreferenceRow.context_key)
            )
            return tuple(self._preference_to_domain(row) for row in rows)

    def get_preferences(self, profile_id: str, key: str) -> tuple[Preference, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(PreferenceRow)
                .where(PreferenceRow.profile_id == profile_id, PreferenceRow.key == key)
                .order_by(PreferenceRow.context_key)
            )
            return tuple(self._preference_to_domain(row) for row in rows)

    @staticmethod
    def _preference_to_domain(row: PreferenceRow) -> Preference:
        return Preference(
            key=row.key,
            value=row.value,
            uncertainty=row.uncertainty,
            confidence=row.confidence,
            context=json.loads(row.context_json),
            supporting_evidence_ids=tuple(json.loads(row.supporting_evidence_ids_json)),
            updated_at=_utc(row.updated_at),
            model_version=row.model_version,
        )

    @classmethod
    def _snapshot_to_domain(cls, row: UserModelSnapshotRow) -> UserModelSnapshot:
        content = cast(dict[str, list[dict[str, object]]], json.loads(row.model_json))
        model = DerivedModel(
            preferences=tuple(cls._preference_from_json(item) for item in content["preferences"]),
            facts=tuple(cls._categorical_from_json(Fact, item) for item in content["facts"]),
            goals=tuple(cls._categorical_from_json(Goal, item) for item in content["goals"]),
            constraints=tuple(
                cls._categorical_from_json(Constraint, item) for item in content["constraints"]
            ),
        )
        return UserModelSnapshot(
            profile_id=row.profile_id,
            version=row.version,
            algorithm_version=row.algorithm_version,
            evidence_revision=row.evidence_revision,
            model=model,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _preference_from_json(item: dict[str, object]) -> Preference:
        return Preference(
            key=str(item["key"]),
            value=cast(float, item["value"]),
            uncertainty=cast(float, item["uncertainty"]),
            confidence=cast(float, item["confidence"]),
            context=cast(dict[str, object], item["context"]),
            supporting_evidence_ids=tuple(cast(list[str], item["supporting_evidence_ids"])),
            updated_at=datetime.fromisoformat(str(item["updated_at"])),
            model_version=cast(int, item["model_version"]),
        )

    @staticmethod
    def _categorical_from_json[DerivedRecord: (Fact, Goal, Constraint)](
        record_type: type[DerivedRecord], item: dict[str, object]
    ) -> DerivedRecord:
        return record_type(
            key=str(item["key"]),
            value=item["value"],
            confidence=cast(float, item["confidence"]),
            context=cast(dict[str, object], item["context"]),
            supporting_evidence_ids=tuple(cast(list[str], item["supporting_evidence_ids"])),
            updated_at=datetime.fromisoformat(str(item["updated_at"])),
            model_version=cast(int, item["model_version"]),
        )


class SqliteAuditEventRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, event: AuditEvent) -> None:
        with self._sessions.begin() as session:
            session.add(
                AuditEventRow(
                    id=event.id,
                    profile_id=event.profile_id,
                    action=event.action,
                    actor_type=event.actor_type,
                    actor_id=event.actor_id,
                    metadata_json=None if event.metadata is None else _json_dump(event.metadata),
                    created_at=event.created_at,
                )
            )

    def get(self, event_id: str) -> AuditEvent | None:
        with self._sessions() as session:
            row = session.get(AuditEventRow, event_id)
            if row is None:
                return None
            metadata = None if row.metadata_json is None else json.loads(row.metadata_json)
            return AuditEvent(
                id=row.id,
                action=row.action,
                actor_type=row.actor_type,
                created_at=_utc(row.created_at),
                profile_id=row.profile_id,
                actor_id=row.actor_id,
                metadata=metadata,
            )


class SqliteJobRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def enqueue(self, job: Job) -> None:
        with self._sessions.begin() as session:
            session.add(
                JobRow(
                    id=job.id,
                    job_type=job.job_type,
                    payload_json=_json_dump(job.payload),
                    status=job.status.value,
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                    available_at=job.available_at,
                    locked_at=job.locked_at,
                    last_error=job.last_error,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                )
            )

    def get(self, job_id: str) -> Job | None:
        with self._sessions() as session:
            row = session.get(JobRow, job_id)
            return None if row is None else self._to_domain(row)

    def claim_next(
        self, now: datetime, stale_before: datetime, job_types: Collection[str]
    ) -> Job | None:
        if not job_types:
            return None
        claimable = and_(
            JobRow.job_type.in_(job_types),
            JobRow.attempts < JobRow.max_attempts,
            or_(
                and_(JobRow.status == JobStatus.QUEUED.value, JobRow.available_at <= now),
                and_(JobRow.status == JobStatus.RUNNING.value, JobRow.locked_at < stale_before),
            ),
        )
        candidate = (
            select(JobRow.id)
            .where(claimable)
            .order_by(
                case((JobRow.status == JobStatus.QUEUED.value, 0), else_=1),
                JobRow.available_at,
                JobRow.created_at,
            )
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(JobRow)
            .where(JobRow.id == candidate, claimable)
            .values(
                status=JobStatus.RUNNING.value,
                attempts=JobRow.attempts + 1,
                locked_at=now,
                updated_at=now,
                last_error=None,
            )
            .returning(JobRow)
        )
        with self._sessions.begin() as session:
            session.execute(
                update(JobRow)
                .where(
                    JobRow.status == JobStatus.RUNNING.value,
                    JobRow.locked_at < stale_before,
                    JobRow.attempts >= JobRow.max_attempts,
                )
                .values(
                    status=JobStatus.FAILED.value,
                    locked_at=None,
                    last_error="Worker interrupted during final attempt",
                    updated_at=now,
                )
            )
            row = session.execute(statement).scalar_one_or_none()
            return None if row is None else self._to_domain(row)

    def mark_succeeded(self, job_id: str, completed_at: datetime) -> None:
        self._finish(job_id, completed_at, JobStatus.SUCCEEDED, None)

    def mark_failed(self, job_id: str, error: str, failed_at: datetime) -> None:
        with self._sessions.begin() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            row.status = (
                JobStatus.FAILED.value
                if row.attempts >= row.max_attempts
                else JobStatus.QUEUED.value
            )
            row.locked_at = None
            row.last_error = error
            row.updated_at = failed_at

    def _finish(self, job_id: str, now: datetime, status: JobStatus, error: str | None) -> None:
        with self._sessions.begin() as session:
            updated_id = session.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(status=status.value, locked_at=None, last_error=error, updated_at=now)
                .returning(JobRow.id)
            ).scalar_one_or_none()
            if updated_id is None:
                raise KeyError(job_id)

    @staticmethod
    def _to_domain(row: JobRow) -> Job:
        return Job(
            id=row.id,
            job_type=row.job_type,
            payload=json.loads(row.payload_json),
            status=JobStatus(row.status),
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            available_at=_utc(row.available_at),
            locked_at=None if row.locked_at is None else _utc(row.locked_at),
            last_error=row.last_error,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )


class SqliteSystemMetadataRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, key: str) -> str | None:
        with self._sessions() as session:
            row = session.get(SystemMetadataRow, key)
            return None if row is None else row.value

    def set(self, key: str, value: str, updated_at: datetime) -> None:
        with self._sessions.begin() as session:
            row = session.get(SystemMetadataRow, key)
            if row is None:
                session.add(SystemMetadataRow(key=key, value=value, updated_at=updated_at))
            else:
                row.value = value
                row.updated_at = updated_at

    def get_or_create(self, key: str, value: str, updated_at: datetime) -> str:
        with self._sessions.begin() as session:
            session.execute(
                insert(SystemMetadataRow)
                .values(key=key, value=value, updated_at=updated_at)
                .on_conflict_do_nothing(index_elements=[SystemMetadataRow.key])
            )
            stored = session.get(SystemMetadataRow, key)
            if stored is None:
                raise RuntimeError("System metadata could not be initialized.")
            return stored.value


class Repositories:
    """Convenient adapter collection for daemon composition."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.profiles = SqliteProfileRepository(sessions)
        self.sources = SqliteSourceRepository(sessions)
        self.raw_events = SqliteRawEventRepository(sessions)
        self.conversations = SqliteConversationRepository(sessions)
        self.messages = SqliteMessageRepository(sessions)
        self.evidence = SqliteEvidenceRepository(sessions)
        self.personal_models = SqlitePersonalModelRepository(sessions)
        self.audit_events = SqliteAuditEventRepository(sessions)
        self.jobs = SqliteJobRepository(sessions)
        self.system_metadata = SqliteSystemMetadataRepository(sessions)
