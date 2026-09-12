"""Verify deterministic delegated-decision policy and approval rules."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from soulmate_core.delegation import DelegationError, DelegationPolicyEngine
from soulmate_core.domain import (
    DecisionEvent,
    DecisionImpact,
    DecisionOption,
    DecisionPrediction,
    DecisionRepository,
    DecisionStatus,
    DelegationPolicy,
    DelegationRequest,
    DelegationStatus,
    DerivedModel,
    OptionProbability,
    PersonalModelRepository,
    UserModelSnapshot,
)

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


class MemoryPolicies:
    def __init__(self) -> None:
        self.items: dict[str, DelegationPolicy] = {}

    def upsert(self, policy: DelegationPolicy) -> DelegationPolicy:
        existing = self.get_for_action(
            policy.profile_id, policy.service_identity_id, policy.action_type
        )
        if existing is not None and existing.id != policy.id:
            raise AssertionError("Policy IDs must remain stable during updates.")
        self.items[policy.id] = policy
        return policy

    def get(self, policy_id: str) -> DelegationPolicy | None:
        return self.items.get(policy_id)

    def get_for_action(
        self, profile_id: str, service_identity_id: str, action_type: str
    ) -> DelegationPolicy | None:
        return next(
            (
                item
                for item in self.items.values()
                if item.profile_id == profile_id
                and item.service_identity_id == service_identity_id
                and item.action_type == action_type
            ),
            None,
        )

    def list_for_profile(self, profile_id: str) -> tuple[DelegationPolicy, ...]:
        return tuple(item for item in self.items.values() if item.profile_id == profile_id)

    def remove(self, profile_id: str, policy_id: str) -> bool:
        item = self.items.get(policy_id)
        if item is None or item.profile_id != profile_id:
            return False
        del self.items[policy_id]
        return True


class MemoryRequests:
    def __init__(self) -> None:
        self.items: dict[str, DelegationRequest] = {}

    def add(self, request: DelegationRequest) -> None:
        self.items[request.id] = request

    def get(self, request_id: str) -> DelegationRequest | None:
        return self.items.get(request_id)

    def get_by_external_request(
        self, service_identity_id: str, external_request_id: str
    ) -> DelegationRequest | None:
        return next(
            (
                item
                for item in self.items.values()
                if item.service_identity_id == service_identity_id
                and item.external_request_id == external_request_id
            ),
            None,
        )

    def list_for_profile(self, profile_id: str) -> tuple[DelegationRequest, ...]:
        return tuple(item for item in self.items.values() if item.profile_id == profile_id)

    def transition(
        self,
        request_id: str,
        expected_status: DelegationStatus,
        status: DelegationStatus,
        reason_code: str,
        changed_at: datetime,
    ) -> bool:
        item = self.items.get(request_id)
        if item is None or item.status is not expected_status:
            return False
        reviewed_at = (
            changed_at
            if status in (DelegationStatus.APPROVED, DelegationStatus.REJECTED)
            else item.reviewed_at
        )
        completed_at = changed_at if status is DelegationStatus.COMPLETED else item.completed_at
        expired_at = changed_at if status is DelegationStatus.EXPIRED else item.expired_at
        self.items[request_id] = replace(
            item,
            status=status,
            reason_code=reason_code,
            reviewed_at=reviewed_at,
            completed_at=completed_at,
            expired_at=expired_at,
        )
        return True


class MemoryDecisions:
    def __init__(self, confidence: float) -> None:
        self.decision = DecisionEvent(
            id="decision_test",
            profile_id="profile_default",
            domain="calendar",
            question="Accept the meeting?",
            context={},
            status=DecisionStatus.OPEN,
            created_at=NOW,
        )
        self.options = (
            DecisionOption("accept", self.decision.id, "Accept", "Accept", {"fit": 1.0}, 1.0),
            DecisionOption("decline", self.decision.id, "Decline", "Decline", {"fit": -1.0}, 1.0),
        )
        self.prediction = DecisionPrediction(
            id="prediction_test",
            decision_id=self.decision.id,
            profile_id=self.decision.profile_id,
            ranking=(
                OptionProbability("accept", 0.96, 1.0),
                OptionProbability("decline", 0.04, -1.0),
            ),
            confidence=confidence,
            important_factors=("fit",),
            uncertain_factors=(),
            supporting_evidence_ids=(),
            similar_decision_ids=(),
            model_snapshot_version=1,
            algorithm_version="synthetic-v1",
            created_at=NOW,
        )

    def get(self, decision_id: str) -> tuple[DecisionEvent, tuple[DecisionOption, ...]] | None:
        return (self.decision, self.options) if decision_id == self.decision.id else None

    def latest_prediction(self, decision_id: str) -> DecisionPrediction | None:
        return self.prediction if decision_id == self.decision.id else None


class MemoryModels:
    def __init__(self, version: int = 1) -> None:
        self.snapshot = UserModelSnapshot(
            profile_id="profile_default",
            version=version,
            algorithm_version="synthetic-v1",
            evidence_revision=1,
            model=DerivedModel(preferences=(), facts=(), goals=(), constraints=()),
            created_at=NOW,
        )

    def latest_snapshot(self, profile_id: str) -> UserModelSnapshot | None:
        return self.snapshot if profile_id == self.snapshot.profile_id else None


def _engine(confidence: float = 0.96, current_model_version: int = 1) -> DelegationPolicyEngine:
    return DelegationPolicyEngine(
        MemoryPolicies(),
        MemoryRequests(),
        cast(DecisionRepository, MemoryDecisions(confidence)),
        cast(PersonalModelRepository, MemoryModels(current_model_version)),
    )


def _policy(
    engine: DelegationPolicyEngine,
    impact: DecisionImpact = DecisionImpact.LOW,
    confidence: float = 0.90,
    automatic: bool = True,
) -> DelegationPolicy:
    return engine.set_policy(
        profile_id="profile_default",
        service_identity_id="service_calendar",
        action_type="calendar.invitation.respond",
        impact=impact,
        minimum_confidence=confidence,
        allow_automatic=automatic,
        now=NOW,
    )


def _request(engine: DelegationPolicyEngine) -> DelegationRequest:
    return engine.request(
        profile_id="profile_default",
        service_identity_id="service_calendar",
        decision_id="decision_test",
        action_type="calendar.invitation.respond",
        action_label="Respond to synthetic meeting invitation",
        external_request_id="calendar-event-1",
        now=NOW,
    )


def test_low_impact_action_is_automatic_only_above_the_confidence_floor() -> None:
    automatic = _engine(0.96)
    _policy(automatic)
    approved = _request(automatic)
    assert approved.status is DelegationStatus.APPROVED
    assert approved.reason_code == "automatic_threshold_met"

    uncertain = _engine(0.89)
    _policy(uncertain)
    pending = _request(uncertain)
    assert pending.status is DelegationStatus.PENDING
    assert pending.reason_code == "confidence_below_threshold"


@pytest.mark.parametrize("impact", (DecisionImpact.HIGH, DecisionImpact.SAFETY_CRITICAL))
def test_high_impact_actions_always_require_an_owner_review(
    impact: DecisionImpact,
) -> None:
    engine = _engine(1.0)
    with pytest.raises(DelegationError, match="minimum confidence"):
        _policy(engine, DecisionImpact.MEDIUM, confidence=0.94)
    with pytest.raises(DelegationError, match="always require owner approval"):
        _policy(engine, impact, confidence=1.0, automatic=True)

    _policy(engine, impact, confidence=1.0, automatic=False)
    pending = _request(engine)
    assert pending.reason_code == "impact_requires_approval"
    approved = engine.review(
        profile_id="profile_default",
        request_id=pending.id,
        approved=True,
        now=NOW + timedelta(minutes=1),
    )
    completed = engine.complete(approved.id, "service_calendar", NOW + timedelta(minutes=2))
    assert completed.status is DelegationStatus.COMPLETED
    assert completed.reviewed_at == NOW + timedelta(minutes=1)
    assert completed.completed_at == NOW + timedelta(minutes=2)
    with pytest.raises(DelegationError, match="approved, unexpired"):
        engine.complete(completed.id, "service_calendar", NOW + timedelta(minutes=3))


def test_requests_are_idempotent_agent_isolated_and_expire() -> None:
    engine = _engine()
    _policy(engine)
    first = _request(engine)
    assert _request(engine).id == first.id
    with pytest.raises(DelegationError, match="already used"):
        engine.request(
            profile_id="profile_default",
            service_identity_id="service_calendar",
            decision_id="decision_test",
            action_type="calendar.invitation.respond",
            action_label="Different action",
            external_request_id="calendar-event-1",
            now=NOW,
        )
    with pytest.raises(DelegationError, match="not found"):
        engine.get_for_agent(first.id, "service_other", NOW)

    expired = engine.get_for_agent(first.id, "service_calendar", NOW + timedelta(hours=25))
    assert expired.status is DelegationStatus.EXPIRED
    assert expired.expired_at == NOW + timedelta(hours=25)
    assert expired.completed_at is None
    with pytest.raises(DelegationError, match="approved, unexpired"):
        engine.complete(first.id, "service_calendar", NOW + timedelta(hours=25))


def test_stale_predictions_are_never_eligible_for_delegation() -> None:
    engine = _engine(current_model_version=2)
    _policy(engine)

    with pytest.raises(DelegationError, match="fresh prediction"):
        _request(engine)


def test_owner_can_reject_a_pending_request() -> None:
    engine = _engine()
    _policy(engine, automatic=False)
    pending = _request(engine)

    rejected = engine.review(
        profile_id="profile_default",
        request_id=pending.id,
        approved=False,
        now=NOW + timedelta(minutes=1),
    )

    assert rejected.status is DelegationStatus.REJECTED
    assert rejected.reason_code == "owner_rejected"


def test_owner_can_revoke_an_automatic_approval_before_completion() -> None:
    engine = _engine()
    _policy(engine)
    automatic = _request(engine)

    rejected = engine.review(
        profile_id="profile_default",
        request_id=automatic.id,
        approved=False,
        now=NOW + timedelta(minutes=1),
    )

    assert rejected.status is DelegationStatus.REJECTED
    with pytest.raises(DelegationError, match="approved, unexpired"):
        engine.complete(rejected.id, "service_calendar", NOW + timedelta(minutes=2))
