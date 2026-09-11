"""SQLAlchemy implementations of Phase 1 repository ports."""

import json
from collections.abc import Collection
from datetime import UTC, datetime

from soulmate_core.domain.models import AuditEvent, Job, JobStatus, Profile, RawEvent, Source
from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from soulmate_storage_sqlite.schema import (
    AuditEventRow,
    JobRow,
    ProfileRow,
    RawEventRow,
    SourceRow,
    SystemMetadataRow,
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
        self.audit_events = SqliteAuditEventRepository(sessions)
        self.jobs = SqliteJobRepository(sessions)
        self.system_metadata = SqliteSystemMetadataRepository(sessions)
