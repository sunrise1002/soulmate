"""Decision I/O provenance vocabulary and externally observed lifecycle records.

The daemon, never an external adapter, assigns the classifications in this module.
See ADR-014.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AcquisitionMethod(StrEnum):
    """How a source obtains the records it reports."""

    OWNER_INPUT = "owner_input"
    OWNER_IMPORT = "owner_import"
    CONNECTOR_PULL = "connector_pull"
    AGENT_PUSH = "agent_push"
    LEGACY_UNVERIFIED = "legacy_unverified"


class ConsentMode(StrEnum):
    """How the owner agreed to the acquisition."""

    OWNER_EXPLICIT = "owner_explicit"
    OWNER_IMPLICIT = "owner_implicit"
    LEGACY_UNVERIFIED = "legacy_unverified"


class DataClass(StrEnum):
    """Categories of content a source is allowed to report."""

    METADATA = "metadata"
    DECISION = "decision"
    CORRECTION = "correction"
    OUTCOME = "outcome"
    PROMPT = "prompt"
    RESPONSE = "response"
    FILE_CONTENT = "file_content"
    DIFF = "diff"


class AuthorScope(StrEnum):
    """Which authors a source may report events for."""

    OWNER_ONLY = "owner_only"
    AGENT_ONLY = "agent_only"
    MIXED = "mixed"


class RawRetentionPolicy(StrEnum):
    """How long and how much raw content a source may retain."""

    METADATA_ONLY = "metadata_only"
    STRUCTURED_ONLY = "structured_only"
    FULL_CONTENT = "full_content"
    DELETE_AFTER_EXTRACTION = "delete_after_extraction"


class EventActorType(StrEnum):
    """Who an adapter reports as the author of an event."""

    OWNER = "owner"
    AGENT = "agent"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class EvidenceEligibility(StrEnum):
    """Whether a later validated extractor may consider an event."""

    ELIGIBLE = "eligible"
    CONTEXTUAL_ONLY = "contextual_only"
    IGNORED = "ignored"


class DecisionIoEventType(StrEnum):
    """Provider-neutral taxonomy for externally ingested events."""

    INTERACTION = "interaction"
    DECISION_CANDIDATE = "decision_candidate"
    DECISION_RESOLUTION = "decision_resolution"
    AGENT_PROPOSAL = "agent_proposal"
    USER_OVERRIDE = "user_override"
    ACTION = "action"
    TECHNICAL_OUTCOME = "technical_outcome"
    USER_OUTCOME = "user_outcome"
    CORRECTION = "correction"
    CONTEXT = "context"


class DecisionOrigin(StrEnum):
    """Which surface created a decision record."""

    OWNER_APP = "owner_app"
    EXTERNAL_SERVICE = "external_service"
    CONNECTOR = "connector"
    IMPORT = "import"
    LEGACY = "legacy"


class DecisionPurpose(StrEnum):
    """Why a decision record exists."""

    OWNER_INTERACTIVE = "owner_interactive"
    AGENT_CONSULTATION = "agent_consultation"
    OBSERVED = "observed"
    SHADOW = "shadow"


class ObservationStatus(StrEnum):
    """Lifecycle of a reported, not yet canonical, observation."""

    UNMATCHED = "unmatched"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class OutcomeKind(StrEnum):
    """Which kind of result an outcome observation describes."""

    TECHNICAL = "technical"
    USER_BEHAVIOR = "user_behavior"
    OWNER_REPORTED = "owner_reported"


class TechnicalOutcomeStatus(StrEnum):
    """Result of a technical action; never owner satisfaction."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class OutcomeAttribution(StrEnum):
    """Whether a stored owner outcome can be proven to come from the owner."""

    OWNER_CONFIRMED = "owner_confirmed"
    LEGACY_UNVERIFIED = "legacy_unverified"


class UserDisposition(StrEnum):
    """What the owner did with an agent's proposal."""

    ACCEPTED = "accepted"
    MODIFIED = "modified"
    REPLACED = "replaced"
    REVERTED = "reverted"
    UNKNOWN = "unknown"


def _require_utc_aware(*values: datetime | None) -> None:
    if any(
        value is not None and (value.tzinfo is None or value.utcoffset() is None)
        for value in values
    ):
        raise ValueError("Domain timestamps must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Versioned acquisition and consent metadata for one source."""

    provider: str | None = None
    acquisition_method: AcquisitionMethod = AcquisitionMethod.LEGACY_UNVERIFIED
    consent_mode: ConsentMode = ConsentMode.LEGACY_UNVERIFIED
    consent_at: datetime | None = None
    data_classes: tuple[DataClass, ...] = (DataClass.METADATA,)
    author_scope: AuthorScope = AuthorScope.MIXED
    raw_retention_policy: RawRetentionPolicy = RawRetentionPolicy.METADATA_ONLY
    adapter_version: str | None = None
    parser_version: str | None = None
    policy_profile_version: str = "legacy"
    service_identity_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.consent_at)
        if not self.data_classes:
            raise ValueError("A source must declare at least one data class.")
        if len(set(self.data_classes)) != len(self.data_classes):
            raise ValueError("Source data classes must not repeat.")
        if not self.policy_profile_version.strip():
            raise ValueError("A source must record its policy profile version.")
        if self.consent_mode is ConsentMode.OWNER_EXPLICIT and self.consent_at is None:
            raise ValueError("Explicit consent must record when it was granted.")
        if (
            self.acquisition_method is AcquisitionMethod.AGENT_PUSH
            and self.service_identity_id is None
        ):
            raise ValueError("A pushed source must name the service identity allowed to write it.")

    def allows_actor(self, actor_type: EventActorType) -> bool:
        """Whether the declared author scope covers one reported actor."""
        if self.author_scope is AuthorScope.MIXED:
            return True
        if self.author_scope is AuthorScope.OWNER_ONLY:
            return actor_type is EventActorType.OWNER
        return actor_type is not EventActorType.OWNER


