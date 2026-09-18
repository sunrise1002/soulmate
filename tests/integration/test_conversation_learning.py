"""Verify retry budget, per-message learning status, and owner retry of failed learning."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from soulmate_core.domain import (
    Conversation,
    Evidence,
    EvidenceRepository,
    EvidenceTargetType,
    Job,
    JobStatus,
    Message,
    MessageRole,
    Profile,
    RawEvent,
)
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.conversation import (
    CONVERSATION_EXTRACTION_JOB,
    EXTRACTION_MAX_ATTEMPTS,
    EXTRACTION_RETRY_DELAY,
    extraction_job_id,
)
from soulmate_daemon.jobs import DurableJobWorker
from soulmate_daemon.learning_api import (
    JOB_NOT_FAILED,
    JOB_NOT_FOUND,
    message_learning,
)
from soulmate_llm_providers import FakeLLMProvider, ProviderUnavailableError
from soulmate_storage_sqlite import Database, Repositories

pytestmark = pytest.mark.integration

PROFILE = "profile_default"
OWNER_CLIENT = ("127.0.0.1", 50000)


def _storage(tmp_path: Path) -> tuple[Database, Repositories]:
    database = Database(tmp_path / "data" / "soulmate.db")
    database.migrate()
    assert database.session_factory is not None
    return database, Repositories(database.session_factory)


def _job(
    message_id: str,
    status: JobStatus,
    *,
    attempts: int = 0,
    profile_id: str = PROFILE,
    available_in: timedelta = timedelta(hours=1),
) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=extraction_job_id(message_id),
        job_type=CONVERSATION_EXTRACTION_JOB,
        payload={
            "profile_id": profile_id,
            "source_event_id": f"event_{message_id}",
            "source_message_id": message_id,
        },
        status=status,
        attempts=attempts,
        max_attempts=EXTRACTION_MAX_ATTEMPTS,
        available_at=now + available_in,
        created_at=now,
        updated_at=now,
        last_error="Handler failed with ProviderUnavailableError"
        if status is JobStatus.FAILED
        else None,
    )


def _source_event(message_id: str) -> RawEvent:
    now = datetime.now(UTC)
    return RawEvent(
        id=f"event_{message_id}",
        profile_id=PROFILE,
        source_id=None,
        event_type="conversation_message",
        content={"message_id": message_id},
        created_at=now,
        ingested_at=now,
    )


def _evidence(message_id: str) -> Evidence:
    return Evidence(
        id=f"evidence_{message_id}",
        profile_id=PROFILE,
        target_type=EvidenceTargetType.PREFERENCE,
        target_key="ui.theme.dark",
        value=0.8,
        strength=0.8,
        confidence=0.95,
        context={},
        source_type="explicit_statement",
        source_event_id=f"event_{message_id}",
        extractor_version="conversation-evidence-v1",
        created_at=datetime.now(UTC),
        source_message_id=message_id,
    )


# --- Job repository: requeue_failed ---------------------------------------------------------


def test_requeue_failed_gives_failed_job_fresh_budget(tmp_path: Path) -> None:
    # Given: an exhausted, failed extraction job
    database, repositories = _storage(tmp_path)
    repositories.jobs.enqueue(_job("message_1", JobStatus.FAILED, attempts=EXTRACTION_MAX_ATTEMPTS))
    now = datetime.now(UTC)

    # When: the failed job is requeued
    requeued = repositories.jobs.requeue_failed(extraction_job_id("message_1"), now)

    # Then: it is queued with no attempts or error and can be claimed immediately
    job = repositories.jobs.get(extraction_job_id("message_1"))
    assert requeued is True
    assert job is not None
    assert job.status is JobStatus.QUEUED
    assert job.attempts == 0
    assert job.last_error is None
    assert job.available_at == now
    claimed = repositories.jobs.claim_next(
        now, now - timedelta(minutes=5), {CONVERSATION_EXTRACTION_JOB}
    )
    assert claimed is not None
    assert claimed.id == extraction_job_id("message_1")
    database.close()


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED])
def test_requeue_failed_leaves_unfailed_job_unchanged(tmp_path: Path, status: JobStatus) -> None:
    # Given: a job that has not failed
    database, repositories = _storage(tmp_path)
    original = _job("message_1", status, attempts=2)
    repositories.jobs.enqueue(original)

    # When: the owner tries to requeue the job
    requeued = repositories.jobs.requeue_failed(original.id, datetime.now(UTC))

    # Then: nothing changes
    assert requeued is False
    assert repositories.jobs.get(original.id) == original
    database.close()


def test_requeue_failed_reports_unknown_job(tmp_path: Path) -> None:
    # Given: no job
    database, repositories = _storage(tmp_path)

    # When / Then: requeue reports that nothing was requeued
    assert repositories.jobs.requeue_failed("job_missing", datetime.now(UTC)) is False
    database.close()


# --- Retry budget -----------------------------------------------------------------------------


def _fail_once(repositories: Repositories, job_id: str) -> Job:
    async def overloaded(_payload: dict[str, object]) -> None:
        raise ProviderUnavailableError("Model provider is temporarily unavailable.")

    worker = DurableJobWorker(
        repositories.jobs,
        {CONVERSATION_EXTRACTION_JOB: overloaded},
        retry_delays={CONVERSATION_EXTRACTION_JOB: EXTRACTION_RETRY_DELAY},
    )
    assert asyncio.run(worker.process_once()) is True
    job = repositories.jobs.get(job_id)
    assert job is not None
    return job


def test_extraction_retries_until_the_final_attempt_with_capped_backoff(tmp_path: Path) -> None:
    # Given: a claimable extraction job one attempt away from its last (max - 1 used after run)
    database, repositories = _storage(tmp_path)
    repositories.jobs.enqueue(
        _job(
            "message_1",
            JobStatus.QUEUED,
            attempts=EXTRACTION_MAX_ATTEMPTS - 2,
            available_in=timedelta(seconds=-1),
        )
    )

    # When: the provider is overloaded again
    job = _fail_once(repositories, extraction_job_id("message_1"))

    # Then: it stays queued, with the backoff capped at 15 minutes
    assert job.status is JobStatus.QUEUED
    assert job.attempts == EXTRACTION_MAX_ATTEMPTS - 1
    assert job.last_error == "Handler failed with ProviderUnavailableError"
    delay = job.available_at - job.updated_at
    assert timedelta(minutes=14, seconds=59) <= delay <= timedelta(minutes=15, seconds=1)
    database.close()


def test_extraction_fails_after_the_final_attempt(tmp_path: Path) -> None:
    # Given: a claimable extraction job on its final attempt
    database, repositories = _storage(tmp_path)
    repositories.jobs.enqueue(
        _job(
            "message_1",
            JobStatus.QUEUED,
            attempts=EXTRACTION_MAX_ATTEMPTS - 1,
            available_in=timedelta(seconds=-1),
        )
    )

    # When: the provider is still overloaded
    job = _fail_once(repositories, extraction_job_id("message_1"))

    # Then: the job is failed and waits for an owner retry
    assert job.status is JobStatus.FAILED
    assert job.attempts == EXTRACTION_MAX_ATTEMPTS
    database.close()


# --- message_learning -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "attempts", "expected"),
    [
        (JobStatus.QUEUED, 0, "pending"),
        (JobStatus.RUNNING, 1, "pending"),
        (JobStatus.QUEUED, 1, "retrying"),
        (JobStatus.FAILED, EXTRACTION_MAX_ATTEMPTS, "failed"),
        (JobStatus.SUCCEEDED, 1, "no_evidence"),
    ],
)
def test_message_learning_maps_job_state(
    tmp_path: Path, status: JobStatus, attempts: int, expected: str
) -> None:
    # Given: one learning job in the given state and no evidence
    database, repositories = _storage(tmp_path)
    repositories.jobs.enqueue(_job("message_1", status, attempts=attempts))

    # When: learning status is read
    result = message_learning(repositories.jobs, repositories.evidence, PROFILE, ["message_1"])

    # Then: the job state maps onto the owner-facing status
    assert result["message_1"].status == expected
    assert result["message_1"].attempts == attempts
    assert result["message_1"].max_attempts == EXTRACTION_MAX_ATTEMPTS
    database.close()


def test_message_learning_reports_learned_when_evidence_came_from_the_message(
    tmp_path: Path,
) -> None:
    # Given: a succeeded job whose message produced evidence
    database, repositories = _storage(tmp_path)
    repositories.jobs.enqueue(_job("message_1", JobStatus.SUCCEEDED, attempts=1))
    repositories.profiles.add(Profile(PROFILE, "Synthetic Owner", datetime.now(UTC)))
    now = datetime.now(UTC)
    repositories.conversations.add(Conversation("conversation_1", PROFILE, now, now))
    repositories.messages.add(
        Message("message_1", "conversation_1", MessageRole.USER, "I like dark theme", now)
    )
    repositories.raw_events.add(_source_event("message_1"))
    repositories.evidence.add(_evidence("message_1"))

    # When: learning status is read
    result = message_learning(repositories.jobs, repositories.evidence, PROFILE, ["message_1"])

    # Then: the message is reported as learned
    assert result["message_1"].status == "learned"
    database.close()


def test_message_learning_omits_messages_without_jobs_or_of_other_profiles(
    tmp_path: Path,
) -> None:
    # Given: one message without a job and one whose job belongs to another profile
    database, repositories = _storage(tmp_path)
    repositories.jobs.enqueue(_job("message_other", JobStatus.FAILED, profile_id="profile_x"))

    # When: learning status is read
    result = message_learning(
        repositories.jobs, repositories.evidence, PROFILE, ["message_none", "message_other"]
    )

    # Then: neither message has a learning status
    assert result == {}
    database.close()


def test_message_learning_skips_evidence_lookup_for_empty_input(tmp_path: Path) -> None:
    # Given: no message ids and an evidence repository that must not be read
    database, repositories = _storage(tmp_path)
    evidence = MagicMock(spec=EvidenceRepository)

    # When: learning status is read
    result = message_learning(repositories.jobs, evidence, PROFILE, [])

    # Then: nothing is returned and evidence is never loaded
    assert result == {}
    evidence.list_for_profile.assert_not_called()
    database.close()


# --- HTTP API ---------------------------------------------------------------------------------


def _chat(tmp_path: Path) -> tuple[TestClient, Repositories, str]:
    provider = FakeLLMProvider(responses=["Noted."])
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    client = TestClient(app, client=OWNER_CLIENT)
    client.__enter__()
    response = client.post("/v1/chat", json={"content": "I like dark theme over light theme"})
    assert response.status_code == 200
    repositories: Repositories = app.state.runtime["repositories"]
    return client, repositories, response.json()["user_message_id"]


def _fail_attempts(repositories: Repositories, message_id: str, failures: int) -> None:
    """Fail the chat's learning job through the public queue API.

    A far-future clock claims the job before the background worker (which uses the
    real clock) can, and keeps each retry out of the worker's reach.
    """
    future = datetime.now(UTC) + timedelta(days=1)
    for _ in range(failures):
        claimed = repositories.jobs.claim_next(
            future, future - timedelta(minutes=5), {CONVERSATION_EXTRACTION_JOB}
        )
        assert claimed is not None
        assert claimed.id == extraction_job_id(message_id)
        repositories.jobs.mark_failed(
            claimed.id,
            "Handler failed with ProviderUnavailableError",
            future,
            future,
        )


def test_chat_enqueues_extraction_with_the_extended_retry_budget(tmp_path: Path) -> None:
    # Given / When: a message is sent
    client, repositories, message_id = _chat(tmp_path)

    # Then: its learning job allows the extended number of attempts
    job = repositories.jobs.get(extraction_job_id(message_id))
    assert job is not None
    assert job.max_attempts == EXTRACTION_MAX_ATTEMPTS == 8
    client.__exit__(None, None, None)


def test_conversations_include_learning_only_for_user_messages(tmp_path: Path) -> None:
    # Given: a chat whose learning job has failed
    client, repositories, message_id = _chat(tmp_path)
    _fail_attempts(repositories, message_id, EXTRACTION_MAX_ATTEMPTS)

    # When: conversations are listed
    messages = client.get("/v1/conversations").json()[0]["messages"]

    # Then: the user message reports failure and the reply has no learning
    assert messages[0]["learning"] == {
        "message_id": message_id,
        "status": "failed",
        "attempts": EXTRACTION_MAX_ATTEMPTS,
        "max_attempts": EXTRACTION_MAX_ATTEMPTS,
    }
    assert messages[1]["learning"] is None
    client.__exit__(None, None, None)


def test_retry_learning_requeues_a_failed_job(tmp_path: Path) -> None:
    # Given: a chat whose learning job has failed
    client, repositories, message_id = _chat(tmp_path)
    _fail_attempts(repositories, message_id, EXTRACTION_MAX_ATTEMPTS)

    # When: the owner retries learning
    response = client.post(f"/v1/messages/{message_id}/learning/retry")

    # Then: learning is pending again with a fresh budget
    assert response.status_code == 200
    assert response.json() == {
        "message_id": message_id,
        "status": "pending",
        "attempts": 0,
        "max_attempts": EXTRACTION_MAX_ATTEMPTS,
    }
    client.__exit__(None, None, None)


def test_retry_learning_rejects_unknown_message(tmp_path: Path) -> None:
    # Given: a running service
    client, _, _ = _chat(tmp_path)

    # When: a message without a learning job is retried
    response = client.post("/v1/messages/message_missing/learning/retry")

    # Then: the service reports that the job does not exist
    assert response.status_code == 404
    assert response.json()["detail"] == JOB_NOT_FOUND
    client.__exit__(None, None, None)


def test_retry_learning_rejects_learning_that_has_not_failed(tmp_path: Path) -> None:
    # Given: learning that is still queued
    client, repositories, message_id = _chat(tmp_path)
    _fail_attempts(repositories, message_id, 1)

    # When: the owner retries learning
    response = client.post(f"/v1/messages/{message_id}/learning/retry")

    # Then: the retry conflicts and the job is untouched
    assert response.status_code == 409
    assert response.json()["detail"] == JOB_NOT_FAILED
    job = repositories.jobs.get(extraction_job_id(message_id))
    assert job is not None
    assert job.attempts == 1
    client.__exit__(None, None, None)


def test_retry_learning_rejects_another_profiles_job(tmp_path: Path) -> None:
    # Given: a failed job that belongs to another profile
    client, repositories, _ = _chat(tmp_path)
    repositories.jobs.enqueue(_job("message_other", JobStatus.FAILED, profile_id="profile_x"))

    # When: the owner retries that job
    response = client.post("/v1/messages/message_other/learning/retry")

    # Then: it is hidden as not found and stays failed
    assert response.status_code == 404
    assert response.json()["detail"] == JOB_NOT_FOUND
    job = repositories.jobs.get(extraction_job_id("message_other"))
    assert job is not None
    assert job.status is JobStatus.FAILED
    client.__exit__(None, None, None)


class _OverloadedProvider(FakeLLMProvider):
    async def generate(self, messages: object) -> str:
        del messages
        raise ProviderUnavailableError("Model provider is temporarily unavailable.")


def test_chat_reports_an_overloaded_provider_as_service_unavailable(tmp_path: Path) -> None:
    # Given: a provider that is overloaded
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=_OverloadedProvider())

    # When: a message is sent
    with TestClient(app, client=OWNER_CLIENT) as client:
        response = client.post("/v1/chat", json={"content": "Hello"})

    # Then: the owner is told to try again shortly
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The model provider is busy or unreachable. Try again shortly."
    )
