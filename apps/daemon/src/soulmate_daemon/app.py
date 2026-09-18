"""FastAPI composition root for the local Soulmate service."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from soulmate_connector_sdk import SourceConnector, discover_connectors
from soulmate_core.domain import (
    ActiveQuestion,
    AuditEvent,
    Conversation,
    DecisionAdvice,
    DecisionEvent,
    DecisionOption,
    DecisionOutcome,
    DecisionPrediction,
    DecisionResolution,
    Evidence,
    EvidenceTargetType,
    MessageRole,
    Preference,
    RawEvent,
)
from soulmate_core.embeddings import EmbeddingProvider
from soulmate_core.learning import rank_uncertainties
from soulmate_llm_providers import (
    EgressDeniedError,
    LLMProvider,
    ProviderError,
    ProviderUnavailableError,
)
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from soulmate_daemon import __version__
from soulmate_daemon.access_api import build_access_router
from soulmate_daemon.active_learning import ActiveAnswerResult, ActiveLearningService
from soulmate_daemon.config import Settings
from soulmate_daemon.connector_api import build_connector_router
from soulmate_daemon.connectors import CONNECTOR_SYNC_JOB, ConnectorService
from soulmate_daemon.conversation import (
    CONVERSATION_EXTRACTION_JOB,
    EXTRACTION_RETRY_DELAY,
    ConversationService,
)
from soulmate_daemon.data_api import build_data_router
from soulmate_daemon.decisions import DecisionOptionInput, DecisionService, ResolutionResult
from soulmate_daemon.delegation_api import build_delegation_router
from soulmate_daemon.embedding_api import build_embedding_router
from soulmate_daemon.embedding_models import EmbeddingModelService
from soulmate_daemon.embeddings import embedding_provider as build_embedding_provider
from soulmate_daemon.external_api import build_external_router
from soulmate_daemon.jobs import DurableJobWorker
from soulmate_daemon.key_alias_api import build_key_alias_router
from soulmate_daemon.key_aliases import (
    alias_repository,
    model_rebuilder,
    register_normalized_aliases,
)
from soulmate_daemon.key_label_api import build_key_label_router
from soulmate_daemon.key_semantics import (
    KEY_EMBEDDING_INTERVAL_SECONDS,
    KEY_EMBEDDING_REFRESH_JOB,
    enqueue_key_embedding_refresh,
    key_semantics_service,
    refresh_from_payload,
)
from soulmate_daemon.learning_api import (
    MessageLearningResponse,
    build_learning_router,
    message_learning,
)
from soulmate_daemon.network import (
    LanEndpoint,
    NetworkConfigurationError,
    prepare_lan_endpoint,
)
from soulmate_daemon.portability import PortabilityError, apply_pending_restore
from soulmate_daemon.providers import build_provider
from soulmate_daemon.remote_backup import (
    REMOTE_BACKUP_JOB,
    RemoteBackupError,
    RemoteBackupService,
    RemoteBackupStore,
    build_remote_backup_store,
    enqueue_remote_backup_if_due,
)
from soulmate_daemon.runtime import (
    AppState,
    build_access_service,
    build_external_identity_service,
    runtime_of,
)
from soulmate_daemon.security import AccessDeniedError, ActorKind, authorize
from soulmate_daemon.system import DEFAULT_PROFILE_ID, ensure_installation
from soulmate_daemon.tls import CertificateError
from soulmate_daemon.web import mount_web_client


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
    extractor_model: str | None
    source_message_id: str | None
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


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content must not be blank.")
        return value


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    provider_model: str | None
    created_at: datetime
    learning: MessageLearningResponse | None = None


class ConversationResponse(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]


class ChatResponse(BaseModel):
    conversation_id: str
    user_message_id: str
    message: MessageResponse
    accepted_evidence: list[EvidenceResponse]
    rejected_evidence_count: int
    snapshot_version: int | None
    learning_status: Literal["learned", "no_evidence", "pending"]
    learning_error: str | None


class DecisionOptionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)
    features: dict[str, float] = Field(default_factory=dict)
    feature_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_features(self) -> "DecisionOptionRequest":
        if not self.label.strip() or not self.description.strip():
            raise ValueError("Decision option text must not be blank.")
        if any(not key.strip() or not -1.0 <= value <= 1.0 for key, value in self.features.items()):
            raise ValueError("Feature values must be between -1 and 1.")
        return self


class DecisionCreateRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=10_000)
    context: dict[str, object] = Field(default_factory=dict)
    options: list[DecisionOptionRequest] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def validate_options(self) -> "DecisionCreateRequest":
        if not self.domain.strip() or not self.question.strip():
            raise ValueError("Decision domain and question must not be blank.")
        labels = [item.label.casefold() for item in self.options]
        if len(labels) != len(set(labels)):
            raise ValueError("Decision option labels must be unique.")
        return self


class DecisionOptionResponse(BaseModel):
    id: str
    label: str
    description: str
    features: dict[str, float]
    feature_confidence: float


class DecisionResponse(BaseModel):
    id: str
    domain: str
    question: str
    context: dict[str, object]
    status: str
    options: list[DecisionOptionResponse]
    created_at: datetime


class RankingResponse(BaseModel):
    option_id: str
    label: str
    probability: float
    utility: float


class DecisionPredictionResponse(BaseModel):
    id: str
    decision_id: str
    mode: str
    predicted_option_id: str
    predicted_choice: str
    ranking: list[RankingResponse]
    confidence: float
    important_factors: tuple[str, ...]
    uncertain_factors: tuple[str, ...]
    supporting_evidence: list[EvidenceResponse]
    similar_decision_ids: tuple[str, ...]
    model_snapshot_version: int
    algorithm_version: str
    created_at: datetime


class AdviceRankingResponse(BaseModel):
    option_id: str
    label: str
    recommendation_score: float
    behavioral_probability: float
    wellbeing_score: float | None
    goal_alignment: float | None


class DecisionAdviceResponse(BaseModel):
    id: str
    decision_id: str
    mode: str
    predicted_option_id: str
    predicted_choice: str
    recommended_option_id: str
    recommended_choice: str
    ranking: list[AdviceRankingResponse]
    confidence: float
    rationale: tuple[str, ...]
    supporting_outcome_ids: tuple[str, ...]
    model_snapshot_version: int
    algorithm_version: str
    created_at: datetime


class DecisionResolutionRequest(BaseModel):
    chosen_option_id: str = Field(min_length=1, max_length=200)


class DecisionResolutionResponse(BaseModel):
    id: str
    decision_id: str
    chosen_option_id: str
    learned_evidence: list[EvidenceResponse]
    snapshot_version: int
    created_at: datetime


class ResolutionHistoryResponse(BaseModel):
    id: str
    decision_id: str
    chosen_option_id: str
    created_at: datetime


class DecisionOutcomeRequest(BaseModel):
    satisfaction: float = Field(ge=0.0, le=1.0)
    regret: bool
    notes: str | None = Field(default=None, max_length=10_000)

    @field_validator("notes")
    @classmethod
    def notes_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Outcome notes must be omitted or contain text.")
        return value


class DecisionOutcomeResponse(BaseModel):
    id: str
    decision_id: str
    satisfaction: float
    regret: bool
    notes: str | None
    created_at: datetime


class DecisionOutcomeDeletionResponse(BaseModel):
    removed_outcome_id: str


class DecisionHistoryResponse(BaseModel):
    decision: DecisionResponse
    prediction: DecisionPredictionResponse | None
    resolution: ResolutionHistoryResponse | None
    advice: DecisionAdviceResponse | None
    outcome: DecisionOutcomeResponse | None


class UncertaintyResponse(BaseModel):
    preference_key: str
    context: dict[str, object]
    uncertainty: float
    confidence: float
    information_value: float


class ActiveQuestionGenerateRequest(BaseModel):
    limit: int = Field(default=3, ge=1, le=10)
    target_key: str | None = Field(default=None, min_length=1, max_length=200)


class ActiveQuestionResponse(BaseModel):
    id: str
    prompt: str
    preference_keys: tuple[str, ...]
    context: dict[str, object]
    option_a_label: str
    option_b_label: str
    information_gain_score: float
    model_snapshot_version: int
    algorithm_version: str
    status: str
    created_at: datetime


class ActiveQuestionAnswerRequest(BaseModel):
    choice: Literal["a", "b"]


class ActiveQuestionAnswerResponse(BaseModel):
    question_id: str
    choice: str
    learned_evidence: list[EvidenceResponse]
    snapshot_version: int
    created_at: datetime


class EvidenceDeletionResponse(BaseModel):
    removed_evidence_id: str
    snapshot_version: int


def _state(app: FastAPI) -> AppState:
    return runtime_of(app)


def _resolve_lan(
    settings: Settings, provided: LanEndpoint | None
) -> tuple[LanEndpoint | None, str | None]:
    """Prepare the LAN listener only when the owner explicitly enabled it."""
    if provided is not None:
        return provided, None
    if not settings.network.lan_enabled:
        return None, None
    try:
        return prepare_lan_endpoint(settings), None
    except (CertificateError, NetworkConfigurationError, OSError) as exc:
        return None, str(exc)


def _resolve_provider(runtime: AppState) -> LLMProvider:
    provider = runtime["provider"]
    if provider is None:
        provider = build_provider(runtime["settings"])
        runtime["provider"] = provider
    return provider


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
        extractor_model=evidence.extractor_model,
        source_message_id=evidence.source_message_id,
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


def _decision_response(
    decision: DecisionEvent, options: tuple[DecisionOption, ...]
) -> DecisionResponse:
    return DecisionResponse(
        id=decision.id,
        domain=decision.domain,
        question=decision.question,
        context=decision.context,
        status=decision.status.value,
        options=[
            DecisionOptionResponse(
                id=item.id,
                label=item.label,
                description=item.description,
                features=item.features,
                feature_confidence=item.feature_confidence,
            )
            for item in options
        ],
        created_at=decision.created_at,
    )


def _prediction_response(
    prediction: DecisionPrediction,
    options: tuple[DecisionOption, ...],
    evidence: list[Evidence],
) -> DecisionPredictionResponse:
    labels = {item.id: item.label for item in options}
    winner = prediction.ranking[0]
    return DecisionPredictionResponse(
        id=prediction.id,
        decision_id=prediction.decision_id,
        mode="predict_me",
        predicted_option_id=winner.option_id,
        predicted_choice=labels[winner.option_id],
        ranking=[
            RankingResponse(
                option_id=item.option_id,
                label=labels[item.option_id],
                probability=item.probability,
                utility=item.utility,
            )
            for item in prediction.ranking
        ],
        confidence=prediction.confidence,
        important_factors=prediction.important_factors,
        uncertain_factors=prediction.uncertain_factors,
        supporting_evidence=[_evidence_response(item) for item in evidence],
        similar_decision_ids=prediction.similar_decision_ids,
        model_snapshot_version=prediction.model_snapshot_version,
        algorithm_version=prediction.algorithm_version,
        created_at=prediction.created_at,
    )


def _resolution_response(result: ResolutionResult) -> DecisionResolutionResponse:
    return DecisionResolutionResponse(
        id=result.resolution.id,
        decision_id=result.resolution.decision_id,
        chosen_option_id=result.resolution.chosen_option_id,
        learned_evidence=[_evidence_response(item) for item in result.evidence],
        snapshot_version=result.snapshot_version,
        created_at=result.resolution.created_at,
    )


def _stored_resolution_response(resolution: DecisionResolution) -> ResolutionHistoryResponse:
    return ResolutionHistoryResponse(
        id=resolution.id,
        decision_id=resolution.decision_id,
        chosen_option_id=resolution.chosen_option_id,
        created_at=resolution.created_at,
    )


def _outcome_response(outcome: DecisionOutcome) -> DecisionOutcomeResponse:
    return DecisionOutcomeResponse(
        id=outcome.id,
        decision_id=outcome.decision_id,
        satisfaction=outcome.satisfaction,
        regret=outcome.regret,
        notes=outcome.notes,
        created_at=outcome.created_at,
    )


def _advice_response(
    advice: DecisionAdvice,
    options: tuple[DecisionOption, ...],
) -> DecisionAdviceResponse:
    labels = {item.id: item.label for item in options}
    recommended = advice.ranking[0]
    predicted = sorted(
        advice.ranking, key=lambda item: (-item.behavioral_probability, item.option_id)
    )[0]
    return DecisionAdviceResponse(
        id=advice.id,
        decision_id=advice.decision_id,
        mode="advise_me",
        predicted_option_id=predicted.option_id,
        predicted_choice=labels[predicted.option_id],
        recommended_option_id=recommended.option_id,
        recommended_choice=labels[recommended.option_id],
        ranking=[
            AdviceRankingResponse(
                option_id=item.option_id,
                label=labels[item.option_id],
                recommendation_score=item.recommendation_score,
                behavioral_probability=item.behavioral_probability,
                wellbeing_score=item.wellbeing_score,
                goal_alignment=item.goal_alignment,
            )
            for item in advice.ranking
        ],
        confidence=advice.confidence,
        rationale=advice.rationale,
        supporting_outcome_ids=advice.supporting_outcome_ids,
        model_snapshot_version=advice.model_snapshot_version,
        algorithm_version=advice.algorithm_version,
        created_at=advice.created_at,
    )


def _active_question_response(question: ActiveQuestion) -> ActiveQuestionResponse:
    return ActiveQuestionResponse(
        id=question.id,
        prompt=question.prompt,
        preference_keys=question.preference_keys,
        context=question.context,
        option_a_label=question.option_a_label,
        option_b_label=question.option_b_label,
        information_gain_score=question.information_gain_score,
        model_snapshot_version=question.model_snapshot_version,
        algorithm_version=question.algorithm_version,
        status=question.status.value,
        created_at=question.created_at,
    )


def create_app(
    settings: Settings | None = None,
    *,
    provider: LLMProvider | None = None,
    lan: LanEndpoint | None = None,
    connectors: tuple[SourceConnector, ...] = (),
    remote_backup_store: RemoteBackupStore | None = None,
    embeddings: EmbeddingProvider | None = None,
) -> FastAPI:
    resolved_settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        restored_revision = apply_pending_restore(resolved_settings)
        database = Database(resolved_settings.database_path)
        database.migrate()
        if database.session_factory is None:
            raise RuntimeError("Database session factory was not initialized.")
        repositories = Repositories(database.session_factory)
        installation_id = ensure_installation(repositories.system_metadata, repositories.profiles)
        rebuilder = model_rebuilder(repositories, resolved_settings)
        if restored_revision is not None:
            rebuilder.rebuild(DEFAULT_PROFILE_ID)
        elif repositories.personal_models.latest_snapshot(DEFAULT_PROFILE_ID) is not None:
            # Refresh a snapshot built before key_aliases.enabled last changed.
            rebuilder.current(DEFAULT_PROFILE_ID)
        endpoint, lan_error = _resolve_lan(resolved_settings, lan)
        connector_catalog = discover_connectors(connectors)
        backup_store = (
            remote_backup_store
            if remote_backup_store is not None
            else build_remote_backup_store(resolved_settings)
        )
        remote_backup = (
            None
            if backup_store is None
            else RemoteBackupService(
                resolved_settings,
                database,
                repositories.system_metadata,
                backup_store,
            )
        )
        embedding_models = EmbeddingModelService(
            resolved_settings, repositories.audit_events, profile_id=DEFAULT_PROFILE_ID
        )
        semantics = None
        if embeddings is not None or resolved_settings.embedding.provider != "none":
            semantics = key_semantics_service(
                repositories,
                resolved_settings,
                embeddings
                if embeddings is not None
                else build_embedding_provider(resolved_settings),
            )
        app.state.runtime = AppState(
            settings=resolved_settings,
            database=database,
            repositories=repositories,
            installation_id=installation_id,
            provider=provider,
            lan=endpoint,
            lan_error=lan_error,
            connector_catalog=connector_catalog,
            remote_backup=remote_backup,
            embedding_models=embedding_models,
            key_semantics=semantics,
        )
        stop = asyncio.Event()

        async def sync_connector(payload: dict[str, object]) -> None:
            profile_id = payload.get("profile_id")
            connector_id = payload.get("connector_id")
            if not isinstance(profile_id, str) or not isinstance(connector_id, str):
                raise ValueError("Connector sync job payload is invalid.")
            await ConnectorService(
                repositories.connector_registrations,
                repositories.jobs,
                repositories.audit_events,
                connector_catalog,
                privacy_mode=resolved_settings.privacy.mode,
            ).sync(profile_id, connector_id)

        async def create_remote_backup(payload: dict[str, object]) -> None:
            if payload or remote_backup is None:
                raise ValueError("Remote backup job payload or configuration is invalid.")
            try:
                result = await asyncio.to_thread(remote_backup.create_and_upload)
            except (OSError, PortabilityError, RemoteBackupError) as exc:
                repositories.audit_events.add(
                    AuditEvent(
                        id=f"audit_{uuid4().hex}",
                        profile_id=DEFAULT_PROFILE_ID,
                        action="data.remote_backup_failed",
                        actor_type="system",
                        actor_id=None,
                        metadata={
                            "backend": resolved_settings.remote_backup.backend,
                            "trigger": "scheduled",
                            "error_type": type(exc).__name__,
                        },
                        created_at=datetime.now(UTC),
                    )
                )
                raise
            repositories.audit_events.add(
                AuditEvent(
                    id=f"audit_{uuid4().hex}",
                    profile_id=DEFAULT_PROFILE_ID,
                    action="data.remote_backup",
                    actor_type="system",
                    actor_id=None,
                    metadata={
                        "sha256": result.archive.sha256,
                        "size_bytes": result.archive.size_bytes,
                        "backend": resolved_settings.remote_backup.backend,
                        "trigger": "scheduled",
                    },
                    created_at=datetime.now(UTC),
                )
            )

        async def retry_conversation_extraction(payload: dict[str, object]) -> None:
            await ConversationService(
                conversations=repositories.conversations,
                messages=repositories.messages,
                raw_events=repositories.raw_events,
                evidence=repositories.evidence,
                models=repositories.personal_models,
                provider=_resolve_provider(_state(app)),
                jobs=repositories.jobs,
                aliases=alias_repository(repositories, resolved_settings),
                catalog=repositories.key_catalog,
                semantics=semantics,
            ).retry_learning(payload)

        async def refresh_key_embeddings(payload: dict[str, object]) -> None:
            if semantics is None:
                raise ValueError("Key embeddings are disabled, so no refresh may run.")
            await asyncio.to_thread(refresh_from_payload, semantics, payload)

        handlers = {
            CONNECTOR_SYNC_JOB: sync_connector,
            CONVERSATION_EXTRACTION_JOB: retry_conversation_extraction,
        }
        if remote_backup is not None:
            handlers[REMOTE_BACKUP_JOB] = create_remote_backup
        if semantics is not None:
            handlers[KEY_EMBEDDING_REFRESH_JOB] = refresh_key_embeddings
        worker = DurableJobWorker(
            repositories.jobs,
            handlers,
            retry_delays={CONVERSATION_EXTRACTION_JOB: EXTRACTION_RETRY_DELAY},
        )
        worker_task = asyncio.create_task(worker.run(stop), name="soulmate-durable-worker")
        scheduler_task: asyncio.Task[None] | None = None
        if remote_backup is not None and resolved_settings.remote_backup.automatic_daily:

            async def schedule_remote_backup() -> None:
                interval = timedelta(hours=resolved_settings.remote_backup.interval_hours)
                while not stop.is_set():
                    await asyncio.to_thread(
                        enqueue_remote_backup_if_due,
                        repositories.jobs,
                        repositories.system_metadata,
                        interval=interval,
                    )
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=3600)
                    except TimeoutError:
                        continue

            scheduler_task = asyncio.create_task(
                schedule_remote_backup(), name="soulmate-remote-backup-scheduler"
            )
        embedding_task: asyncio.Task[None] | None = None
        if semantics is not None:

            async def schedule_key_embeddings() -> None:
                """Queue a refresh when evidence or the installed model changed.

                Polling keeps the chat path free of embedding work and covers every
                evidence source; the job identity makes a repeated check free.
                """
                while not stop.is_set():
                    await asyncio.to_thread(
                        enqueue_key_embedding_refresh,
                        repositories.jobs,
                        repositories.evidence,
                        semantics,
                        DEFAULT_PROFILE_ID,
                    )
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=KEY_EMBEDDING_INTERVAL_SECONDS)
                    except TimeoutError:
                        continue

            embedding_task = asyncio.create_task(
                schedule_key_embeddings(), name="soulmate-key-embedding-scheduler"
            )
        try:
            yield
        finally:
            stop.set()
            await embedding_models.shutdown()
            tasks = [worker_task]
            if scheduler_task is not None:
                tasks.append(scheduler_task)
            if embedding_task is not None:
                tasks.append(embedding_task)
            await asyncio.gather(*tasks)
            if database.engine is not None:
                database.engine.dispose()

    app = FastAPI(
        title="Soulmate", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )

    def record_external_audit(
        state: AppState,
        request: Request,
        status_code: int,
        *,
        actor_type: str,
        identity_id: str | None,
        credential_id: str | None,
    ) -> None:
        state["repositories"].audit_events.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                profile_id=DEFAULT_PROFILE_ID,
                action="external_request",
                actor_type=actor_type,
                actor_id=identity_id,
                metadata={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    **({} if credential_id is None else {"credential_id": credential_id}),
                },
                created_at=datetime.now(UTC),
            )
        )

    @app.middleware("http")
    async def enforce_device_access(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Authorize every request before any handler can observe personal data."""
        runtime = getattr(app.state, "runtime", None)
        if runtime is None:
            return JSONResponse({"detail": "The local service is starting."}, status_code=503)
        state = cast(AppState, runtime)
        is_external = request.url.path.startswith("/v1/external/")
        external_service = build_external_identity_service(state)
        try:
            actor = await run_in_threadpool(
                authorize,
                method=request.method,
                path=request.url.path,
                client_host=None if request.client is None else request.client.host,
                lan_enabled=state["lan"] is not None,
                authorization=request.headers.get("authorization"),
                authenticate=build_access_service(state).authenticate,
                authenticate_service=lambda credential: external_service.authenticate(
                    credential, datetime.now(UTC)
                ),
            )
        except AccessDeniedError as exc:
            if is_external:
                record_external_audit(
                    state,
                    request,
                    exc.status_code,
                    actor_type=("service" if exc.service_identity_id is not None else "anonymous"),
                    identity_id=exc.service_identity_id,
                    credential_id=exc.credential_id,
                )
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        request.state.actor = actor
        try:
            response = await call_next(request)
        except Exception:
            if is_external:
                record_external_audit(
                    state,
                    request,
                    500,
                    actor_type="service",
                    identity_id=actor.service_identity_id,
                    credential_id=actor.credential_id,
                )
            raise
        if is_external:
            record_external_audit(
                state,
                request,
                response.status_code,
                actor_type=("service" if actor.kind is ActorKind.SERVICE else actor.kind.value),
                identity_id=actor.service_identity_id,
                credential_id=actor.credential_id,
            )
        return response

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

    @app.get("/v1/model/uncertainties", response_model=list[UncertaintyResponse])
    def uncertainties() -> list[UncertaintyResponse]:
        repositories = _state(app)["repositories"]
        snapshot = repositories.personal_models.latest_snapshot(DEFAULT_PROFILE_ID)
        if snapshot is None:
            return []
        return [
            UncertaintyResponse(
                preference_key=item.preference_key,
                context=item.context,
                uncertainty=item.uncertainty,
                confidence=item.confidence,
                information_value=item.information_value,
            )
            for item in rank_uncertainties(snapshot.model.preferences)
        ]

    @app.get("/v1/active-questions", response_model=list[ActiveQuestionResponse])
    def active_questions() -> list[ActiveQuestionResponse]:
        records = _state(app)["repositories"].active_questions.list_for_profile(DEFAULT_PROFILE_ID)
        return [_active_question_response(item) for item in records]

    @app.post(
        "/v1/active-questions/generate",
        response_model=list[ActiveQuestionResponse],
        status_code=201,
    )
    def generate_questions(
        request: ActiveQuestionGenerateRequest,
    ) -> list[ActiveQuestionResponse]:
        repositories = _state(app)["repositories"]
        service = ActiveLearningService(
            questions=repositories.active_questions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            aliases=alias_repository(repositories, _state(app)["settings"]),
        )
        questions = service.generate(DEFAULT_PROFILE_ID, request.limit, request.target_key)
        return [_active_question_response(item) for item in questions]

    @app.post(
        "/v1/active-questions/{question_id}/answer",
        response_model=ActiveQuestionAnswerResponse,
        status_code=201,
    )
    def answer_question(
        question_id: str, request: ActiveQuestionAnswerRequest
    ) -> ActiveQuestionAnswerResponse:
        repositories = _state(app)["repositories"]
        service = ActiveLearningService(
            questions=repositories.active_questions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            aliases=alias_repository(repositories, _state(app)["settings"]),
        )
        try:
            result: ActiveAnswerResult = service.answer(
                DEFAULT_PROFILE_ID, question_id, request.choice
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Active question was not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ActiveQuestionAnswerResponse(
            question_id=result.answer.question_id,
            choice=result.answer.choice,
            learned_evidence=[_evidence_response(item) for item in result.evidence],
            snapshot_version=result.snapshot_version,
            created_at=result.answer.created_at,
        )

    @app.get("/v1/conversations", response_model=list[ConversationResponse])
    def conversations() -> list[ConversationResponse]:
        repositories = _state(app)["repositories"]
        records: tuple[Conversation, ...] = repositories.conversations.list_for_profile(
            DEFAULT_PROFILE_ID
        )
        messages = {
            conversation.id: repositories.messages.list_for_conversation(conversation.id)
            for conversation in records
        }
        learning = message_learning(
            repositories.jobs,
            repositories.evidence,
            DEFAULT_PROFILE_ID,
            (
                message.id
                for items in messages.values()
                for message in items
                if message.role is MessageRole.USER
            ),
        )
        return [
            ConversationResponse(
                id=conversation.id,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                messages=[
                    MessageResponse(
                        id=message.id,
                        role=message.role.value,
                        content=message.content,
                        provider_model=message.provider_model,
                        created_at=message.created_at,
                        learning=learning.get(message.id),
                    )
                    for message in messages[conversation.id]
                ],
            )
            for conversation in records
        ]

    @app.get("/v1/decisions", response_model=list[DecisionHistoryResponse])
    def decision_history() -> list[DecisionHistoryResponse]:
        repositories = _state(app)["repositories"]
        result = []
        for decision, options in repositories.decisions.list_for_profile(DEFAULT_PROFILE_ID):
            prediction = repositories.decisions.latest_prediction(decision.id)
            resolution = repositories.decisions.get_resolution(decision.id)
            advice = repositories.decisions.latest_advice(decision.id)
            outcome = repositories.outcomes.get_for_decision(decision.id)
            support = []
            if prediction is not None:
                support = [
                    item
                    for evidence_id in prediction.supporting_evidence_ids
                    if (item := repositories.evidence.get(evidence_id)) is not None
                ]
            result.append(
                DecisionHistoryResponse(
                    decision=_decision_response(decision, options),
                    prediction=(
                        None
                        if prediction is None
                        else _prediction_response(prediction, options, support)
                    ),
                    resolution=(
                        None if resolution is None else _stored_resolution_response(resolution)
                    ),
                    advice=(None if advice is None else _advice_response(advice, options)),
                    outcome=None if outcome is None else _outcome_response(outcome),
                )
            )
        return result

    @app.get("/v1/evidence/{evidence_id}", response_model=EvidenceResponse)
    def evidence_by_id(evidence_id: str) -> EvidenceResponse:
        evidence = _state(app)["repositories"].evidence.get(evidence_id)
        if evidence is None or evidence.profile_id != DEFAULT_PROFILE_ID:
            raise HTTPException(status_code=404, detail="Evidence was not found.")
        return _evidence_response(evidence)

    @app.delete("/v1/evidence/{evidence_id}", response_model=EvidenceDeletionResponse)
    def delete_evidence(evidence_id: str) -> EvidenceDeletionResponse:
        repositories = _state(app)["repositories"]
        evidence = repositories.evidence.get(evidence_id)
        if evidence is None or evidence.profile_id != DEFAULT_PROFILE_ID:
            raise HTTPException(status_code=404, detail="Evidence was not found.")
        if not repositories.evidence.remove(evidence_id):
            raise HTTPException(status_code=404, detail="Evidence was not found.")
        snapshot = model_rebuilder(repositories, _state(app)["settings"]).rebuild(
            DEFAULT_PROFILE_ID, datetime.now(UTC)
        )
        return EvidenceDeletionResponse(
            removed_evidence_id=evidence_id, snapshot_version=snapshot.version
        )

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
        settings = _state(app)["settings"]
        register_normalized_aliases(
            repositories.evidence,
            alias_repository(repositories, settings),
            DEFAULT_PROFILE_ID,
            now,
        )
        snapshot = model_rebuilder(repositories, settings).rebuild(DEFAULT_PROFILE_ID, now)
        return PreferenceCorrectionResponse(
            evidence=_evidence_response(evidence), snapshot_version=snapshot.version
        )

    @app.post("/v1/decisions", response_model=DecisionResponse, status_code=201)
    async def create_decision(request: DecisionCreateRequest) -> DecisionResponse:
        runtime = _state(app)
        provider = None
        if any(not item.features for item in request.options):
            try:
                provider = _resolve_provider(runtime)
            except ValueError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="A configured model provider is required for feature extraction.",
                ) from exc
        repositories = runtime["repositories"]
        service = DecisionService(
            decisions=repositories.decisions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            outcomes=repositories.outcomes,
            provider=provider,
            aliases=alias_repository(repositories, runtime["settings"]),
            semantics=runtime["key_semantics"],
        )
        try:
            decision, options = await service.create(
                profile_id=DEFAULT_PROFILE_ID,
                domain=request.domain,
                question=request.question,
                context=request.context,
                option_inputs=tuple(
                    DecisionOptionInput(
                        item.label,
                        item.description,
                        item.features,
                        item.feature_confidence,
                    )
                    for item in request.options
                ),
            )
        except EgressDeniedError as exc:
            raise HTTPException(
                status_code=403, detail="The configured privacy mode denied model egress."
            ) from exc
        except ProviderError as exc:
            raise HTTPException(
                status_code=502, detail="The model provider request failed."
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=502, detail="The model provider returned invalid structured output."
            ) from exc
        return _decision_response(decision, options)

    @app.post(
        "/v1/decisions/{decision_id}/predict",
        response_model=DecisionPredictionResponse,
        status_code=201,
    )
    def predict_decision(decision_id: str) -> DecisionPredictionResponse:
        repositories = _state(app)["repositories"]
        service = DecisionService(
            decisions=repositories.decisions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            outcomes=repositories.outcomes,
            provider=None,
            aliases=alias_repository(repositories, _state(app)["settings"]),
        )
        try:
            prediction = service.predict(DEFAULT_PROFILE_ID, decision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Decision was not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        stored = repositories.decisions.get(decision_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Decision was not found.")
        support = [
            item
            for evidence_id in prediction.supporting_evidence_ids
            if (item := repositories.evidence.get(evidence_id)) is not None
        ]
        return _prediction_response(prediction, stored[1], support)

    @app.post(
        "/v1/decisions/{decision_id}/advise",
        response_model=DecisionAdviceResponse,
        status_code=201,
    )
    def advise_decision(decision_id: str) -> DecisionAdviceResponse:
        repositories = _state(app)["repositories"]
        service = DecisionService(
            decisions=repositories.decisions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            outcomes=repositories.outcomes,
            provider=None,
            aliases=alias_repository(repositories, _state(app)["settings"]),
        )
        try:
            advice = service.advise(DEFAULT_PROFILE_ID, decision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Decision was not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        stored = repositories.decisions.get(decision_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Decision was not found.")
        return _advice_response(advice, stored[1])

    @app.post(
        "/v1/decisions/{decision_id}/resolve",
        response_model=DecisionResolutionResponse,
        status_code=201,
    )
    def resolve_decision(
        decision_id: str, request: DecisionResolutionRequest
    ) -> DecisionResolutionResponse:
        repositories = _state(app)["repositories"]
        service = DecisionService(
            decisions=repositories.decisions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            outcomes=repositories.outcomes,
            provider=None,
            aliases=alias_repository(repositories, _state(app)["settings"]),
        )
        try:
            result = service.resolve(DEFAULT_PROFILE_ID, decision_id, request.chosen_option_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Decision or option was not found."
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _resolution_response(result)

    @app.post(
        "/v1/decisions/{decision_id}/outcome",
        response_model=DecisionOutcomeResponse,
        status_code=201,
    )
    def record_outcome(
        decision_id: str, request: DecisionOutcomeRequest
    ) -> DecisionOutcomeResponse:
        repositories = _state(app)["repositories"]
        service = DecisionService(
            decisions=repositories.decisions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            outcomes=repositories.outcomes,
            provider=None,
            aliases=alias_repository(repositories, _state(app)["settings"]),
        )
        try:
            outcome = service.record_outcome(
                DEFAULT_PROFILE_ID,
                decision_id,
                request.satisfaction,
                request.regret,
                request.notes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Decision was not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _outcome_response(outcome)

    @app.delete(
        "/v1/decisions/{decision_id}/outcome",
        response_model=DecisionOutcomeDeletionResponse,
    )
    def delete_outcome(decision_id: str) -> DecisionOutcomeDeletionResponse:
        repositories = _state(app)["repositories"]
        service = DecisionService(
            decisions=repositories.decisions,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            outcomes=repositories.outcomes,
            provider=None,
            aliases=alias_repository(repositories, _state(app)["settings"]),
        )
        try:
            outcome = service.delete_outcome(DEFAULT_PROFILE_ID, decision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Decision outcome was not found.") from exc
        return DecisionOutcomeDeletionResponse(removed_outcome_id=outcome.id)

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        runtime = _state(app)
        try:
            resolved_provider = _resolve_provider(runtime)
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="The configured model provider is unavailable."
            ) from exc
        repositories = runtime["repositories"]
        service = ConversationService(
            conversations=repositories.conversations,
            messages=repositories.messages,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            provider=resolved_provider,
            jobs=repositories.jobs,
            aliases=alias_repository(repositories, runtime["settings"]),
            catalog=repositories.key_catalog,
            semantics=runtime["key_semantics"],
        )
        try:
            result = await service.chat(
                DEFAULT_PROFILE_ID, request.content, request.conversation_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Conversation was not found.") from exc
        except EgressDeniedError as exc:
            raise HTTPException(
                status_code=403, detail="The configured privacy mode denied model egress."
            ) from exc
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail="The model provider is busy or unreachable. Try again shortly.",
            ) from exc
        except ProviderError as exc:
            raise HTTPException(
                status_code=502, detail="The model provider request failed."
            ) from exc
        except ValidationError as exc:
            raise HTTPException(
                status_code=502, detail="The model provider returned invalid structured output."
            ) from exc
        return ChatResponse(
            conversation_id=result.conversation_id,
            user_message_id=result.user_message_id,
            message=MessageResponse(
                id=result.assistant_message.id,
                role=result.assistant_message.role.value,
                content=result.assistant_message.content,
                provider_model=result.assistant_message.provider_model,
                created_at=result.assistant_message.created_at,
            ),
            accepted_evidence=[_evidence_response(item) for item in result.accepted_evidence],
            rejected_evidence_count=result.rejected_evidence_count,
            snapshot_version=result.snapshot_version,
            learning_status=result.learning_status,
            learning_error=result.learning_error,
        )

    app.include_router(build_access_router(app))
    app.include_router(build_external_router(app))
    app.include_router(build_data_router(app))
    app.include_router(build_connector_router(app))
    app.include_router(build_delegation_router(app))
    app.include_router(build_key_alias_router(app))
    app.include_router(build_key_label_router(app))
    app.include_router(build_learning_router(app))
    app.include_router(build_embedding_router(app))
    mount_web_client(app, resolved_settings.web_client_directory)
    return app
