"""Domain records shared by persistence ports and application services."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


def _require_utc_aware(*values: datetime | None) -> None:
    if any(
        value is not None and (value.tzinfo is None or value.utcoffset() is None)
        for value in values
    ):
        raise ValueError("Domain timestamps must be timezone-aware.")


class JobStatus(StrEnum):
    """Durable job lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvidenceTargetType(StrEnum):
    """Kinds of derived Personal Model state supported by evidence."""

    FACT = "fact"
    PREFERENCE = "preference"
    GOAL = "goal"
    CONSTRAINT = "constraint"


class TargetKeyAliasMethod(StrEnum):
    """How an alias between two target keys was proposed."""

    NORMALIZED = "normalized"
    SEMANTIC = "semantic"
    OWNER = "owner"


class TargetKeyAliasStatus(StrEnum):
    """Review state of an alias; only active aliases affect derived state."""

    ACTIVE = "active"
    SUGGESTED = "suggested"
    REJECTED = "rejected"


class MessageRole(StrEnum):
    """Conversation roles persisted by the provider-neutral kernel."""

    USER = "user"
    ASSISTANT = "assistant"


class DecisionStatus(StrEnum):
    """Lifecycle states for a prediction-only decision."""

    OPEN = "open"
    RESOLVED = "resolved"


class ActiveQuestionStatus(StrEnum):
    """Lifecycle states for an uncertainty-targeting question."""

    PENDING = "pending"
    ANSWERED = "answered"


class DecisionImpact(StrEnum):
    """Owner-assigned impact class for a delegated action type."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SAFETY_CRITICAL = "safety_critical"


class DelegationStatus(StrEnum):
    """Durable approval lifecycle for one external action request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Profile:
    id: str
    display_name: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    profile_id: str
    source_type: str
    name: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class RawEvent:
    """Immutable input envelope for learning inputs."""

    id: str
    profile_id: str
    source_id: str | None
    event_type: str
    content: dict[str, Any]
    created_at: datetime
    ingested_at: datetime
    sensitivity: str = "normal"

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.ingested_at)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    profile_id: str
    created_at: datetime
    updated_at: datetime
    source_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.updated_at)


@dataclass(frozen=True, slots=True)
class SourceDeletion:
    """Counts removed with one imported source and its provenance graph."""

    source_id: str
    raw_event_count: int
    conversation_count: int
    message_count: int
    evidence_count: int


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime
    provider_model: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.content:
            raise ValueError("Message content must not be empty.")


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    id: str
    profile_id: str
    domain: str
    question: str
    context: dict[str, object]
    status: DecisionStatus
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.domain.strip() or not self.question.strip():
            raise ValueError("Decision domain and question must not be empty.")


