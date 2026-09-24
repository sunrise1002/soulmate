"""Deterministic Decision I/O classification without an LLM or network call.

The daemon calls these functions; an external adapter can only supply the inputs.
Fixed inputs plus ``POLICY_PROFILE_VERSION`` always produce the same result.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from soulmate_core.domain import (
    AcquisitionMethod,
    ConsentMode,
    DataClass,
    DecisionIoEventType,
    EventActorType,
    EventProvenance,
    EvidenceEligibility,
    OutcomeKind,
    RawRetentionPolicy,
    SourceProvenance,
)

POLICY_PROFILE_VERSION = "p13.1"
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1,)
MAX_EVENT_CONTENT_BYTES = 64 * 1024
MAX_EXTERNAL_ID_LENGTH = 200

UNSUPPORTED_RETENTION_POLICIES: tuple[RawRetentionPolicy, ...] = (
    RawRetentionPolicy.DELETE_AFTER_EXTRACTION,
)

EVENT_DATA_CLASSES: dict[DecisionIoEventType, DataClass] = {
    DecisionIoEventType.INTERACTION: DataClass.METADATA,
    DecisionIoEventType.DECISION_CANDIDATE: DataClass.DECISION,
    DecisionIoEventType.DECISION_RESOLUTION: DataClass.DECISION,
    DecisionIoEventType.AGENT_PROPOSAL: DataClass.DECISION,
    DecisionIoEventType.USER_OVERRIDE: DataClass.CORRECTION,
    DecisionIoEventType.ACTION: DataClass.METADATA,
    DecisionIoEventType.TECHNICAL_OUTCOME: DataClass.OUTCOME,
    DecisionIoEventType.USER_OUTCOME: DataClass.OUTCOME,
    DecisionIoEventType.CORRECTION: DataClass.CORRECTION,
    DecisionIoEventType.CONTEXT: DataClass.METADATA,
}

OWNER_AUTHORED_EVENT_TYPES: frozenset[DecisionIoEventType] = frozenset(
    {
        DecisionIoEventType.DECISION_RESOLUTION,
        DecisionIoEventType.USER_OVERRIDE,
        DecisionIoEventType.CORRECTION,
        DecisionIoEventType.USER_OUTCOME,
    }
)

IGNORED_EVENT_TYPES: frozenset[DecisionIoEventType] = frozenset(
    {DecisionIoEventType.TECHNICAL_OUTCOME}
)

OUTCOME_KINDS: dict[DecisionIoEventType, OutcomeKind] = {
    DecisionIoEventType.TECHNICAL_OUTCOME: OutcomeKind.TECHNICAL,
    DecisionIoEventType.USER_OUTCOME: OutcomeKind.USER_BEHAVIOR,
}


# Records the owner produced by using Soulmate directly on their own device.
OWNER_LOCAL_EVENT = EventProvenance(
    actor_type=EventActorType.OWNER, evidence_eligibility=EvidenceEligibility.ELIGIBLE
)


class DecisionIoError(Exception):
    """A Decision I/O validation or policy rule rejected an operation."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class EventClassification:
    """What the daemon decided about one reported event."""

    event_type: DecisionIoEventType
    actor_type: EventActorType
    eligibility: EvidenceEligibility
    data_class: DataClass
    policy_profile_version: str


def canonical_content(content: dict[str, Any]) -> str:
    """Serialize event content so identical input always fingerprints identically."""
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_fingerprint(content: dict[str, Any]) -> str:
    """Stable digest used to tell an identical retry from a conflicting reuse."""
    return hashlib.sha256(canonical_content(content).encode("utf-8")).hexdigest()


def validate_retention_policy(policy: RawRetentionPolicy) -> RawRetentionPolicy:
    """Reject retention modes the repository cannot honour yet."""
    if policy in UNSUPPORTED_RETENTION_POLICIES:
        raise DecisionIoError(
            "retention_unsupported",
            f"The '{policy.value}' retention policy is not supported yet.",
        )
    return policy


def retained_content(policy: RawRetentionPolicy, content: dict[str, Any]) -> dict[str, Any]:
    """Return only the event content a source's retention policy allows to be stored.

    The fingerprint is always computed over the reported content, so idempotency
    still distinguishes retries from conflicts when nothing is retained.
    """
    validate_retention_policy(policy)
    if policy is RawRetentionPolicy.METADATA_ONLY:
        return {}
    return content


