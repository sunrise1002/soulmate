"""Verify migrations, repositories, decision history, and durable job recovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from soulmate_core.domain import (
    AuditEvent,
    Conversation,
    Evidence,
    EvidenceTargetType,
    Job,
    JobStatus,
    Message,
    MessageRole,
    Profile,
    RawEvent,
    Source,
)
from soulmate_core.preferences import ModelRebuilder
from soulmate_daemon.jobs import DurableJobWorker
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import inspect, text
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
        "evidence",
        "evidence_revisions",
        "preferences",
        "facts",
        "goals",
        "constraints",
        "user_model_snapshots",
        "audit_events",
        "jobs",
        "system_metadata",
        "alembic_version",
        "conversations",
        "messages",
        "decision_events",
        "decision_options",
        "decision_predictions",
        "decision_resolutions",
    } == tables
    check = database.check()
    assert check.integrity == "ok"
    assert check.journal_mode == "wal"
    assert check.foreign_keys is True
    assert check.current_revision == check.head_revision == "0004_phase_4"
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


def test_phase_1_database_upgrades_without_losing_base_records(tmp_path: Path) -> None:
    path = tmp_path / "decision-twin.db"
    database = Database(path)
    database.connect()
    command.upgrade(database.migration_config, "0001_phase_1")
    assert database.session_factory is not None
    repositories = Repositories(database.session_factory)
    now = datetime.now(UTC)
    profile = Profile("profile_preserved", "Synthetic Owner", now)
    repositories.profiles.add(profile)

    database.migrate()

    assert repositories.profiles.get(profile.id) == profile
    assert database.current_revision() == "0004_phase_4"
    database.close()


def test_phase_2_database_upgrades_without_losing_evidence_or_model_state(tmp_path: Path) -> None:
    path = tmp_path / "decision-twin.db"
    database = Database(path)
    database.connect()
    command.upgrade(database.migration_config, "0002_phase_2")
    assert database.engine is not None
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO profiles (id, display_name, created_at) "
                "VALUES (:id, NULL, :created_at)"
            ),
            {"id": "profile_preserved", "created_at": now.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO raw_events "
                "(id, profile_id, source_id, event_type, content_json, created_at, "
                "ingested_at, sensitivity) VALUES "
                "(:id, :profile_id, NULL, 'synthetic', '{}', :created_at, :created_at, 'normal')"
            ),
            {
                "id": "event_preserved",
                "profile_id": "profile_preserved",
                "created_at": now.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO evidence "
                "(id, profile_id, target_type, target_key, value_json, strength, confidence, "
                "context_json, source_type, source_event_id, extractor_version, created_at) "
                "VALUES (:id, :profile_id, 'preference', 'work.remote', '0.8', 1, 1, '{}', "
                "'explicit_statement', :event_id, 'phase-2-test', :created_at)"
            ),
            {
                "id": "evidence_preserved",
                "profile_id": "profile_preserved",
                "event_id": "event_preserved",
                "created_at": now.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO preferences "
                "(profile_id, key, context_key, value, uncertainty, confidence, context_json, "
                "supporting_evidence_ids_json, updated_at, model_version) VALUES "
                "(:profile_id, 'work.remote', '{}', 0.8, 0.2, 0.8, '{}', "
                "'[\"evidence_preserved\"]', :updated_at, 1)"
            ),
            {"profile_id": "profile_preserved", "updated_at": now.isoformat()},
        )

    database.migrate()

    with database.engine.connect() as connection:
        evidence = connection.execute(
            text(
                "SELECT extractor_version, extractor_model, source_message_id "
                "FROM evidence WHERE id = 'evidence_preserved'"
            )
        ).one()
        preference_count = connection.execute(
            text("SELECT count(*) FROM preferences WHERE profile_id = 'profile_preserved'")
        ).scalar_one()
    assert evidence == ("phase-2-test", None, None)
    assert preference_count == 1
    assert database.current_revision() == "0004_phase_4"
    database.close()


def test_phase_3_database_upgrades_without_losing_conversation_provenance(tmp_path: Path) -> None:
    path = tmp_path / "decision-twin.db"
    database = Database(path)
    database.connect()
    command.upgrade(database.migration_config, "0003_phase_3")
    assert database.session_factory is not None
    repositories = Repositories(database.session_factory)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    profile = Profile("profile_preserved", None, now)
    conversation = Conversation("conversation_preserved", profile.id, now, now)
    message = Message(
        "message_preserved", conversation.id, MessageRole.USER, "Synthetic preference", now
    )
    event = RawEvent("event_preserved", profile.id, None, "conversation_message", {}, now, now)
    repositories.profiles.add(profile)
    repositories.conversations.add(conversation)
    repositories.messages.add(message)
    repositories.raw_events.add(event)
    repositories.evidence.add(
        Evidence(
            "evidence_preserved",
            profile.id,
            EvidenceTargetType.PREFERENCE,
            "work.remote",
            0.8,
            1.0,
            1.0,
            {},
            "explicit_statement",
            event.id,
            "phase-3-test",
            now,
            source_message_id=message.id,
        )
    )

    database.migrate()

    assert repositories.messages.get(message.id) == message
    assert repositories.evidence.get("evidence_preserved") is not None
    assert database.current_revision() == "0004_phase_4"
    database.close()


def test_evidence_rebuild_persists_provenance_snapshots_and_removal(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    profile = Profile("profile_test", "Synthetic Owner", now)
    repositories.profiles.add(profile)
    for index, value in enumerate((0.8, -0.4), start=1):
        event = RawEvent(
            id=f"event_{index}",
            profile_id=profile.id,
            source_id=None,
            event_type="synthetic_preference",
            content={"value": value},
            created_at=now + timedelta(seconds=index),
            ingested_at=now + timedelta(seconds=index),
        )
        repositories.raw_events.add(event)
        repositories.evidence.add(
            Evidence(
                id=f"evidence_{index}",
                profile_id=profile.id,
                target_type=EvidenceTargetType.PREFERENCE,
                target_key="work.remote",
                value=value,
                strength=1.0,
                confidence=1.0,
                context={"domain": "career"},
                source_type="explicit_statement" if index == 1 else "user_correction",
                source_event_id=event.id,
                extractor_version="synthetic-v1",
                created_at=event.created_at,
            )
        )

    rebuilder = ModelRebuilder(repositories.evidence, repositories.personal_models)
    first = rebuilder.rebuild(profile.id, now + timedelta(minutes=1))
    assert first.version == 1
    assert first.evidence_revision == 2
    assert len(first.model.preferences) == 1
    assert first.model.preferences[0].supporting_evidence_ids == (
        "evidence_1",
        "evidence_2",
    )
    corrected_value = first.model.preferences[0].value

    assert repositories.evidence.remove("evidence_2") is True
    second = rebuilder.rebuild(profile.id, now + timedelta(minutes=2))
    assert second.version == 2
    assert second.evidence_revision == 3
    assert second.model.preferences[0].value == pytest.approx(0.8)
    assert second.model.preferences[0].value != corrected_value
    assert repositories.personal_models.latest_snapshot(profile.id) == second
    database.close()


def test_evidence_requires_provenance_from_same_profile(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime.now(UTC)
    repositories.profiles.add(Profile("profile_one", None, now))
    repositories.profiles.add(Profile("profile_two", None, now))
    repositories.raw_events.add(
        RawEvent("event_one", "profile_one", None, "synthetic", {}, now, now)
    )
    evidence = Evidence(
        "evidence_bad",
        "profile_two",
        EvidenceTargetType.FACT,
        "owner.region",
        "south",
        1.0,
        1.0,
        {},
        "user_correction",
        "event_one",
        "synthetic-v1",
        now,
    )
    with pytest.raises(ValueError, match="same profile"):
        repositories.evidence.add(evidence)
    database.close()


def test_all_derived_state_types_persist_in_snapshot(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    profile = Profile("profile_model", None, now)
    repositories.profiles.add(profile)
    cases = (
        (EvidenceTargetType.FACT, "owner.region", "south"),
        (EvidenceTargetType.PREFERENCE, "work.remote", 0.8),
        (EvidenceTargetType.GOAL, "career.leadership", "become_lead"),
        (EvidenceTargetType.CONSTRAINT, "work.travel", "monthly_max"),
    )
    for index, (target_type, key, value) in enumerate(cases):
        event = RawEvent(
            f"event_model_{index}",
            profile.id,
            None,
            "synthetic",
            {},
            now + timedelta(seconds=index),
            now + timedelta(seconds=index),
        )
        repositories.raw_events.add(event)
        repositories.evidence.add(
            Evidence(
                f"evidence_model_{index}",
                profile.id,
                target_type,
                key,
                value,
                1.0,
                1.0,
                {},
                "explicit_statement",
                event.id,
                "synthetic-v1",
                event.created_at,
            )
        )

    snapshot = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
        profile.id, now + timedelta(minutes=1)
    )
    restored = repositories.personal_models.latest_snapshot(profile.id)

    assert restored == snapshot
    assert snapshot.model.facts[0].value == "south"
    assert snapshot.model.preferences[0].value == pytest.approx(0.8)
    assert snapshot.model.goals[0].value == "become_lead"
    assert snapshot.model.constraints[0].value == "monthly_max"
    database.close()


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
