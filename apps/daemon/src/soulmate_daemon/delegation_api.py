"""Owner policy management and scoped delegated-action approval endpoints."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from soulmate_core.access import AGENT_DELEGATE, ExternalAccessError
from soulmate_core.delegation import DelegationError, DelegationPolicyEngine
from soulmate_core.domain import (
    AuditEvent,
    DecisionImpact,
    DelegationPolicy,
    DelegationRequest,
)

from soulmate_daemon.runtime import build_external_identity_service, runtime_of
from soulmate_daemon.security import Actor, ActorKind
from soulmate_daemon.system import DEFAULT_PROFILE_ID


class DelegationPolicyRequest(BaseModel):
    service_identity_id: str = Field(min_length=1, max_length=200)
    action_type: str = Field(min_length=1, max_length=200)
    impact: DecisionImpact
    minimum_confidence: float = Field(ge=0.0, le=1.0)
    allow_automatic: bool = False

    @field_validator("service_identity_id", "action_type")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Delegation identifiers must not be blank.")
        return value


class DelegationPolicyResponse(BaseModel):
    id: str
    service_identity_id: str
    action_type: str
    impact: DecisionImpact
    minimum_confidence: float
    allow_automatic: bool
    created_at: datetime
    updated_at: datetime


class DelegationRequestInput(BaseModel):
    decision_id: str = Field(min_length=1, max_length=200)
    action_type: str = Field(min_length=1, max_length=200)
    action_label: str = Field(min_length=1, max_length=500)
    external_request_id: str = Field(min_length=1, max_length=200)

    @field_validator("decision_id", "action_type", "action_label", "external_request_id")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Delegation request values must not be blank.")
        return value


class DelegationRequestResponse(BaseModel):
    id: str
    service_identity_id: str
    policy_id: str | None
    decision_id: str
    prediction_id: str
    external_request_id: str
    action_type: str
    action_label: str
    impact: DecisionImpact
    predicted_option_id: str
    prediction_confidence: float
    status: str
    reason_code: str
    requested_at: datetime
    expires_at: datetime
    reviewed_at: datetime | None
    completed_at: datetime | None
    expired_at: datetime | None


def _engine(app: FastAPI) -> DelegationPolicyEngine:
    repositories = runtime_of(app)["repositories"]
    return DelegationPolicyEngine(
        repositories.delegation_policies,
        repositories.delegation_requests,
        repositories.decisions,
        repositories.personal_models,
    )


def _response(request: DelegationRequest) -> DelegationRequestResponse:
    return DelegationRequestResponse(
        id=request.id,
        service_identity_id=request.service_identity_id,
        policy_id=request.policy_id,
        decision_id=request.decision_id,
        prediction_id=request.prediction_id,
        external_request_id=request.external_request_id,
        action_type=request.action_type,
        action_label=request.action_label,
        impact=request.impact,
        predicted_option_id=request.predicted_option_id,
        prediction_confidence=request.prediction_confidence,
        status=request.status.value,
        reason_code=request.reason_code,
        requested_at=request.requested_at,
        expires_at=request.expires_at,
        reviewed_at=request.reviewed_at,
        completed_at=request.completed_at,
        expired_at=request.expired_at,
    )


def _policy_response(policy: DelegationPolicy) -> DelegationPolicyResponse:
    return DelegationPolicyResponse(
        id=policy.id,
        service_identity_id=policy.service_identity_id,
        action_type=policy.action_type,
        impact=policy.impact,
        minimum_confidence=policy.minimum_confidence,
        allow_automatic=policy.allow_automatic,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _service_actor(request: Request) -> Actor:
    actor = request.state.actor
    if not isinstance(actor, Actor) or actor.kind is not ActorKind.SERVICE:
        raise HTTPException(status_code=401, detail="An external service API key is required.")
    return actor


def _audit(
    app: FastAPI,
    action: str,
    *,
    actor_type: str,
    actor_id: str | None,
    metadata: dict[str, object],
) -> None:
    runtime_of(app)["repositories"].audit_events.add(
        AuditEvent(
            id=f"audit_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            metadata=metadata,
            created_at=datetime.now(UTC),
        )
    )


def _delegation_http_error(exc: DelegationError) -> HTTPException:
    detail = str(exc)
    return HTTPException(status_code=404 if "not found" in detail else 409, detail=detail)


def build_delegation_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/delegation-policies", response_model=list[DelegationPolicyResponse])
    def list_policies() -> list[DelegationPolicyResponse]:
        policies = runtime_of(app)["repositories"].delegation_policies.list_for_profile(
            DEFAULT_PROFILE_ID
        )
        return [_policy_response(item) for item in policies]

    @router.post(
        "/v1/delegation-policies",
        response_model=DelegationPolicyResponse,
        status_code=201,
    )
    def set_policy(payload: DelegationPolicyRequest) -> DelegationPolicyResponse:
        identities = build_external_identity_service(runtime_of(app))
        try:
            identity = identities.get_identity(DEFAULT_PROFILE_ID, payload.service_identity_id)
        except ExternalAccessError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not identity.is_active or AGENT_DELEGATE not in identity.scopes:
            raise HTTPException(
                status_code=409,
                detail="The service identity must be active and have the 'agent:delegate' scope.",
            )
        try:
            policy = _engine(app).set_policy(
                profile_id=DEFAULT_PROFILE_ID,
                service_identity_id=identity.id,
                action_type=payload.action_type,
                impact=payload.impact,
                minimum_confidence=payload.minimum_confidence,
                allow_automatic=payload.allow_automatic,
                now=datetime.now(UTC),
            )
        except DelegationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _audit(
            app,
            "delegation_policy_set",
            actor_type="owner",
            actor_id=None,
            metadata={
                "policy_id": policy.id,
                "service_identity_id": identity.id,
                "action_type": policy.action_type,
                "impact": policy.impact.value,
            },
        )
        return _policy_response(policy)

    @router.delete("/v1/delegation-policies/{policy_id}", status_code=204)
    def remove_policy(policy_id: str) -> None:
        try:
            _engine(app).remove_policy(DEFAULT_PROFILE_ID, policy_id)
        except DelegationError as exc:
            raise _delegation_http_error(exc) from exc
        _audit(
            app,
            "delegation_policy_removed",
            actor_type="owner",
            actor_id=None,
            metadata={"policy_id": policy_id},
        )

    @router.get("/v1/delegation-requests", response_model=list[DelegationRequestResponse])
    def list_requests() -> list[DelegationRequestResponse]:
        return [
            _response(item)
            for item in _engine(app).list_for_owner(DEFAULT_PROFILE_ID, datetime.now(UTC))
        ]

    def review(request_id: str, approved: bool) -> DelegationRequestResponse:
        try:
            result = _engine(app).review(
                profile_id=DEFAULT_PROFILE_ID,
                request_id=request_id,
                approved=approved,
                now=datetime.now(UTC),
            )
        except DelegationError as exc:
            raise _delegation_http_error(exc) from exc
        _audit(
            app,
            "delegation_request_approved" if approved else "delegation_request_rejected",
            actor_type="owner",
            actor_id=None,
            metadata={
                "delegation_request_id": result.id,
                "service_identity_id": result.service_identity_id,
            },
        )
        return _response(result)

    @router.post(
        "/v1/delegation-requests/{request_id}/approve",
        response_model=DelegationRequestResponse,
    )
    def approve_request(request_id: str) -> DelegationRequestResponse:
        return review(request_id, True)

    @router.post(
        "/v1/delegation-requests/{request_id}/reject",
        response_model=DelegationRequestResponse,
    )
    def reject_request(request_id: str) -> DelegationRequestResponse:
        return review(request_id, False)

    @router.post(
        "/v1/external/delegation-requests",
        response_model=DelegationRequestResponse,
        status_code=201,
    )
    def request_delegation(
        request: Request, payload: DelegationRequestInput
    ) -> DelegationRequestResponse:
        actor = _service_actor(request)
        if actor.service_identity_id is None:
            raise HTTPException(status_code=401, detail="An external service API key is required.")
        try:
            result = _engine(app).request(
                profile_id=DEFAULT_PROFILE_ID,
                service_identity_id=actor.service_identity_id,
                decision_id=payload.decision_id,
                action_type=payload.action_type,
                action_label=payload.action_label,
                external_request_id=payload.external_request_id,
                now=datetime.now(UTC),
            )
        except DelegationError as exc:
            raise _delegation_http_error(exc) from exc
        _audit(
            app,
            "delegation_request_created",
            actor_type="service",
            actor_id=actor.service_identity_id,
            metadata={
                "delegation_request_id": result.id,
                "policy_id": result.policy_id or "removed",
                "status": result.status.value,
            },
        )
        return _response(result)

    @router.get(
        "/v1/external/delegation-requests/{request_id}",
        response_model=DelegationRequestResponse,
    )
    def get_delegation(request: Request, request_id: str) -> DelegationRequestResponse:
        actor = _service_actor(request)
        if actor.service_identity_id is None:
            raise HTTPException(status_code=401, detail="An external service API key is required.")
        try:
            result = _engine(app).get_for_agent(
                request_id, actor.service_identity_id, datetime.now(UTC)
            )
        except DelegationError as exc:
            raise _delegation_http_error(exc) from exc
        return _response(result)

    @router.post(
        "/v1/external/delegation-requests/{request_id}/complete",
        response_model=DelegationRequestResponse,
    )
    def complete_delegation(request: Request, request_id: str) -> DelegationRequestResponse:
        actor = _service_actor(request)
        if actor.service_identity_id is None:
            raise HTTPException(status_code=401, detail="An external service API key is required.")
        try:
            result = _engine(app).complete(request_id, actor.service_identity_id, datetime.now(UTC))
        except DelegationError as exc:
            raise _delegation_http_error(exc) from exc
        _audit(
            app,
            "delegation_request_completed",
            actor_type="service",
            actor_id=actor.service_identity_id,
            metadata={"delegation_request_id": result.id},
        )
        return _response(result)

    return router


__all__ = ["build_delegation_router"]
