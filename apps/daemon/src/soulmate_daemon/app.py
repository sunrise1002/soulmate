"""FastAPI composition root for the local Soulmate service."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TypedDict, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from soulmate_core.domain import (
    Conversation,
    DecisionEvent,
    DecisionOption,
    DecisionPrediction,
    DecisionResolution,
    Evidence,
    EvidenceTargetType,
    Preference,
    RawEvent,
)
from soulmate_core.preferences import ModelRebuilder
from soulmate_llm_providers import EgressDeniedError, LLMProvider, ProviderError
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from soulmate_daemon import __version__
from soulmate_daemon.config import Settings
from soulmate_daemon.conversation import ConversationService
from soulmate_daemon.decisions import DecisionOptionInput, DecisionService, ResolutionResult
from soulmate_daemon.jobs import DurableJobWorker
from soulmate_daemon.providers import build_provider
from soulmate_daemon.system import DEFAULT_PROFILE_ID, ensure_installation


class AppState(TypedDict):
    settings: Settings
    database: Database
    repositories: Repositories
    installation_id: str
    provider: LLMProvider | None


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


class DecisionHistoryResponse(BaseModel):
    decision: DecisionResponse
    prediction: DecisionPredictionResponse | None
    resolution: ResolutionHistoryResponse | None


class EvidenceDeletionResponse(BaseModel):
    removed_evidence_id: str
    snapshot_version: int


def _state(app: FastAPI) -> AppState:
    return cast(AppState, app.state.runtime)


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


def create_app(settings: Settings | None = None, *, provider: LLMProvider | None = None) -> FastAPI:
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
            provider=provider,
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

    @app.get("/v1/conversations", response_model=list[ConversationResponse])
    def conversations() -> list[ConversationResponse]:
        repositories = _state(app)["repositories"]
        records: tuple[Conversation, ...] = repositories.conversations.list_for_profile(
            DEFAULT_PROFILE_ID
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
                    )
                    for message in repositories.messages.list_for_conversation(conversation.id)
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
        snapshot = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
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
        snapshot = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
            DEFAULT_PROFILE_ID, now
        )
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
            provider=provider,
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
            provider=None,
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
            provider=None,
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
        )

    return app
