"""Owner source control and the bounded push-ingestion surface for adapters."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from soulmate_core.access import ExternalAccessError
from soulmate_core.decision_io import (
    MAX_EVENT_CONTENT_BYTES,
    POLICY_PROFILE_VERSION,
    DecisionIoConflictError,
    DecisionIoError,
    validate_retention_policy,
)
from soulmate_core.domain import (
    AcquisitionMethod,
    AuditEvent,
    AuthorScope,
    ConsentMode,
    DataClass,
    DecisionIoEventType,
    EventActorType,
    ObservationStatus,
    OutcomeKind,
    OutcomeObservation,
    RawRetentionPolicy,
    ResolutionObservation,
    Source,
    SourceProvenance,
    TechnicalOutcomeStatus,
    UserDisposition,
)
from soulmate_core.preferences import ModelRebuilder

from soulmate_daemon.decision_io import (
    DecisionIoService,
    DecisionProjection,
    EventEnvelope,
    IngestionOutcome,
    OutcomeReport,
    ResolutionReport,
)
from soulmate_daemon.decisions import DecisionService
from soulmate_daemon.key_aliases import alias_repository, register_normalized_aliases
from soulmate_daemon.runtime import build_external_identity_service, runtime_of
from soulmate_daemon.security import Actor, ActorKind
from soulmate_daemon.system import DEFAULT_PROFILE_ID

MAX_OPTIONS = 20


class SourceRegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=200)
    service_identity_id: str = Field(min_length=1, max_length=200)
    data_classes: list[DataClass] = Field(min_length=1, max_length=len(DataClass))
    author_scope: AuthorScope = AuthorScope.MIXED
    raw_retention_policy: RawRetentionPolicy = RawRetentionPolicy.METADATA_ONLY
    adapter_version: str | None = Field(default=None, max_length=100)
    parser_version: str | None = Field(default=None, max_length=100)

    @field_validator("name", "provider", "service_identity_id")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Source identifiers must not be blank.")
        return value

    @field_validator("data_classes")
    @classmethod
    def data_classes_must_be_unique(cls, value: list[DataClass]) -> list[DataClass]:
        if len(set(value)) != len(value):
            raise ValueError("Source data classes must not repeat.")
        return value


class SourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    provider: str | None
    acquisition_method: AcquisitionMethod
    consent_mode: ConsentMode
    consent_at: datetime | None
    data_classes: list[DataClass]
    author_scope: AuthorScope
    raw_retention_policy: RawRetentionPolicy
    adapter_version: str | None
    parser_version: str | None
    policy_profile_version: str
    service_identity_id: str | None
    created_at: datetime
    raw_event_count: int
    decision_count: int
    resolution_observation_count: int
    outcome_observation_count: int
    unmatched_observation_count: int


class SourceDeletionResponse(BaseModel):
    source_id: str
    raw_event_count: int
    decision_count: int
    observation_count: int
    evidence_count: int
    model_rebuilt: bool


class EventEnvelopeRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    external_event_id: str = Field(min_length=1, max_length=200)
    occurred_at: datetime
    actor_type: EventActorType
    content: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1, ge=1, le=1_000)
    correlation_id: str | None = Field(default=None, max_length=200)
    causation_event_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_envelope(self) -> "EventEnvelopeRequest":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Event timestamps must include a UTC offset.")
        if len(str(self.content)) > MAX_EVENT_CONTENT_BYTES:
            raise ValueError("Event content is too large.")
        return self


class OptionRequest(BaseModel):
    external_option_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)
    features: dict[str, float] = Field(min_length=1, max_length=100)


class DecisionEventRequest(EventEnvelopeRequest):
    external_decision_id: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=10_000)
    context: dict[str, Any] = Field(default_factory=dict)
    options: list[OptionRequest] = Field(min_length=2, max_length=MAX_OPTIONS)


class ResolutionEventRequest(EventEnvelopeRequest):
    external_decision_id: str = Field(min_length=1, max_length=200)
    external_option_id: str = Field(min_length=1, max_length=200)
    disposition: UserDisposition = UserDisposition.ACCEPTED
    event_type: DecisionIoEventType = DecisionIoEventType.DECISION_RESOLUTION

    @field_validator("event_type")
    @classmethod
    def event_type_must_report_a_choice(cls, value: DecisionIoEventType) -> DecisionIoEventType:
        allowed = (DecisionIoEventType.DECISION_RESOLUTION, DecisionIoEventType.USER_OVERRIDE)
        if value not in allowed:
            raise ValueError("A resolution report must be a decision resolution or user override.")
        return value


class OutcomeEventRequest(EventEnvelopeRequest):
    external_decision_id: str = Field(min_length=1, max_length=200)
    kind: OutcomeKind
    technical_status: TechnicalOutcomeStatus | None = None
    disposition: UserDisposition | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "OutcomeEventRequest":
        if self.kind is OutcomeKind.OWNER_REPORTED:
            raise ValueError("Owner wellbeing cannot be reported by an external service.")
        return self


class InteractionEventRequest(EventEnvelopeRequest):
    event_type: DecisionIoEventType = DecisionIoEventType.INTERACTION

    @field_validator("event_type")
    @classmethod
    def event_type_must_be_contextual(cls, value: DecisionIoEventType) -> DecisionIoEventType:
        allowed = (
            DecisionIoEventType.INTERACTION,
            DecisionIoEventType.ACTION,
            DecisionIoEventType.CONTEXT,
            DecisionIoEventType.AGENT_PROPOSAL,
        )
        if value not in allowed:
            raise ValueError("This endpoint accepts interaction, action, context, or proposal.")
        return value


class IngestionResponse(BaseModel):
    event_id: str
    duplicate: bool
    evidence_eligibility: str
    actor_type: str
    policy_profile_version: str
    decision_id: str | None = None
    observation_id: str | None = None
    observation_status: str | None = None
    promoted: bool = False


class ObservationResponse(BaseModel):
    id: str
    kind: str
    source_id: str
    source_event_id: str
    actor_type: str
    status: str
    decision_id: str | None
    external_decision_id: str | None
    disposition: str | None
    technical_status: str | None
    satisfaction: float | None
    regret: bool | None
    reason_code: str | None
    created_at: datetime
    confirmed_at: datetime | None


class OwnerOutcomeConfirmation(BaseModel):
    satisfaction: float = Field(ge=0.0, le=1.0)
    regret: bool
    notes: str | None = Field(default=None, max_length=10_000)


def _owner(request: Request) -> Actor:
    actor = request.state.actor
    if not isinstance(actor, Actor) or not actor.is_owner:
        raise HTTPException(status_code=403, detail="This action is owner-only.")
    return actor


def _service_actor(request: Request) -> Actor:
    actor = request.state.actor
    if not isinstance(actor, Actor) or actor.kind is not ActorKind.SERVICE:
        raise HTTPException(status_code=401, detail="An external service API key is required.")
    return actor


def _service(app: FastAPI) -> DecisionIoService:
    repositories = runtime_of(app)["repositories"]
    return DecisionIoService(
        sources=repositories.sources,
        decision_io=repositories.decision_io,
        decisions=repositories.decisions,
        audits=repositories.audit_events,
    )


def _http_error(error: DecisionIoError) -> HTTPException:
    if isinstance(error, DecisionIoConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if error.reason_code in ("source_not_found", "decision_not_found", "observation_not_found"):
        return HTTPException(status_code=404, detail=str(error))
    if error.reason_code in (
        "decision_already_resolved",
        "observation_not_confirmable",
        "observation_state_changed",
    ):
        return HTTPException(status_code=409, detail=str(error))
    if error.reason_code in ("source_identity_mismatch", "source_not_ingestible"):
        return HTTPException(status_code=403, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


def _source_response(app: FastAPI, source: Source) -> SourceResponse:
    counts = runtime_of(app)["repositories"].decision_io.counts_for_source(
        DEFAULT_PROFILE_ID, source.id
    )
    provenance = source.provenance
    return SourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        provider=provenance.provider,
        acquisition_method=provenance.acquisition_method,
        consent_mode=provenance.consent_mode,
        consent_at=provenance.consent_at,
        data_classes=list(provenance.data_classes),
        author_scope=provenance.author_scope,
        raw_retention_policy=provenance.raw_retention_policy,
        adapter_version=provenance.adapter_version,
        parser_version=provenance.parser_version,
        policy_profile_version=provenance.policy_profile_version,
        service_identity_id=provenance.service_identity_id,
        created_at=source.created_at,
        raw_event_count=counts.raw_event_count,
        decision_count=counts.decision_count,
        resolution_observation_count=counts.resolution_observation_count,
        outcome_observation_count=counts.outcome_observation_count,
        unmatched_observation_count=counts.unmatched_observation_count,
    )


def _resolution_response(item: ResolutionObservation) -> ObservationResponse:
    return ObservationResponse(
        id=item.id,
        kind="resolution",
        source_id=item.source_id,
        source_event_id=item.source_event_id,
        actor_type=item.actor_type.value,
        status=item.status.value,
        decision_id=item.decision_id,
        external_decision_id=item.external_decision_id,
        disposition=item.disposition.value,
        technical_status=None,
        satisfaction=None,
        regret=None,
        reason_code=item.reason_code,
        created_at=item.created_at,
        confirmed_at=item.confirmed_at,
    )


def _outcome_response(item: OutcomeObservation) -> ObservationResponse:
    return ObservationResponse(
        id=item.id,
        kind=item.kind.value,
        source_id=item.source_id,
        source_event_id=item.source_event_id,
        actor_type=item.actor_type.value,
        status=item.status.value,
        decision_id=item.decision_id,
        external_decision_id=item.external_decision_id,
        disposition=None if item.disposition is None else item.disposition.value,
        technical_status=(None if item.technical_status is None else item.technical_status.value),
        satisfaction=item.satisfaction,
        regret=item.regret,
        reason_code=item.reason_code,
        created_at=item.created_at,
        confirmed_at=item.confirmed_at,
    )


def _ingestion_response(outcome: IngestionOutcome) -> IngestionResponse:
    result = outcome.result
    observation_id = result.resolution_observation_id or result.outcome_observation_id
    return IngestionResponse(
        event_id=result.event_id,
        duplicate=result.duplicate,
        evidence_eligibility=outcome.classification.eligibility.value,
        actor_type=outcome.classification.actor_type.value,
        policy_profile_version=outcome.classification.policy_profile_version,
        decision_id=result.decision_id,
        observation_id=observation_id,
        observation_status=(
            None if result.observation_status is None else result.observation_status.value
        ),
        promoted=outcome.promoted is not None,
    )


def _envelope(payload: EventEnvelopeRequest, event_type: DecisionIoEventType) -> EventEnvelope:
    return EventEnvelope(
        source_id=payload.source_id,
        external_event_id=payload.external_event_id,
        event_type=event_type,
        actor_type=payload.actor_type,
        occurred_at=payload.occurred_at,
        content=payload.content,
        schema_version=payload.schema_version,
        correlation_id=payload.correlation_id,
        causation_event_id=payload.causation_event_id,
    )


def _audit_owner(app: FastAPI, action: str, metadata: dict[str, object]) -> None:
    runtime_of(app)["repositories"].audit_events.add(
        AuditEvent(
            id=f"audit_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            action=action,
            actor_type="owner",
            actor_id=None,
            metadata=metadata,
            created_at=datetime.now(UTC),
        )
    )


def build_decision_io_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    def ingest(
        request: Request,
        payload: EventEnvelopeRequest,
        event_type: DecisionIoEventType,
        *,
        decision: DecisionProjection | None = None,
        resolution: ResolutionReport | None = None,
        outcome: OutcomeReport | None = None,
    ) -> IngestionResponse:
        actor = _service_actor(request)
        try:
            result = _service(app).record_event(
                profile_id=DEFAULT_PROFILE_ID,
                service_identity_id=actor.service_identity_id,
                envelope=_envelope(payload, event_type),
                decision=decision,
                resolution=resolution,
                outcome=outcome,
            )
        except DecisionIoError as error:
            raise _http_error(error) from error
        if result.promoted is not None:
            _refresh_model(app, register_aliases=True)
        return _ingestion_response(result)

    @router.post("/v1/decision-io/sources", response_model=SourceResponse, status_code=201)
    def register_source(request: Request, payload: SourceRegistrationRequest) -> SourceResponse:
        _owner(request)
        identities = build_external_identity_service(runtime_of(app))
        try:
            identity = identities.get_identity(DEFAULT_PROFILE_ID, payload.service_identity_id)
        except ExternalAccessError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if not identity.is_active:
            raise HTTPException(status_code=409, detail="The service identity is revoked.")
        now = datetime.now(UTC)
        try:
            provenance = SourceProvenance(
                provider=payload.provider.strip(),
                acquisition_method=AcquisitionMethod.AGENT_PUSH,
                consent_mode=ConsentMode.OWNER_EXPLICIT,
                consent_at=now,
                data_classes=tuple(payload.data_classes),
                author_scope=payload.author_scope,
                raw_retention_policy=validate_retention_policy(payload.raw_retention_policy),
                adapter_version=payload.adapter_version,
                parser_version=payload.parser_version,
                policy_profile_version=POLICY_PROFILE_VERSION,
                service_identity_id=identity.id,
            )
        except DecisionIoError as error:
            raise _http_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        source = Source(
            id=f"source_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            source_type=f"agent:{payload.provider.strip()}",
            name=payload.name.strip(),
            created_at=now,
            provenance=provenance,
        )
        runtime_of(app)["repositories"].sources.add(source)
        _audit_owner(
            app,
            "decision_io.source_registered",
            {
                "source_id": source.id,
                "service_identity_id": identity.id,
                "data_classes": [item.value for item in provenance.data_classes],
                "raw_retention_policy": provenance.raw_retention_policy.value,
            },
        )
        return _source_response(app, source)

    @router.get("/v1/decision-io/sources", response_model=list[SourceResponse])
    def list_sources(request: Request) -> list[SourceResponse]:
        _owner(request)
        sources = runtime_of(app)["repositories"].sources.list_for_profile(DEFAULT_PROFILE_ID)
        return [
            _source_response(app, item)
            for item in sources
            if item.provenance.acquisition_method is AcquisitionMethod.AGENT_PUSH
        ]

    @router.delete("/v1/decision-io/sources/{source_id}", response_model=SourceDeletionResponse)
    def delete_source(request: Request, source_id: str) -> SourceDeletionResponse:
        _owner(request)
        repositories = runtime_of(app)["repositories"]
        removed = repositories.decision_io.remove_source(DEFAULT_PROFILE_ID, source_id)
        if removed is None:
            raise HTTPException(status_code=404, detail="The source was not found.")
        if removed.evidence_count:
            _refresh_model(app)
        _audit_owner(
            app,
            "decision_io.source_removed",
            {
                "source_id": source_id,
                "raw_event_count": removed.raw_event_count,
                "decision_count": removed.decision_count,
                "observation_count": removed.observation_count,
                "evidence_count": removed.evidence_count,
            },
        )
        return SourceDeletionResponse(
            source_id=source_id,
            raw_event_count=removed.raw_event_count,
            decision_count=removed.decision_count,
            observation_count=removed.observation_count,
            evidence_count=removed.evidence_count,
            model_rebuilt=bool(removed.evidence_count),
        )

    @router.get("/v1/decision-io/observations", response_model=list[ObservationResponse])
    def list_observations(
        request: Request, status: ObservationStatus | None = None
    ) -> list[ObservationResponse]:
        _owner(request)
        repository = runtime_of(app)["repositories"].decision_io
        items = [
            _resolution_response(item)
            for item in repository.list_resolution_observations(DEFAULT_PROFILE_ID, status)
        ] + [
            _outcome_response(item)
            for item in repository.list_outcome_observations(DEFAULT_PROFILE_ID, status)
        ]
        return sorted(items, key=lambda item: (item.created_at, item.id), reverse=True)

    @router.post(
        "/v1/decision-io/observations/{observation_id}/confirm",
        response_model=ObservationResponse,
    )
    def confirm_observation(
        request: Request,
        observation_id: str,
        payload: OwnerOutcomeConfirmation | None = None,
    ) -> ObservationResponse:
        """Confirm a reported choice, or turn a satisfaction report into wellbeing.

        A reported choice becomes the canonical resolution with its choice Evidence.
        A satisfaction report needs the owner's own values; the agent's are never
        copied into owner wellbeing.
        """
        _owner(request)
        repository = runtime_of(app)["repositories"].decision_io
        outcome = repository.get_outcome_observation(DEFAULT_PROFILE_ID, observation_id)
        if outcome is None:
            try:
                promoted = _service(app).confirm_resolution(DEFAULT_PROFILE_ID, observation_id)
            except DecisionIoError as error:
                raise _http_error(error) from error
            _refresh_model(app, register_aliases=True)
            _audit_owner(
                app,
                "decision_io.observation_confirmed",
                {"observation_id": observation_id, "decision_id": promoted.decision_id},
            )
            confirmed_choice = repository.get_resolution_observation(
                DEFAULT_PROFILE_ID, observation_id
            )
            if confirmed_choice is None:
                raise HTTPException(status_code=404, detail="The observation was not found.")
            return _resolution_response(confirmed_choice)
        if outcome.kind is not OutcomeKind.OWNER_REPORTED:
            raise HTTPException(
                status_code=409,
                detail="Only a reported satisfaction can become owner wellbeing.",
            )
        if outcome.decision_id is None or outcome.status is not ObservationStatus.PENDING:
            raise HTTPException(
                status_code=409, detail="Only a matched, pending report can be confirmed."
            )
        if payload is None:
            raise HTTPException(
                status_code=422, detail="Your own satisfaction and regret are required."
            )
        # The owner's outcome is written first: if marking the report fails, the
        # owner's own values still stand and the report stays open for review.
        _record_owner_outcome(app, outcome.decision_id, payload)
        repository.set_outcome_observation_status(
            observation_id,
            ObservationStatus.PENDING,
            ObservationStatus.CONFIRMED,
            "owner_confirmed",
            datetime.now(UTC),
        )
        _audit_owner(
            app,
            "decision_io.observation_confirmed",
            {"observation_id": observation_id, "decision_id": outcome.decision_id},
        )
        confirmed = repository.get_outcome_observation(DEFAULT_PROFILE_ID, observation_id)
        if confirmed is None:
            raise HTTPException(status_code=404, detail="The observation was not found.")
        return _outcome_response(confirmed)

    @router.post(
        "/v1/decision-io/observations/{observation_id}/reject",
        response_model=ObservationResponse,
    )
    def reject_observation(request: Request, observation_id: str) -> ObservationResponse:
        _owner(request)
        repository = runtime_of(app)["repositories"].decision_io
        outcome = repository.get_outcome_observation(DEFAULT_PROFILE_ID, observation_id)
        resolution = repository.get_resolution_observation(DEFAULT_PROFILE_ID, observation_id)
        if outcome is None and resolution is None:
            raise HTTPException(status_code=404, detail="The observation was not found.")
        if outcome is not None:
            changed = repository.set_outcome_observation_status(
                observation_id,
                outcome.status,
                ObservationStatus.REJECTED,
                "owner_rejected",
                None,
            )
        else:
            assert resolution is not None  # noqa: S101 -- narrowed by the guard above.
            changed = repository.set_resolution_observation_status(
                observation_id,
                resolution.status,
                ObservationStatus.REJECTED,
                "owner_rejected",
                None,
            )
        if not changed:
            raise HTTPException(status_code=409, detail="The observation state changed.")
        _audit_owner(app, "decision_io.observation_rejected", {"observation_id": observation_id})
        rejected_outcome = repository.get_outcome_observation(DEFAULT_PROFILE_ID, observation_id)
        if rejected_outcome is not None:
            return _outcome_response(rejected_outcome)
        rejected = repository.get_resolution_observation(DEFAULT_PROFILE_ID, observation_id)
        if rejected is None:
            raise HTTPException(status_code=404, detail="The observation was not found.")
        return _resolution_response(rejected)

    @router.post(
        "/v1/external/decision-io/interactions",
        response_model=IngestionResponse,
        status_code=201,
    )
    def record_interaction(request: Request, payload: InteractionEventRequest) -> IngestionResponse:
        return ingest(request, payload, payload.event_type)

    @router.post(
        "/v1/external/decision-io/decisions",
        response_model=IngestionResponse,
        status_code=201,
    )
    def record_decision(request: Request, payload: DecisionEventRequest) -> IngestionResponse:
        projection = DecisionProjection(
            external_decision_id=payload.external_decision_id,
            domain=payload.domain,
            question=payload.question,
            context=dict(payload.context),
            options=tuple(
                (item.external_option_id, item.label, item.description, item.features)
                for item in payload.options
            ),
        )
        return ingest(
            request,
            payload,
            DecisionIoEventType.DECISION_CANDIDATE,
            decision=projection,
        )

    @router.post(
        "/v1/external/decision-io/resolutions",
        response_model=IngestionResponse,
        status_code=201,
    )
    def record_resolution(request: Request, payload: ResolutionEventRequest) -> IngestionResponse:
        return ingest(
            request,
            payload,
            payload.event_type,
            resolution=ResolutionReport(
                external_decision_id=payload.external_decision_id,
                external_option_id=payload.external_option_id,
                disposition=payload.disposition,
            ),
        )

    @router.post(
        "/v1/external/decision-io/outcomes",
        response_model=IngestionResponse,
        status_code=201,
    )
    def observe_outcome(request: Request, payload: OutcomeEventRequest) -> IngestionResponse:
        event_type = (
            DecisionIoEventType.TECHNICAL_OUTCOME
            if payload.kind is OutcomeKind.TECHNICAL
            else DecisionIoEventType.USER_OUTCOME
        )
        return ingest(
            request,
            payload,
            event_type,
            outcome=OutcomeReport(
                external_decision_id=payload.external_decision_id,
                technical_status=payload.technical_status,
                disposition=payload.disposition,
            ),
        )

    return router


def _decision_service(app: FastAPI) -> DecisionService:
    repositories = runtime_of(app)["repositories"]
    return DecisionService(
        decisions=repositories.decisions,
        raw_events=repositories.raw_events,
        evidence=repositories.evidence,
        models=repositories.personal_models,
        outcomes=repositories.outcomes,
        provider=None,
        aliases=alias_repository(repositories, runtime_of(app)["settings"]),
    )


def _record_owner_outcome(
    app: FastAPI, decision_id: str, payload: OwnerOutcomeConfirmation
) -> None:
    try:
        _decision_service(app).record_outcome(
            DEFAULT_PROFILE_ID, decision_id, payload.satisfaction, payload.regret, payload.notes
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="The decision was not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _refresh_model(app: FastAPI, *, register_aliases: bool = False) -> None:
    """Rebuild derived state after Evidence changed; recoverable by revision."""
    repositories = runtime_of(app)["repositories"]
    aliases = alias_repository(repositories, runtime_of(app)["settings"])
    now = datetime.now(UTC)
    if register_aliases:
        register_normalized_aliases(repositories.evidence, aliases, DEFAULT_PROFILE_ID, now)
    ModelRebuilder(repositories.evidence, repositories.personal_models, aliases).rebuild(
        DEFAULT_PROFILE_ID, now
    )


__all__ = ["build_decision_io_router"]
