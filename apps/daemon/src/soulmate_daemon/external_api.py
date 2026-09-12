"""Owner-managed external identities and privacy-minimal intelligence endpoints."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from soulmate_core.access import SERVICE_SCOPES, ExternalAccessError
from soulmate_core.decisions import ResolvedDecision, find_similar_decisions
from soulmate_core.domain import (
    ApiCredential,
    AuditEvent,
    DecisionEvent,
    DecisionOption,
    DecisionPrediction,
    DecisionStatus,
    ServiceIdentity,
)

from soulmate_daemon.decisions import DecisionOptionInput, DecisionService
from soulmate_daemon.runtime import build_external_identity_service, runtime_of
from soulmate_daemon.security import Actor, ActorKind
from soulmate_daemon.system import DEFAULT_PROFILE_ID


class ExternalOptionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)
    features: dict[str, float] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_option(self) -> "ExternalOptionRequest":
        if not self.label.strip() or not self.description.strip():
            raise ValueError("External decision option text must not be blank.")
        if any(not key.strip() or not -1.0 <= value <= 1.0 for key, value in self.features.items()):
            raise ValueError("External option feature values must be between -1 and 1.")
        return self


class ExternalDecisionRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=10_000)
    context: dict[str, object] = Field(default_factory=dict)
    options: list[ExternalOptionRequest] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def validate_decision(self) -> "ExternalDecisionRequest":
        if not self.domain.strip() or not self.question.strip():
            raise ValueError("External decision text must not be blank.")
        labels = [item.label.casefold() for item in self.options]
        if len(labels) != len(set(labels)):
            raise ValueError("External decision option labels must be unique.")
        return self


class ServiceIdentityCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    scopes: list[str] = Field(min_length=1, max_length=len(SERVICE_SCOPES))

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Service identity name must not be blank.")
        return value

    @field_validator("scopes")
    @classmethod
    def scopes_must_be_known(cls, value: list[str]) -> list[str]:
        unknown = next((scope for scope in value if scope not in SERVICE_SCOPES), None)
        if unknown is not None:
            raise ValueError(f"Unknown permission scope: {unknown}")
        return value


class ServiceIdentityScopesRequest(BaseModel):
    scopes: list[str] = Field(min_length=1, max_length=len(SERVICE_SCOPES))

    @field_validator("scopes")
    @classmethod
    def scopes_must_be_known(cls, value: list[str]) -> list[str]:
        unknown = next((scope for scope in value if scope not in SERVICE_SCOPES), None)
        if unknown is not None:
            raise ValueError(f"Unknown permission scope: {unknown}")
        return value


class ApiCredentialResponse(BaseModel):
    id: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    active: bool


class ServiceIdentityResponse(BaseModel):
    id: str
    name: str
    description: str | None
    scopes: tuple[str, ...]
    created_at: datetime
    revoked_at: datetime | None
    active: bool
    credentials: list[ApiCredentialResponse]


class IssuedServiceIdentityResponse(BaseModel):
    identity: ServiceIdentityResponse
    api_key: str


class IssuedCredentialResponse(BaseModel):
    credential: ApiCredentialResponse
    api_key: str


class AuditEventResponse(BaseModel):
    id: str
    action: str
    actor_type: str
    actor_id: str | None
    metadata: dict[str, object] | None
    created_at: datetime


class ExternalDecisionResponse(BaseModel):
    id: str
    domain: str
    question: str
    status: str
    option_ids: list[str]
    created_at: datetime


class ExternalRankingItemResponse(BaseModel):
    option_id: str
    label: str
    probability: float
    utility: float


class ExternalPredictionResponse(BaseModel):
    decision_id: str
    predicted_option_id: str
    predicted_choice: str
    ranking: list[ExternalRankingItemResponse]
    confidence: float
    important_factors: tuple[str, ...]
    uncertain_factors: tuple[str, ...]
    similar_decision_ids: tuple[str, ...]
    model_snapshot_version: int
    algorithm_version: str


class PreferenceSummaryResponse(BaseModel):
    key: str
    value: float
    uncertainty: float
    confidence: float
    context: dict[str, object]
    model_version: int


class ExternalModelSummaryResponse(BaseModel):
    version: int | None
    algorithm_version: str | None
    evidence_revision: int
    preference_count: int
    fact_count: int
    goal_count: int
    constraint_count: int


class SimilarDecisionResponse(BaseModel):
    decision_id: str
    domain: str
    similarity: float


class ExternalOutcomeRequest(BaseModel):
    decision_id: str = Field(min_length=1, max_length=200)
    satisfaction: float = Field(ge=0.0, le=1.0)
    regret: bool
    notes: str | None = Field(default=None, max_length=10_000)

    @field_validator("notes")
    @classmethod
    def notes_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Outcome notes must be omitted or contain text.")
        return value


class ExternalOutcomeResponse(BaseModel):
    id: str
    decision_id: str
    satisfaction: float
    regret: bool
    created_at: datetime


def _actor(request: Request) -> Actor:
    actor = request.state.actor
    if not isinstance(actor, Actor) or actor.kind is not ActorKind.SERVICE:
        raise HTTPException(status_code=401, detail="An external service API key is required.")
    return actor


def _credential_response(credential: ApiCredential) -> ApiCredentialResponse:
    return ApiCredentialResponse(
        id=credential.id,
        created_at=credential.created_at,
        last_used_at=credential.last_used_at,
        revoked_at=credential.revoked_at,
        active=credential.is_active,
    )


def _identity_response(app: FastAPI, identity: ServiceIdentity) -> ServiceIdentityResponse:
    service = build_external_identity_service(runtime_of(app))
    return ServiceIdentityResponse(
        id=identity.id,
        name=identity.name,
        description=identity.description,
        scopes=identity.scopes,
        created_at=identity.created_at,
        revoked_at=identity.revoked_at,
        active=identity.is_active,
        credentials=[
            _credential_response(item)
            for item in service.list_credentials(DEFAULT_PROFILE_ID, identity.id)
        ],
    )


def _audit_owner_action(
    app: FastAPI, action: str, identity_id: str, metadata: dict[str, object] | None = None
) -> None:
    runtime_of(app)["repositories"].audit_events.add(
        AuditEvent(
            id=f"audit_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            action=action,
            actor_type="owner",
            actor_id=None,
            metadata={"service_identity_id": identity_id, **(metadata or {})},
            created_at=datetime.now(UTC),
        )
    )


def _decision_service(app: FastAPI) -> DecisionService:
    repositories = runtime_of(app)["repositories"]
    return DecisionService(
        decisions=repositories.decisions,
        raw_events=repositories.raw_events,
        evidence=repositories.evidence,
        models=repositories.personal_models,
        outcomes=repositories.outcomes,
        provider=None,
    )


async def _create_decision(
    app: FastAPI, payload: ExternalDecisionRequest
) -> tuple[DecisionEvent, tuple[DecisionOption, ...]]:
    return await _decision_service(app).create(
        profile_id=DEFAULT_PROFILE_ID,
        domain=payload.domain,
        question=payload.question,
        context=payload.context,
        option_inputs=tuple(
            DecisionOptionInput(item.label, item.description, item.features, 1.0)
            for item in payload.options
        ),
    )


def _external_decision_response(
    decision: DecisionEvent, options: tuple[DecisionOption, ...]
) -> ExternalDecisionResponse:
    return ExternalDecisionResponse(
        id=decision.id,
        domain=decision.domain,
        question=decision.question,
        status=decision.status.value,
        option_ids=[item.id for item in options],
        created_at=decision.created_at,
    )


def _external_prediction_response(
    prediction: DecisionPrediction, options: tuple[DecisionOption, ...]
) -> ExternalPredictionResponse:
    labels = {item.id: item.label for item in options}
    winner = prediction.ranking[0]
    return ExternalPredictionResponse(
        decision_id=prediction.decision_id,
        predicted_option_id=winner.option_id,
        predicted_choice=labels[winner.option_id],
        ranking=[
            ExternalRankingItemResponse(
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
        similar_decision_ids=prediction.similar_decision_ids,
        model_snapshot_version=prediction.model_snapshot_version,
        algorithm_version=prediction.algorithm_version,
    )


def build_external_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/service-identities/scopes", response_model=list[str])
    def list_scopes() -> list[str]:
        return list(SERVICE_SCOPES)

    @router.get("/v1/service-identities", response_model=list[ServiceIdentityResponse])
    def list_identities() -> list[ServiceIdentityResponse]:
        service = build_external_identity_service(runtime_of(app))
        return [
            _identity_response(app, item) for item in service.list_identities(DEFAULT_PROFILE_ID)
        ]

    @router.post(
        "/v1/service-identities", response_model=IssuedServiceIdentityResponse, status_code=201
    )
    def create_identity(payload: ServiceIdentityCreateRequest) -> IssuedServiceIdentityResponse:
        service = build_external_identity_service(runtime_of(app))
        try:
            issued = service.create(
                profile_id=DEFAULT_PROFILE_ID,
                name=payload.name,
                description=payload.description,
                scopes=tuple(payload.scopes),
                now=datetime.now(UTC),
            )
        except ExternalAccessError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _audit_owner_action(app, "service_identity_created", issued.identity.id)
        return IssuedServiceIdentityResponse(
            identity=_identity_response(app, issued.identity), api_key=issued.api_key
        )

    @router.post(
        "/v1/service-identities/{identity_id}/scopes",
        response_model=ServiceIdentityResponse,
    )
    def replace_identity_scopes(
        identity_id: str, payload: ServiceIdentityScopesRequest
    ) -> ServiceIdentityResponse:
        service = build_external_identity_service(runtime_of(app))
        try:
            identity = service.replace_scopes(
                DEFAULT_PROFILE_ID, identity_id, tuple(payload.scopes)
            )
        except ExternalAccessError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _audit_owner_action(app, "service_identity_scopes_changed", identity.id)
        return _identity_response(app, identity)

    @router.post(
        "/v1/service-identities/{identity_id}/credentials",
        response_model=IssuedCredentialResponse,
        status_code=201,
    )
    def issue_credential(identity_id: str) -> IssuedCredentialResponse:
        service = build_external_identity_service(runtime_of(app))
        try:
            service.get_identity(DEFAULT_PROFILE_ID, identity_id)
            issued = service.issue_credential(identity_id, datetime.now(UTC))
        except ExternalAccessError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _audit_owner_action(
            app,
            "api_credential_created",
            issued.identity.id,
            {"credential_id": issued.credential.id},
        )
        return IssuedCredentialResponse(
            credential=_credential_response(issued.credential), api_key=issued.api_key
        )

    @router.delete(
        "/v1/service-identities/{identity_id}/credentials/{credential_id}",
        response_model=ApiCredentialResponse,
    )
    def revoke_credential(identity_id: str, credential_id: str) -> ApiCredentialResponse:
        service = build_external_identity_service(runtime_of(app))
        try:
            credential = service.revoke_credential(
                DEFAULT_PROFILE_ID, identity_id, credential_id, datetime.now(UTC)
            )
        except ExternalAccessError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _audit_owner_action(
            app,
            "api_credential_revoked",
            identity_id,
            {"credential_id": credential.id},
        )
        return _credential_response(credential)

    @router.delete("/v1/service-identities/{identity_id}", response_model=ServiceIdentityResponse)
    def revoke_identity(identity_id: str) -> ServiceIdentityResponse:
        service = build_external_identity_service(runtime_of(app))
        try:
            identity = service.revoke_identity(DEFAULT_PROFILE_ID, identity_id, datetime.now(UTC))
        except ExternalAccessError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _audit_owner_action(app, "service_identity_revoked", identity.id)
        return _identity_response(app, identity)

    @router.get("/v1/audit/events", response_model=list[AuditEventResponse])
    def audit_events(
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[AuditEventResponse]:
        records = runtime_of(app)["repositories"].audit_events.list_for_profile(
            DEFAULT_PROFILE_ID, limit
        )
        return [
            AuditEventResponse(
                id=item.id,
                action=item.action,
                actor_type=item.actor_type,
                actor_id=item.actor_id,
                metadata=item.metadata,
                created_at=item.created_at,
            )
            for item in records
        ]

    @router.post(
        "/v1/external/record-decision",
        response_model=ExternalDecisionResponse,
        status_code=201,
    )
    async def external_record_decision(
        request: Request, payload: ExternalDecisionRequest
    ) -> ExternalDecisionResponse:
        _actor(request)
        decision, options = await _create_decision(app, payload)
        return _external_decision_response(decision, options)

    async def predict(payload: ExternalDecisionRequest) -> ExternalPredictionResponse:
        decision, options = await _create_decision(app, payload)
        prediction = _decision_service(app).predict(DEFAULT_PROFILE_ID, decision.id)
        return _external_prediction_response(prediction, options)

    @router.post(
        "/v1/external/predict-choice",
        response_model=ExternalPredictionResponse,
        status_code=201,
    )
    async def external_predict_choice(
        request: Request, payload: ExternalDecisionRequest
    ) -> ExternalPredictionResponse:
        _actor(request)
        return await predict(payload)

    @router.post(
        "/v1/external/rank-options",
        response_model=ExternalPredictionResponse,
        status_code=201,
    )
    async def external_rank_options(
        request: Request, payload: ExternalDecisionRequest
    ) -> ExternalPredictionResponse:
        _actor(request)
        return await predict(payload)

    @router.get("/v1/external/preference-summary", response_model=list[PreferenceSummaryResponse])
    def external_preference_summary(request: Request) -> list[PreferenceSummaryResponse]:
        _actor(request)
        preferences = runtime_of(app)["repositories"].personal_models.list_preferences(
            DEFAULT_PROFILE_ID
        )
        return [
            PreferenceSummaryResponse(
                key=item.key,
                value=item.value,
                uncertainty=item.uncertainty,
                confidence=item.confidence,
                context=item.context,
                model_version=item.model_version,
            )
            for item in preferences
        ]

    @router.get("/v1/external/model-summary", response_model=ExternalModelSummaryResponse)
    def external_model_summary(request: Request) -> ExternalModelSummaryResponse:
        _actor(request)
        repositories = runtime_of(app)["repositories"]
        snapshot = repositories.personal_models.latest_snapshot(DEFAULT_PROFILE_ID)
        if snapshot is None:
            return ExternalModelSummaryResponse(
                version=None,
                algorithm_version=None,
                evidence_revision=repositories.evidence.current_revision(DEFAULT_PROFILE_ID),
                preference_count=0,
                fact_count=0,
                goal_count=0,
                constraint_count=0,
            )
        return ExternalModelSummaryResponse(
            version=snapshot.version,
            algorithm_version=snapshot.algorithm_version,
            evidence_revision=snapshot.evidence_revision,
            preference_count=len(snapshot.model.preferences),
            fact_count=len(snapshot.model.facts),
            goal_count=len(snapshot.model.goals),
            constraint_count=len(snapshot.model.constraints),
        )

    @router.post(
        "/v1/external/find-similar-decisions", response_model=list[SimilarDecisionResponse]
    )
    def external_find_similar(
        request: Request, payload: ExternalDecisionRequest
    ) -> list[SimilarDecisionResponse]:
        _actor(request)
        now = datetime.now(UTC)
        decision = DecisionEvent(
            id=f"query_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            domain=payload.domain,
            question=payload.question,
            context=payload.context,
            status=DecisionStatus.OPEN,
            created_at=now,
        )
        options = tuple(
            DecisionOption(
                id=f"query_option_{index}",
                decision_id=decision.id,
                label=item.label,
                description=item.description,
                features=item.features,
                feature_confidence=1.0,
            )
            for index, item in enumerate(payload.options)
        )
        repositories = runtime_of(app)["repositories"]
        history = tuple(
            ResolvedDecision(item, historical_options, resolution)
            for item, historical_options, resolution in repositories.decisions.list_resolved(
                DEFAULT_PROFILE_ID
            )
        )
        return [
            SimilarDecisionResponse(
                decision_id=item.decision_id,
                domain=item.domain,
                similarity=item.similarity,
            )
            for item in find_similar_decisions(decision, options, history)
        ]

    @router.post(
        "/v1/external/record-outcome",
        response_model=ExternalOutcomeResponse,
        status_code=201,
    )
    def external_record_outcome(
        request: Request, payload: ExternalOutcomeRequest
    ) -> ExternalOutcomeResponse:
        _actor(request)
        try:
            outcome = _decision_service(app).record_outcome(
                DEFAULT_PROFILE_ID,
                payload.decision_id,
                payload.satisfaction,
                payload.regret,
                payload.notes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Decision was not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ExternalOutcomeResponse(
            id=outcome.id,
            decision_id=outcome.decision_id,
            satisfaction=outcome.satisfaction,
            regret=outcome.regret,
            created_at=outcome.created_at,
        )

    return router


__all__ = ["build_external_router"]
