"""FastAPI composition root for the local Soulmate service."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TypedDict, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from soulmate_core.domain import Evidence, EvidenceTargetType, Preference, RawEvent
from soulmate_core.preferences import ModelRebuilder
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from soulmate_daemon import __version__
from soulmate_daemon.config import Settings
from soulmate_daemon.jobs import DurableJobWorker
from soulmate_daemon.system import DEFAULT_PROFILE_ID, ensure_installation


class AppState(TypedDict):
    settings: Settings
    database: Database
    repositories: Repositories
    installation_id: str


class HealthResponse(BaseModel):
    status: str
    database: str
    migration: str


class SystemInfoResponse(BaseModel):
    service: str
    version: str
    installation_id: str
    profile_id: str
    privacy_mode: str


class EvidenceResponse(BaseModel):
    id: str
    target_type: str
    target_key: str
    value: object
    strength: float
    confidence: float
    context: dict[str, object]
    source_type: str
    source_event_id: str
    extractor_version: str
    created_at: datetime


class PreferenceResponse(BaseModel):
    key: str
    value: float
    uncertainty: float
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int


class ModelSummaryResponse(BaseModel):
    version: int | None
    algorithm_version: str | None
    evidence_revision: int
    preference_count: int
    fact_count: int
    goal_count: int
    constraint_count: int


class PreferenceCorrectionRequest(BaseModel):
    target_key: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)
    context: dict[str, object] = Field(default_factory=dict)


class PreferenceCorrectionResponse(BaseModel):
    evidence: EvidenceResponse
    snapshot_version: int


def _state(app: FastAPI) -> AppState:
    return cast(AppState, app.state.runtime)


def _evidence_response(evidence: Evidence) -> EvidenceResponse:
    return EvidenceResponse(
        id=evidence.id,
        target_type=evidence.target_type.value,
        target_key=evidence.target_key,
        value=evidence.value,
        strength=evidence.strength,
        confidence=evidence.confidence,
        context=evidence.context,
        source_type=evidence.source_type,
        source_event_id=evidence.source_event_id,
        extractor_version=evidence.extractor_version,
        created_at=evidence.created_at,
    )


def _preference_response(preference: Preference) -> PreferenceResponse:
    return PreferenceResponse(
        key=preference.key,
        value=preference.value,
        uncertainty=preference.uncertainty,
        confidence=preference.confidence,
        context=preference.context,
        supporting_evidence_ids=preference.supporting_evidence_ids,
        updated_at=preference.updated_at,
        model_version=preference.model_version,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings.database_path)
        database.migrate()
        if database.session_factory is None:
            raise RuntimeError("Database session factory was not initialized.")
        repositories = Repositories(database.session_factory)
        installation_id = ensure_installation(repositories.system_metadata, repositories.profiles)
        app.state.runtime = AppState(
            settings=resolved_settings,
            database=database,
            repositories=repositories,
            installation_id=installation_id,
        )
        stop = asyncio.Event()
        worker = DurableJobWorker(repositories.jobs, {})
        worker_task = asyncio.create_task(worker.run(stop), name="soulmate-durable-worker")
        try:
            yield
        finally:
            stop.set()
            await worker_task
            if database.engine is not None:
                database.engine.dispose()

    app = FastAPI(
        title="Soulmate", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        runtime = _state(app)
        database = runtime["database"]
        try:
            if database.engine is None:
                raise RuntimeError("Database is not connected.")
            with database.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            migration = (
                "current" if database.current_revision() == database.head_revision() else "outdated"
            )
        except (RuntimeError, SQLAlchemyError) as exc:
            raise HTTPException(status_code=503, detail="Local storage is unavailable.") from exc
        status = "healthy" if migration == "current" else "degraded"
        return HealthResponse(status=status, database="available", migration=migration)

    @app.get("/v1/system/info", response_model=SystemInfoResponse)
    def system_info() -> SystemInfoResponse:
        runtime = _state(app)
        return SystemInfoResponse(
            service="soulmate-daemon",
            version=__version__,
            installation_id=runtime["installation_id"],
            profile_id=DEFAULT_PROFILE_ID,
            privacy_mode=runtime["settings"].privacy.mode,
        )

    @app.get("/v1/model/summary", response_model=ModelSummaryResponse)
    def model_summary() -> ModelSummaryResponse:
        repositories = _state(app)["repositories"]
        snapshot = repositories.personal_models.latest_snapshot(DEFAULT_PROFILE_ID)
        if snapshot is None:
            return ModelSummaryResponse(
                version=None,
                algorithm_version=None,
                evidence_revision=repositories.evidence.current_revision(DEFAULT_PROFILE_ID),
                preference_count=0,
                fact_count=0,
                goal_count=0,
                constraint_count=0,
            )
        return ModelSummaryResponse(
            version=snapshot.version,
            algorithm_version=snapshot.algorithm_version,
            evidence_revision=snapshot.evidence_revision,
            preference_count=len(snapshot.model.preferences),
            fact_count=len(snapshot.model.facts),
            goal_count=len(snapshot.model.goals),
            constraint_count=len(snapshot.model.constraints),
        )

    @app.get("/v1/preferences", response_model=list[PreferenceResponse])
    def preferences() -> list[PreferenceResponse]:
        records = _state(app)["repositories"].personal_models.list_preferences(DEFAULT_PROFILE_ID)
        return [_preference_response(item) for item in records]

    @app.get("/v1/evidence/{evidence_id}", response_model=EvidenceResponse)
    def evidence_by_id(evidence_id: str) -> EvidenceResponse:
        evidence = _state(app)["repositories"].evidence.get(evidence_id)
        if evidence is None or evidence.profile_id != DEFAULT_PROFILE_ID:
            raise HTTPException(status_code=404, detail="Evidence was not found.")
        return _evidence_response(evidence)

    @app.get("/v1/preferences/{key}/evidence", response_model=list[EvidenceResponse])
    def preference_evidence(key: str) -> list[EvidenceResponse]:
        evidence = _state(app)["repositories"].evidence.list_for_target(DEFAULT_PROFILE_ID, key)
        return [
            _evidence_response(item)
            for item in evidence
            if item.target_type is EvidenceTargetType.PREFERENCE
        ]

    @app.post(
        "/v1/preferences/corrections",
        response_model=PreferenceCorrectionResponse,
        status_code=201,
    )
    def correct_preference(request: PreferenceCorrectionRequest) -> PreferenceCorrectionResponse:
        repositories = _state(app)["repositories"]
        now = datetime.now(UTC)
        event = RawEvent(
            id=f"event_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            source_id=None,
            event_type="preference_correction",
            content={
                "target_key": request.target_key,
                "value": request.value,
                "context": request.context,
            },
            created_at=now,
            ingested_at=now,
        )
        evidence = Evidence(
            id=f"evidence_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            target_type=EvidenceTargetType.PREFERENCE,
            target_key=request.target_key,
            value=request.value,
            strength=1.0,
            confidence=1.0,
            context=request.context,
            source_type="user_correction",
            source_event_id=event.id,
            extractor_version="user-correction-v1",
            created_at=now,
        )
        repositories.raw_events.add(event)
        repositories.evidence.add(evidence)
        snapshot = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
            DEFAULT_PROFILE_ID, now
        )
        return PreferenceCorrectionResponse(
            evidence=_evidence_response(evidence), snapshot_version=snapshot.version
        )

    return app
