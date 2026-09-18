"""Per-message learning status and owner-triggered retry of failed conversation learning."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel
from soulmate_core.domain import EvidenceRepository, Job, JobRepository, JobStatus

from soulmate_daemon.conversation import extraction_job_id
from soulmate_daemon.runtime import runtime_of
from soulmate_daemon.system import DEFAULT_PROFILE_ID

LearningStatus = Literal["pending", "retrying", "learned", "no_evidence", "failed"]
JOB_NOT_FOUND = "The message has no learning job."
JOB_NOT_FAILED = "Only failed learning can be retried."


class MessageLearningResponse(BaseModel):
    message_id: str
    status: LearningStatus
    attempts: int
    max_attempts: int


def _status(job: Job, learned_message_ids: set[str], message_id: str) -> LearningStatus:
    if job.status is JobStatus.FAILED:
        return "failed"
    if job.status is JobStatus.SUCCEEDED:
        return "learned" if message_id in learned_message_ids else "no_evidence"
    if job.status is JobStatus.QUEUED and job.attempts > 0:
        return "retrying"
    return "pending"


def message_learning(
    jobs: JobRepository,
    evidence: EvidenceRepository,
    profile_id: str,
    message_ids: Iterable[str],
) -> dict[str, MessageLearningResponse]:
    """Return the deferred learning state of each message that has a learning job."""
    found = {
        message_id: job
        for message_id in message_ids
        if (job := jobs.get(extraction_job_id(message_id))) is not None
        and job.payload.get("profile_id") == profile_id
    }
    if not found:
        return {}
    learned = {
        item.source_message_id
        for item in evidence.list_for_profile(profile_id)
        if item.source_message_id is not None
    }
    return {
        message_id: MessageLearningResponse(
            message_id=message_id,
            status=_status(job, learned, message_id),
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )
        for message_id, job in found.items()
    }


def build_learning_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/messages/{message_id}/learning/retry", response_model=MessageLearningResponse)
    def retry_learning(message_id: str) -> MessageLearningResponse:
        repositories = runtime_of(app)["repositories"]
        job = repositories.jobs.get(extraction_job_id(message_id))
        if job is None or job.payload.get("profile_id") != DEFAULT_PROFILE_ID:
            raise HTTPException(status_code=404, detail=JOB_NOT_FOUND)
        if not repositories.jobs.requeue_failed(job.id, datetime.now(UTC)):
            raise HTTPException(status_code=409, detail=JOB_NOT_FAILED)
        return message_learning(
            repositories.jobs, repositories.evidence, DEFAULT_PROFILE_ID, (message_id,)
        )[message_id]

    return router