@dataclass(frozen=True, slots=True)
class EventProvenance:
    """Normalized Decision I/O envelope fields attached to one raw event."""

    schema_version: int = 1
    external_event_id: str | None = None
    actor_type: EventActorType = EventActorType.UNKNOWN
    evidence_eligibility: EvidenceEligibility = EvidenceEligibility.CONTEXTUAL_ONLY
    correlation_id: str | None = None
    causation_event_id: str | None = None
    content_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("Event schema version must be positive.")
        if self.external_event_id is not None and not self.external_event_id.strip():
            raise ValueError("External event IDs must be omitted or contain text.")
        if self.causation_event_id is not None and self.correlation_id is None:
            raise ValueError("A caused event must carry the correlation it belongs to.")


@dataclass(frozen=True, slots=True)
class ResolutionObservation:
    """A reported choice that is not yet a canonical decision resolution."""

    id: str
    profile_id: str
    source_id: str
    source_event_id: str
    actor_type: EventActorType
    status: ObservationStatus
    disposition: UserDisposition
    created_at: datetime
    decision_id: str | None = None
    external_decision_id: str | None = None
    chosen_option_id: str | None = None
    external_option_id: str | None = None
    correlation_confidence: float | None = None
    confirmed_at: datetime | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.confirmed_at)
        if (
            self.correlation_confidence is not None
            and not 0.0 <= self.correlation_confidence <= 1.0
        ):
            raise ValueError("Correlation confidence must be between 0 and 1.")
        if self.decision_id is None and self.external_decision_id is None:
            raise ValueError("A resolution observation must reference a decision identifier.")
        if self.status is ObservationStatus.UNMATCHED and self.decision_id is not None:
            raise ValueError("A matched observation must not keep the unmatched status.")
        if (self.status is ObservationStatus.CONFIRMED) != (self.confirmed_at is not None):
            raise ValueError("Confirmation status and confirmation time must agree.")
        if self.status is ObservationStatus.CONFIRMED and self.decision_id is None:
            raise ValueError("A confirmed observation must reference a stored decision.")


@dataclass(frozen=True, slots=True)
class OutcomeObservation:
    """A reported result; only an owner confirmation can become wellbeing."""

    id: str
    profile_id: str
    source_id: str
    source_event_id: str
    kind: OutcomeKind
    actor_type: EventActorType
    status: ObservationStatus
    created_at: datetime
    decision_id: str | None = None
    external_decision_id: str | None = None
    technical_status: TechnicalOutcomeStatus | None = None
    disposition: UserDisposition | None = None
    satisfaction: float | None = None
    regret: bool | None = None
    confirmed_at: datetime | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.confirmed_at)
        if self.decision_id is None and self.external_decision_id is None:
            raise ValueError("An outcome observation must reference a decision identifier.")
        if self.status is ObservationStatus.UNMATCHED and self.decision_id is not None:
            raise ValueError("A matched observation must not keep the unmatched status.")
        if (self.status is ObservationStatus.CONFIRMED) != (self.confirmed_at is not None):
            raise ValueError("Confirmation status and confirmation time must agree.")
        if self.status is ObservationStatus.CONFIRMED and self.decision_id is None:
            raise ValueError("A confirmed observation must reference a stored decision.")
        if self.satisfaction is not None and not 0.0 <= self.satisfaction <= 1.0:
            raise ValueError("Observed satisfaction must be between 0 and 1.")
        if self.kind is OutcomeKind.TECHNICAL and self.technical_status is None:
            raise ValueError("A technical outcome observation must record its technical status.")
        if self.kind is not OutcomeKind.TECHNICAL and self.technical_status is not None:
            raise ValueError("Only technical outcome observations carry a technical status.")
        if self.kind is OutcomeKind.USER_BEHAVIOR and self.disposition is None:
            raise ValueError("A user-behavior observation must record the owner's disposition.")
        if self.kind is not OutcomeKind.USER_BEHAVIOR and self.disposition is not None:
            raise ValueError("Only user-behavior observations carry a disposition.")
        if self.kind is not OutcomeKind.OWNER_REPORTED and (
            self.satisfaction is not None or self.regret is not None
        ):
            raise ValueError("Satisfaction and regret belong to owner-reported outcomes only.")
        if self.kind is OutcomeKind.OWNER_REPORTED and (
            self.satisfaction is None or self.regret is None
        ):
            raise ValueError("An owner-reported observation must report satisfaction and regret.")


__all__ = [
    "AcquisitionMethod",
    "AuthorScope",
    "ConsentMode",
    "DataClass",
    "DecisionIoEventType",
    "DecisionOrigin",
    "DecisionPurpose",
    "EventActorType",
    "EventProvenance",
    "EvidenceEligibility",
    "ObservationStatus",
    "OutcomeAttribution",
    "OutcomeKind",
    "OutcomeObservation",
    "RawRetentionPolicy",
    "ResolutionObservation",
    "SourceProvenance",
    "TechnicalOutcomeStatus",
    "UserDisposition",
]
