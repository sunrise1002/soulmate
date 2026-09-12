"""Deterministic policy engine for prediction-bound delegated actions."""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from soulmate_core.domain import (
    DecisionImpact,
    DecisionRepository,
    DelegationPolicy,
    DelegationPolicyRepository,
    DelegationRequest,
    DelegationRequestRepository,
    DelegationStatus,
    PersonalModelRepository,
)

DEFAULT_DELEGATION_TTL = timedelta(hours=24)
IMPACT_CONFIDENCE_FLOORS: dict[DecisionImpact, float] = {
    DecisionImpact.LOW: 0.90,
    DecisionImpact.MEDIUM: 0.95,
    DecisionImpact.HIGH: 1.0,
    DecisionImpact.SAFETY_CRITICAL: 1.0,
}


class DelegationError(Exception):
    """A delegation policy or lifecycle rule rejected an operation."""


class DelegationPolicyEngine:
    """Apply owner policies without executing external side effects."""

    def __init__(
        self,
        policies: DelegationPolicyRepository,
        requests: DelegationRequestRepository,
        decisions: DecisionRepository,
        models: PersonalModelRepository,
    ) -> None:
        self._policies = policies
        self._requests = requests
        self._decisions = decisions
        self._models = models

    def set_policy(
        self,
        *,
        profile_id: str,
        service_identity_id: str,
        action_type: str,
        impact: DecisionImpact,
        minimum_confidence: float,
        allow_automatic: bool,
        now: datetime,
    ) -> DelegationPolicy:
        normalized_action = action_type.strip()
        floor = IMPACT_CONFIDENCE_FLOORS[impact]
        if minimum_confidence < floor:
            raise DelegationError(
                f"The minimum confidence for {impact.value}-impact actions is {floor:.2f}."
            )
        existing = self._policies.get_for_action(profile_id, service_identity_id, normalized_action)
        try:
            policy = DelegationPolicy(
                id=existing.id if existing is not None else f"policy_{uuid4().hex}",
                profile_id=profile_id,
                service_identity_id=service_identity_id,
                action_type=normalized_action,
                impact=impact,
                minimum_confidence=minimum_confidence,
                allow_automatic=allow_automatic,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
            )
        except ValueError as exc:
            raise DelegationError(str(exc)) from exc
        return self._policies.upsert(policy)

    def request(
        self,
        *,
        profile_id: str,
        service_identity_id: str,
        decision_id: str,
        action_type: str,
        action_label: str,
        external_request_id: str,
        now: datetime,
    ) -> DelegationRequest:
        normalized_action = action_type.strip()
        normalized_label = action_label.strip()
        normalized_external_id = external_request_id.strip()
        existing = self._requests.get_by_external_request(
            service_identity_id, normalized_external_id
        )
        if existing is not None:
            if (
                existing.decision_id != decision_id
                or existing.action_type != normalized_action
                or existing.action_label != normalized_label
            ):
                raise DelegationError(
                    "The external request ID was already used for another action."
                )
            return self._refresh_expiry(existing, now)

        policy = self._policies.get_for_action(profile_id, service_identity_id, normalized_action)
        if policy is None:
            raise DelegationError("The owner has not approved this action type for the agent.")
        stored = self._decisions.get(decision_id)
        prediction = self._decisions.latest_prediction(decision_id)
        if stored is None or stored[0].profile_id != profile_id or prediction is None:
            raise DelegationError("A persisted decision prediction is required for delegation.")
        if prediction.profile_id != profile_id:
            raise DelegationError("The decision prediction belongs to another profile.")
        snapshot = self._models.latest_snapshot(profile_id)
        if snapshot is None or prediction.model_snapshot_version != snapshot.version:
            raise DelegationError("A fresh prediction from the current Personal Model is required.")

        status, reason = self._classify(policy, prediction.confidence)
        request = DelegationRequest(
            id=f"delegation_{uuid4().hex}",
            profile_id=profile_id,
            service_identity_id=service_identity_id,
            policy_id=policy.id,
            decision_id=decision_id,
            prediction_id=prediction.id,
            external_request_id=normalized_external_id,
            action_type=policy.action_type,
            action_label=normalized_label,
            impact=policy.impact,
            predicted_option_id=prediction.ranking[0].option_id,
            prediction_confidence=prediction.confidence,
            status=status,
            reason_code=reason,
            requested_at=now,
            expires_at=now + DEFAULT_DELEGATION_TTL,
        )
        self._requests.add(request)
        return request

    def get_for_agent(
        self, request_id: str, service_identity_id: str, now: datetime
    ) -> DelegationRequest:
        request = self._required_request(request_id)
        if request.service_identity_id != service_identity_id:
            raise DelegationError("Delegation request was not found.")
        return self._refresh_expiry(request, now)

    def list_for_owner(self, profile_id: str, now: datetime) -> tuple[DelegationRequest, ...]:
        return tuple(
            self._refresh_expiry(item, now) for item in self._requests.list_for_profile(profile_id)
        )

    def review(
        self,
        *,
        profile_id: str,
        request_id: str,
        approved: bool,
        now: datetime,
    ) -> DelegationRequest:
        request = self._required_owned_request(profile_id, request_id)
        request = self._refresh_expiry(request, now)
        reviewable = (
            (DelegationStatus.PENDING,)
            if approved
            else (DelegationStatus.PENDING, DelegationStatus.APPROVED)
        )
        if request.status not in reviewable:
            raise DelegationError(
                "Only pending requests can be approved; pending or approved "
                "requests can be rejected."
            )
        status = DelegationStatus.APPROVED if approved else DelegationStatus.REJECTED
        reason = "owner_approved" if approved else "owner_rejected"
        if not self._requests.transition(request.id, request.status, status, reason, now):
            raise DelegationError("Delegation request state changed before review.")
        return replace(request, status=status, reason_code=reason, reviewed_at=now)

    def complete(
        self, request_id: str, service_identity_id: str, now: datetime
    ) -> DelegationRequest:
        request = self.get_for_agent(request_id, service_identity_id, now)
        if request.status is not DelegationStatus.APPROVED:
            raise DelegationError("Only an approved, unexpired delegation can be completed.")
        if not self._requests.transition(
            request.id,
            DelegationStatus.APPROVED,
            DelegationStatus.COMPLETED,
            "agent_completed",
            now,
        ):
            raise DelegationError("Delegation request state changed before completion.")
        return replace(
            request,
            status=DelegationStatus.COMPLETED,
            reason_code="agent_completed",
            completed_at=now,
        )

    def remove_policy(self, profile_id: str, policy_id: str) -> None:
        if not self._policies.remove(profile_id, policy_id):
            raise DelegationError("Delegation policy was not found.")

    @staticmethod
    def _classify(policy: DelegationPolicy, confidence: float) -> tuple[DelegationStatus, str]:
        requires_confirmation = policy.impact in (
            DecisionImpact.HIGH,
            DecisionImpact.SAFETY_CRITICAL,
        )
        if requires_confirmation:
            return DelegationStatus.PENDING, "impact_requires_approval"
        if not policy.allow_automatic:
            return DelegationStatus.PENDING, "owner_approval_required"
        if confidence < policy.minimum_confidence:
            return DelegationStatus.PENDING, "confidence_below_threshold"
        return DelegationStatus.APPROVED, "automatic_threshold_met"

    def _refresh_expiry(self, request: DelegationRequest, now: datetime) -> DelegationRequest:
        if request.status not in (DelegationStatus.PENDING, DelegationStatus.APPROVED):
            return request
        if now < request.expires_at:
            return request
        if self._requests.transition(
            request.id,
            request.status,
            DelegationStatus.EXPIRED,
            "request_expired",
            now,
        ):
            return replace(
                request,
                status=DelegationStatus.EXPIRED,
                reason_code="request_expired",
                expired_at=now,
            )
        return self._required_request(request.id)

    def _required_request(self, request_id: str) -> DelegationRequest:
        request = self._requests.get(request_id)
        if request is None:
            raise DelegationError("Delegation request was not found.")
        return request

    def _required_owned_request(self, profile_id: str, request_id: str) -> DelegationRequest:
        request = self._required_request(request_id)
        if request.profile_id != profile_id:
            raise DelegationError("Delegation request was not found.")
        return request