@dataclass(frozen=True, slots=True)
class DecisionOption:
    id: str
    decision_id: str
    label: str
    description: str
    features: dict[str, float]
    feature_confidence: float

    def __post_init__(self) -> None:
        if not self.label.strip() or not self.description.strip():
            raise ValueError("Decision option label and description must not be empty.")
        if not self.features:
            raise ValueError("Decision option features must not be empty.")
        if any(not key.strip() or not -1.0 <= value <= 1.0 for key, value in self.features.items()):
            raise ValueError("Decision option features must have keys and values between -1 and 1.")
        if not 0.0 <= self.feature_confidence <= 1.0:
            raise ValueError("Decision option feature confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class OptionProbability:
    option_id: str
    probability: float
    utility: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("Option probability must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class DecisionPrediction:
    id: str
    decision_id: str
    profile_id: str
    ranking: tuple[OptionProbability, ...]
    confidence: float
    important_factors: tuple[str, ...]
    uncertain_factors: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    similar_decision_ids: tuple[str, ...]
    model_snapshot_version: int
    algorithm_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.ranking or not self.algorithm_version:
            raise ValueError("Prediction ranking and algorithm version must not be empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Prediction confidence must be between 0 and 1.")
        if self.model_snapshot_version < 1:
            raise ValueError("Prediction must reference a persisted model snapshot.")


@dataclass(frozen=True, slots=True)
class DecisionResolution:
    id: str
    decision_id: str
    chosen_option_id: str
    source_event_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """Owner-reported wellbeing after a resolved decision."""

    id: str
    decision_id: str
    profile_id: str
    satisfaction: float
    regret: bool
    notes: str | None
    source_event_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not 0.0 <= self.satisfaction <= 1.0:
            raise ValueError("Outcome satisfaction must be between 0 and 1.")
        if self.notes is not None and not self.notes.strip():
            raise ValueError("Outcome notes must be omitted or contain text.")


@dataclass(frozen=True, slots=True)
class AdviceRankingItem:
    option_id: str
    recommendation_score: float
    behavioral_probability: float
    wellbeing_score: float | None
    goal_alignment: float | None

    def __post_init__(self) -> None:
        values = (self.recommendation_score, self.behavioral_probability)
        optional = (self.wellbeing_score, self.goal_alignment)
        if any(not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("Advice scores must be between 0 and 1.")
        if any(value is not None and not 0.0 <= value <= 1.0 for value in optional):
            raise ValueError("Optional advice scores must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class DecisionAdvice:
    """Normative recommendation kept separate from behavioral prediction."""

    id: str
    decision_id: str
    profile_id: str
    behavioral_prediction_id: str
    ranking: tuple[AdviceRankingItem, ...]
    confidence: float
    rationale: tuple[str, ...]
    supporting_outcome_ids: tuple[str, ...]
    model_snapshot_version: int
    algorithm_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.ranking or not self.algorithm_version:
            raise ValueError("Advice ranking and algorithm version must not be empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Advice confidence must be between 0 and 1.")
        if self.model_snapshot_version < 1:
            raise ValueError("Advice must reference a persisted model snapshot.")


@dataclass(frozen=True, slots=True)
class ActiveQuestion:
    """Deterministic pairwise question aimed at uncertain preferences."""

    id: str
    profile_id: str
    prompt: str
    preference_keys: tuple[str, ...]
    context: dict[str, object]
    option_a_label: str
    option_a_features: dict[str, float]
    option_b_label: str
    option_b_features: dict[str, float]
    information_gain_score: float
    model_snapshot_version: int
    algorithm_version: str
    status: ActiveQuestionStatus
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.prompt.strip() or not self.preference_keys:
            raise ValueError("Active question prompt and preference keys must not be empty.")
        if not self.option_a_label.strip() or not self.option_b_label.strip():
            raise ValueError("Active question option labels must not be empty.")
        if not 0.0 <= self.information_gain_score <= 1.0:
            raise ValueError("Information-gain score must be between 0 and 1.")
        if self.model_snapshot_version < 1 or not self.algorithm_version:
            raise ValueError("Active question must record model and algorithm versions.")


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    id: str
    question_id: str
    choice: str
    source_event_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if self.choice not in {"a", "b"}:
            raise ValueError("Question answer choice must be 'a' or 'b'.")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Immutable, provenance-bearing claim used to derive Personal Model state."""

    id: str
    profile_id: str
    target_type: EvidenceTargetType
    target_key: str
    value: object
    strength: float
    confidence: float
    context: dict[str, object]
    source_type: str
    source_event_id: str
    extractor_version: str
    created_at: datetime
    extractor_model: str | None = None
    source_message_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.target_key:
            raise ValueError("Evidence target_key must not be empty.")
        if not self.source_type or not self.source_event_id or not self.extractor_version:
            raise ValueError("Evidence provenance fields must not be empty.")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("Evidence strength must be between 0 and 1.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Evidence confidence must be between 0 and 1.")
        if self.target_type is EvidenceTargetType.PREFERENCE and (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not -1.0 <= float(self.value) <= 1.0
        ):
            raise ValueError("Preference evidence value must be numeric and between -1 and 1.")


@dataclass(frozen=True, slots=True)
class TargetKeyAlias:
    """Owner-owned mapping of one target key onto the canonical key it reinforces.

    Evidence is never rewritten: aggregation applies active aliases, so removing
    one and rebuilding restores the previous grouping. ``polarity`` is ``-1`` for
    opposite keys such as ``ui.theme.light`` against ``ui.theme.dark``.
    """

    profile_id: str
    target_type: EvidenceTargetType
    alias_key: str
    canonical_key: str
    polarity: int
    method: TargetKeyAliasMethod
    status: TargetKeyAliasStatus
    algorithm_version: str
    created_at: datetime
    updated_at: datetime
    similarity: float | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.updated_at)
        if not self.alias_key or not self.canonical_key:
            raise ValueError("Target key alias keys must not be empty.")
        if self.alias_key == self.canonical_key:
            raise ValueError("A target key alias must not point at itself.")
        if not self.algorithm_version:
            raise ValueError("Target key alias algorithm version must not be empty.")
        if self.polarity not in (1, -1):
            raise ValueError("Target key alias polarity must be 1 or -1.")
        if self.polarity == -1 and self.target_type is not EvidenceTargetType.PREFERENCE:
            raise ValueError("Only preference aliases can invert polarity.")
        if self.similarity is not None and not 0.0 <= self.similarity <= 1.0:
            raise ValueError("Target key alias similarity must be between 0 and 1.")
        if self.method is TargetKeyAliasMethod.SEMANTIC and self.similarity is None:
            raise ValueError("Semantic target key aliases must record a similarity.")


@dataclass(frozen=True, slots=True)
class Preference:
    key: str
    value: float
    uncertainty: float
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class Fact:
    key: str
    value: object
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class Goal:
    key: str
    value: object
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class Constraint:
    key: str
    value: object
    confidence: float
    context: dict[str, object]
    supporting_evidence_ids: tuple[str, ...]
    updated_at: datetime
    model_version: int

    def __post_init__(self) -> None:
        _require_utc_aware(self.updated_at)


@dataclass(frozen=True, slots=True)
class DerivedModel:
    """Deterministically aggregated model content before persistence versioning."""

    preferences: tuple[Preference, ...]
    facts: tuple[Fact, ...]
    goals: tuple[Goal, ...]
    constraints: tuple[Constraint, ...]


@dataclass(frozen=True, slots=True)
class UserModelSnapshot:
    profile_id: str
    version: int
    algorithm_version: str
    evidence_revision: int
    model: DerivedModel
    created_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    action: str
    actor_type: str
    created_at: datetime
    profile_id: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    job_type: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    locked_at: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.available_at, self.created_at, self.updated_at, self.locked_at)


@dataclass(frozen=True, slots=True)
class PairingToken:
    """One-time, short-lived secret that authorizes a single device enrollment."""

    id: str
    profile_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    device_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.expires_at, self.consumed_at)
        if not self.token_hash:
            raise ValueError("Pairing token hash must not be empty.")
        if self.expires_at <= self.created_at:
            raise ValueError("Pairing token must expire after it was created.")

    def is_usable_at(self, now: datetime) -> bool:
        return self.consumed_at is None and now < self.expires_at


@dataclass(frozen=True, slots=True)
class PairedDevice:
    """A revocable client credential held by another device of the same owner."""

    id: str
    profile_id: str
    name: str
    platform: str
    credential_hash: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.last_seen_at, self.revoked_at)
        if not self.name.strip():
            raise ValueError("Paired device name must not be empty.")
        if not self.credential_hash:
            raise ValueError("Paired device credential hash must not be empty.")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """A revocable, least-privilege identity for one external application."""

    id: str
    profile_id: str
    name: str
    description: str | None
    scopes: tuple[str, ...]
    created_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.revoked_at)
        if not self.name.strip():
            raise ValueError("Service identity name must not be empty.")
        if self.description is not None and not self.description.strip():
            raise ValueError("Service identity description must be omitted or contain text.")
        if not self.scopes or any(not scope.strip() for scope in self.scopes):
            raise ValueError("Service identity scopes must not be empty.")
        if tuple(sorted(set(self.scopes))) != self.scopes:
            raise ValueError("Service identity scopes must be unique and sorted.")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class ApiCredential:
    """A revocable API-key hash; usable secret material is never persisted."""

    id: str
    service_identity_id: str
    secret_hash: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.last_used_at, self.revoked_at)
        if not self.secret_hash:
            raise ValueError("API credential hash must not be empty.")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class DelegationPolicy:
    """Owner-approved boundary for one agent and action type."""

    id: str
    profile_id: str
    service_identity_id: str
    action_type: str
    impact: DecisionImpact
    minimum_confidence: float
    allow_automatic: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at, self.updated_at)
        if not self.action_type.strip():
            raise ValueError("Delegation action type must not be empty.")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("Delegation confidence threshold must be between 0 and 1.")
        if self.allow_automatic and self.impact in (
            DecisionImpact.HIGH,
            DecisionImpact.SAFETY_CRITICAL,
        ):
            raise ValueError(
                "High-impact and safety-critical actions always require owner approval."
            )


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """A prediction-bound authorization request from an external agent."""

    id: str
    profile_id: str
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
    status: DelegationStatus
    reason_code: str
    requested_at: datetime
    expires_at: datetime
    reviewed_at: datetime | None = None
    completed_at: datetime | None = None
    expired_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(
            self.requested_at,
            self.expires_at,
            self.reviewed_at,
            self.completed_at,
            self.expired_at,
        )
        if not self.external_request_id.strip() or not self.action_type.strip():
            raise ValueError("Delegation request identifiers must not be empty.")
        if not self.action_label.strip():
            raise ValueError("Delegation action label must not be empty.")
        if not 0.0 <= self.prediction_confidence <= 1.0:
            raise ValueError("Delegation prediction confidence must be between 0 and 1.")
        if self.expires_at <= self.requested_at:
            raise ValueError("Delegation request must expire after it was created.")
