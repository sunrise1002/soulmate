"""Verify migrations, repository behavior, constraints, and durable job recovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from soulmate_core.domain import AuditEvent, Job, JobStatus, Profile, RawEvent, Source
from soulmate_daemon.jobs import DurableJobWorker
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def _storage(tmp_path: Path) -> tuple[Database, Repositories]:
    database = Database(tmp_path / "data" / "decision-twin.db")
    database.migrate()
    assert database.session_factory is not None
    return database, Repositories(database.session_factory)


def test_initial_migration_creates_base_tables_and_required_pragmas(tmp_path: Path) -> None:
    database, _ = _storage(tmp_path)
    assert database.engine is not None
    tables = set(inspect(database.engine).get_table_names())
    assert {
        "profiles",
        "sources",
        "raw_events",
        "audit_events",
        "jobs",
        "system_metadata",
        "alembic_version",
    } == tables
    check = database.check()
    assert check.integrity == "ok"
    assert check.journal_mode == "wal"
    assert check.foreign_keys is True
    assert check.current_revision == check.head_revision == "0001_phase_1"
    database.close()


def test_foreign_keys_are_enforced_on_every_repository_connection(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError):
        repositories.sources.add(Source("source_orphan", "missing", "manual", "Orphan", now))
    database.close()


def test_base_repositories_round_trip_structured_records(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime.now(UTC)
    profile = Profile("profile_test", "Synthetic Owner", now)
    source = Source("source_test", profile.id, "manual", "Synthetic source", now)
    event = RawEvent(
        id="event_test",
        profile_id=profile.id,
        source_id=source.id,
        event_type="synthetic",
        content={"private_fixture": "not logged", "value": 1},
        created_at=now,
        ingested_at=now,
    )
    audit_event = AuditEvent(
        id="audit_test",
        profile_id=profile.id,
        action="synthetic.action",
        actor_type="test",
        actor_id=None,
        metadata={"result": "accepted"},
        created_at=now,
    )
    repositories.profiles.add(profile)
    repositories.sources.add(source)
    repositories.raw_events.add(event)
    repositories.audit_events.add(audit_event)
    assert repositories.profiles.get(profile.id) == profile
    assert repositories.sources.get(source.id) == source
    assert repositories.raw_events.get(event.id) == event
    assert repositories.audit_events.get(audit_event.id) == audit_event
    database.close()


def test_migration_is_idempotent_across_database_restart(tmp_path: Path) -> None:
    path = tmp_path / "decision-twin.db"
    first = Database(path)
    first.migrate()
    first.close()
    second = Database(path)
    second.migrate()
    assert second.current_revision() == second.head_revision()
    second.close()


def test_worker_reclaims_stale_job_after_restart(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime.now(UTC)
    repositories.jobs.enqueue(
        Job(
            id="job_restart",
            job_type="synthetic_job",
            payload={"value": "safe-fixture"},
            status=JobStatus.RUNNING,
            attempts=1,
            max_attempts=3,
            available_at=now - timedelta(minutes=10),
            locked_at=now - timedelta(minutes=10),
            last_error=None,
            created_at=now - timedelta(minutes=10),
            updated_at=now - timedelta(minutes=10),
        )
    )
    database.close()

    restarted = Database(tmp_path / "data" / "decision-twin.db")
    restarted.migrate()
    assert restarted.session_factory is not None
    restarted_repositories = Repositories(restarted.session_factory)
    received: list[dict[str, object]] = []

    async def handler(payload: dict[str, object]) -> None:
        received.append(payload)

    worker = DurableJobWorker(
        restarted_repositories.jobs,
        {"synthetic_job": handler},
        lease_timeout=timedelta(seconds=1),
    )
    assert asyncio.run(worker.process_once()) is True
    completed = restarted_repositories.jobs.get("job_restart")
    assert completed is not None
    assert completed.status is JobStatus.SUCCEEDED
    assert completed.attempts == 2
    assert received == [{"value": "safe-fixture"}]
    restarted.close()


def test_worker_retries_without_persisting_exception_message(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime.now(UTC)
    repositories.jobs.enqueue(
        Job(
            id="job_failure",
            job_type="synthetic_job",
            payload={},
            status=JobStatus.QUEUED,
            attempts=0,
            max_attempts=2,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    private_message = "private payload accidentally included by handler"

    async def handler(_payload: dict[str, object]) -> None:
        raise ValueError(private_message)

    worker = DurableJobWorker(repositories.jobs, {"synthetic_job": handler})
    assert asyncio.run(worker.process_once()) is True
    retried = repositories.jobs.get("job_failure")
    assert retried is not None
    assert retried.status is JobStatus.QUEUED
    assert retried.last_error == "Handler failed with ValueError"
    assert private_message not in retried.last_error
    database.close()


def test_worker_marks_interrupted_final_attempt_failed(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime.now(UTC)
    repositories.jobs.enqueue(
        Job(
            id="job_exhausted",
            job_type="synthetic_job",
            payload={},
            status=JobStatus.RUNNING,
            attempts=2,
            max_attempts=2,
            available_at=now - timedelta(minutes=10),
            locked_at=now - timedelta(minutes=10),
            created_at=now - timedelta(minutes=10),
            updated_at=now - timedelta(minutes=10),
        )
    )

    async def handler(_payload: dict[str, object]) -> None:
        pytest.fail("An exhausted job must not run again.")

    worker = DurableJobWorker(
        repositories.jobs,
        {"synthetic_job": handler},
        lease_timeout=timedelta(seconds=1),
    )
    assert asyncio.run(worker.process_once()) is False
    exhausted = repositories.jobs.get("job_exhausted")
    assert exhausted is not None
    assert exhausted.status is JobStatus.FAILED
    assert exhausted.last_error == "Worker interrupted during final attempt"
    database.close()