def derive_eligibility(
    provenance: SourceProvenance,
    event_type: DecisionIoEventType,
    actor_type: EventActorType,
) -> EvidenceEligibility:
    """Classify whether a later extractor may consider this event.

    Only an owner-authored event from an explicitly consented source that declares
    the event's data class can ever become eligible. Everything else is contextual,
    and purely technical results are ignored for learning.
    """
    if event_type in IGNORED_EVENT_TYPES:
        return EvidenceEligibility.IGNORED
    if actor_type is not EventActorType.OWNER:
        return EvidenceEligibility.CONTEXTUAL_ONLY
    if provenance.consent_mode is ConsentMode.LEGACY_UNVERIFIED:
        return EvidenceEligibility.CONTEXTUAL_ONLY
    if provenance.acquisition_method is AcquisitionMethod.LEGACY_UNVERIFIED:
        return EvidenceEligibility.CONTEXTUAL_ONLY
    if EVENT_DATA_CLASSES[event_type] not in provenance.data_classes:
        return EvidenceEligibility.CONTEXTUAL_ONLY
    if event_type not in OWNER_AUTHORED_EVENT_TYPES:
        return EvidenceEligibility.CONTEXTUAL_ONLY
    return EvidenceEligibility.ELIGIBLE


def classify_event(
    *,
    provenance: SourceProvenance,
    event_type: DecisionIoEventType,
    reported_actor: EventActorType,
    schema_version: int,
    content: dict[str, Any],
    occurred_at: datetime,
    external_event_id: str,
) -> EventClassification:
    """Validate one reported event and assign the daemon's own classification."""
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise DecisionIoError(
            "schema_unsupported", f"Event schema version {schema_version} is not supported."
        )
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise DecisionIoError("timestamp_naive", "Event timestamps must be timezone-aware.")
    normalized_external_id = external_event_id.strip()
    if not normalized_external_id or len(normalized_external_id) > MAX_EXTERNAL_ID_LENGTH:
        raise DecisionIoError(
            "external_id_invalid",
            f"External event IDs must contain 1 to {MAX_EXTERNAL_ID_LENGTH} characters.",
        )
    if len(canonical_content(content).encode("utf-8")) > MAX_EVENT_CONTENT_BYTES:
        raise DecisionIoError(
            "content_too_large",
            f"Event content must stay under {MAX_EVENT_CONTENT_BYTES} bytes.",
        )
    if provenance.acquisition_method is not AcquisitionMethod.AGENT_PUSH:
        raise DecisionIoError(
            "source_not_ingestible", "The source is not approved for pushed events."
        )
    if not provenance.allows_actor(reported_actor):
        raise DecisionIoError(
            "actor_outside_source_scope",
            "The source is not approved to report events for this actor.",
        )
    data_class = EVENT_DATA_CLASSES[event_type]
    if data_class not in provenance.data_classes:
        raise DecisionIoError(
            "data_class_not_declared",
            f"The source does not declare the '{data_class.value}' data class.",
        )
    return EventClassification(
        event_type=event_type,
        actor_type=reported_actor,
        eligibility=derive_eligibility(provenance, event_type, reported_actor),
        data_class=data_class,
        policy_profile_version=POLICY_PROFILE_VERSION,
    )


def may_promote_resolution(classification: EventClassification) -> bool:
    """Only an owner-authored, eligible choice becomes a canonical resolution."""
    return (
        classification.event_type
        in (DecisionIoEventType.DECISION_RESOLUTION, DecisionIoEventType.USER_OVERRIDE)
        and classification.actor_type is EventActorType.OWNER
        and classification.eligibility is EvidenceEligibility.ELIGIBLE
    )


def outcome_kind_for(event_type: DecisionIoEventType) -> OutcomeKind:
    """Map an event type to the outcome semantics it may ever carry."""
    kind = OUTCOME_KINDS.get(event_type)
    if kind is None:
        raise DecisionIoError(
            "event_type_not_outcome", "The event type does not describe an outcome."
        )
    return kind


__all__ = [
    "MAX_EVENT_CONTENT_BYTES",
    "MAX_EXTERNAL_ID_LENGTH",
    "OWNER_LOCAL_EVENT",
    "POLICY_PROFILE_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "UNSUPPORTED_RETENTION_POLICIES",
    "DecisionIoError",
    "EventClassification",
    "canonical_content",
    "classify_event",
    "content_fingerprint",
    "derive_eligibility",
    "may_promote_resolution",
    "outcome_kind_for",
    "retained_content",
    "validate_retention_policy",
]
