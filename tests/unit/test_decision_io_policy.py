"""Deterministic Decision I/O classification rules (ADR-014)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from soulmate_core.decision_io import (
    MAX_EVENT_CONTENT_BYTES,
    MAX_EXTERNAL_ID_LENGTH,
    POLICY_PROFILE_VERSION,
    DecisionIoError,
    EventClassification,
    canonical_content,
    classify_event,
    content_fingerprint,
    derive_eligibility,
    may_promote_resolution,
    outcome_kind_for,
    retained_content,
    validate_retention_policy,
)
from soulmate_core.domain import (
    AcquisitionMethod,
    AuthorScope,
    ConsentMode,
    DataClass,
    DecisionIoEventType,
    EventActorType,
    EvidenceEligibility,
    OutcomeKind,
    RawRetentionPolicy,
    SourceProvenance,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def agent_source(
    *,
    author_scope: AuthorScope = AuthorScope.MIXED,
    consent_mode: ConsentMode = ConsentMode.OWNER_EXPLICIT,
    acquisition_method: AcquisitionMethod = AcquisitionMethod.AGENT_PUSH,
    data_classes: tuple[DataClass, ...] = (
        DataClass.METADATA,
        DataClass.DECISION,
        DataClass.CORRECTION,
        DataClass.OUTCOME,
    ),
) -> SourceProvenance:
    return SourceProvenance(
        provider="test_adapter",
        acquisition_method=acquisition_method,
        consent_mode=consent_mode,
        consent_at=None if consent_mode is not ConsentMode.OWNER_EXPLICIT else NOW,
        data_classes=data_classes,
        author_scope=author_scope,
        raw_retention_policy=RawRetentionPolicy.STRUCTURED_ONLY,
        adapter_version="1.0.0",
        parser_version="1.0.0",
        policy_profile_version=POLICY_PROFILE_VERSION,
        service_identity_id=(
            None if acquisition_method is not AcquisitionMethod.AGENT_PUSH else "service_1"
        ),
    )


def classify(
    *,
    provenance: SourceProvenance | None = None,
    event_type: DecisionIoEventType = DecisionIoEventType.DECISION_RESOLUTION,
    reported_actor: EventActorType = EventActorType.OWNER,
    schema_version: int = 1,
    content: dict[str, Any] | None = None,
    occurred_at: datetime = NOW,
    external_event_id: str = "event-1",
) -> EventClassification:
    return classify_event(
        provenance=agent_source() if provenance is None else provenance,
        event_type=event_type,
        reported_actor=reported_actor,
        schema_version=schema_version,
        content={"decision": "external_1"} if content is None else content,
        occurred_at=occurred_at,
        external_event_id=external_event_id,
    )


def test_owner_choice_from_a_consented_source_is_eligible() -> None:
    # Given: an owner-approved push source that declares decision content
    # When: the owner's own explicit choice arrives
    classification = classify()
    # Then: the daemon marks it eligible for later extraction and promotion
    assert classification.eligibility is EvidenceEligibility.ELIGIBLE
    assert classification.policy_profile_version == POLICY_PROFILE_VERSION
    assert may_promote_resolution(classification)


@pytest.mark.parametrize(
    "actor",
    [
        EventActorType.AGENT,
        EventActorType.ASSISTANT,
        EventActorType.SYSTEM,
        EventActorType.THIRD_PARTY,
        EventActorType.UNKNOWN,
    ],
)
def test_non_owner_content_can_never_be_eligible(actor: EventActorType) -> None:
    # Given: a fully consented source
    # When: any non-owner actor reports a choice
    classification = classify(reported_actor=actor)
    # Then: the event is contextual only and may not be promoted
    assert classification.eligibility is EvidenceEligibility.CONTEXTUAL_ONLY
    assert not may_promote_resolution(classification)


def test_technical_results_are_ignored_for_learning() -> None:
    # Given: an owner-approved source
    # When: a technical outcome arrives, even reported as owner-authored
    classification = classify(
        event_type=DecisionIoEventType.TECHNICAL_OUTCOME, reported_actor=EventActorType.OWNER
    )
    # Then: technical success never feeds the Personal Model
    assert classification.eligibility is EvidenceEligibility.IGNORED
    assert outcome_kind_for(DecisionIoEventType.TECHNICAL_OUTCOME) is OutcomeKind.TECHNICAL


def test_user_outcome_is_behavioural_not_wellbeing() -> None:
    # Given/When: a user outcome event type is mapped to outcome semantics
    # Then: it is behavioural, so satisfaction and regret stay out of reach
    assert outcome_kind_for(DecisionIoEventType.USER_OUTCOME) is OutcomeKind.USER_BEHAVIOR


def test_outcome_kind_rejects_non_outcome_events() -> None:
    # Given: an interaction event
    # When: outcome semantics are requested
    with pytest.raises(DecisionIoError) as error:
        outcome_kind_for(DecisionIoEventType.INTERACTION)
    # Then: the mapping fails with a stable reason code
    assert error.value.reason_code == "event_type_not_outcome"


def test_legacy_consent_and_acquisition_never_produce_eligibility() -> None:
    # Given: a source whose consent or acquisition could not be proven
    legacy_consent = agent_source(consent_mode=ConsentMode.LEGACY_UNVERIFIED)
    legacy_acquisition = agent_source(acquisition_method=AcquisitionMethod.LEGACY_UNVERIFIED)
    # When: an owner-authored choice is classified against each
    # Then: neither can ever be eligible
    for provenance in (legacy_consent, legacy_acquisition):
        assert (
            derive_eligibility(
                provenance, DecisionIoEventType.DECISION_RESOLUTION, EventActorType.OWNER
            )
            is EvidenceEligibility.CONTEXTUAL_ONLY
        )


def test_undeclared_data_class_is_rejected_before_persistence() -> None:
    # Given: a source that declares metadata only
    provenance = agent_source(data_classes=(DataClass.METADATA,))
    # When: a decision-class event arrives
    with pytest.raises(DecisionIoError) as error:
        classify(provenance=provenance)
    # Then: the consent boundary rejects it
    assert error.value.reason_code == "data_class_not_declared"


def test_actor_outside_the_declared_author_scope_is_rejected() -> None:
    # Given: an owner-only source
    provenance = agent_source(author_scope=AuthorScope.OWNER_ONLY)
    # When: the adapter reports an agent as the author
    with pytest.raises(DecisionIoError) as error:
        classify(provenance=provenance, reported_actor=EventActorType.AGENT)
    # Then: the event is rejected before persistence
    assert error.value.reason_code == "actor_outside_source_scope"


def test_agent_only_source_cannot_report_the_owner() -> None:
    # Given: an agent-only source
    provenance = agent_source(author_scope=AuthorScope.AGENT_ONLY)
    # When: the adapter claims the owner authored the event
    with pytest.raises(DecisionIoError) as error:
        classify(provenance=provenance, reported_actor=EventActorType.OWNER)
    # Then: impersonating the owner is refused
    assert error.value.reason_code == "actor_outside_source_scope"


def test_pull_connector_sources_cannot_receive_pushed_events() -> None:
    # Given: a pull connector source
    provenance = agent_source(acquisition_method=AcquisitionMethod.CONNECTOR_PULL)
    # When: an event is pushed for it
    with pytest.raises(DecisionIoError) as error:
        classify(provenance=provenance)
    # Then: the push boundary rejects the source
    assert error.value.reason_code == "source_not_ingestible"


def test_unsupported_schema_version_is_rejected() -> None:
    # Given/When: an event declares a schema version the daemon does not implement
    with pytest.raises(DecisionIoError) as error:
        classify(schema_version=2)
    # Then: the request fails without partial state
    assert error.value.reason_code == "schema_unsupported"


def test_zero_schema_version_is_rejected() -> None:
    # Given/When: the boundary value below the first supported version arrives
    with pytest.raises(DecisionIoError) as error:
        classify(schema_version=0)
    # Then: it is refused like any other unsupported version
    assert error.value.reason_code == "schema_unsupported"


def test_naive_timestamps_are_rejected() -> None:
    # Given/When: an event carries a timestamp without a UTC offset
    with pytest.raises(DecisionIoError) as error:
        classify(occurred_at=datetime(2026, 9, 23, 12, 0))
    # Then: the request is rejected
    assert error.value.reason_code == "timestamp_naive"


@pytest.mark.parametrize("external_id", ["", "   ", "x" * (MAX_EXTERNAL_ID_LENGTH + 1)])
def test_invalid_external_event_ids_are_rejected(external_id: str) -> None:
    # Given/When: an empty, blank, or oversized external event ID arrives
    with pytest.raises(DecisionIoError) as error:
        classify(external_event_id=external_id)
    # Then: the envelope is refused
    assert error.value.reason_code == "external_id_invalid"


def test_external_event_id_at_the_maximum_length_is_accepted() -> None:
    # Given/When: the longest permitted external ID arrives
    classification = classify(external_event_id="x" * MAX_EXTERNAL_ID_LENGTH)
    # Then: the boundary value is accepted
    assert classification.actor_type is EventActorType.OWNER


def test_oversized_content_is_rejected_and_the_limit_itself_is_accepted() -> None:
    # Given: content that is exactly at, and just over, the payload limit
    filler = "a" * (MAX_EVENT_CONTENT_BYTES - len(canonical_content({"note": ""})))
    # When: both payloads are classified
    accepted = classify(content={"note": filler})
    with pytest.raises(DecisionIoError) as error:
        classify(content={"note": filler + "a"})
    # Then: only the oversized payload is refused
    assert accepted.eligibility is EvidenceEligibility.ELIGIBLE
    assert error.value.reason_code == "content_too_large"


def test_fingerprints_ignore_key_order_and_follow_content() -> None:
    # Given: the same content written in a different key order, and a changed value
    # When: all three payloads are fingerprinted
    first = content_fingerprint({"a": 1, "b": {"c": 2, "d": 3}})
    reordered = content_fingerprint({"b": {"d": 3, "c": 2}, "a": 1})
    changed = content_fingerprint({"a": 1, "b": {"c": 2, "d": 4}})
    # Then: identical retries match and conflicting content does not
    assert first == reordered
    assert first != changed


def test_empty_content_fingerprints_deterministically() -> None:
    # Given/When: the empty payload boundary is fingerprinted twice
    # Then: it is stable rather than rejected
    assert content_fingerprint({}) == content_fingerprint({})


def test_delete_after_extraction_retention_is_rejected() -> None:
    # Given/When: a source asks for retention the repository cannot honour
    with pytest.raises(DecisionIoError) as error:
        validate_retention_policy(RawRetentionPolicy.DELETE_AFTER_EXTRACTION)
    # Then: it is refused rather than silently ignored
    assert error.value.reason_code == "retention_unsupported"


@pytest.mark.parametrize(
    "policy",
    [
        RawRetentionPolicy.METADATA_ONLY,
        RawRetentionPolicy.STRUCTURED_ONLY,
        RawRetentionPolicy.FULL_CONTENT,
    ],
)
def test_supported_retention_policies_pass_through(policy: RawRetentionPolicy) -> None:
    # Given/When/Then: every implemented retention mode is accepted unchanged
    assert validate_retention_policy(policy) is policy


def test_classification_is_deterministic_for_fixed_inputs() -> None:
    # Given: identical inputs classified twice
    # When/Then: the daemon returns the same decision without an LLM
    assert classify() == classify()


def test_metadata_only_retention_stores_no_event_content() -> None:
    # Given: reported content under a metadata-only source
    content = {"prompt": "synthetic prompt", "tool": "search"}
    # When: the retained content is derived
    retained = retained_content(RawRetentionPolicy.METADATA_ONLY, content)
    # Then: nothing from the payload is kept
    assert retained == {}


@pytest.mark.parametrize(
    "policy", [RawRetentionPolicy.STRUCTURED_ONLY, RawRetentionPolicy.FULL_CONTENT]
)
def test_content_retaining_policies_keep_the_reported_content(
    policy: RawRetentionPolicy,
) -> None:
    # Given/When: a policy that allows structured content keeps the payload
    # Then: the stored content equals what was reported
    assert retained_content(policy, {"decision": "external_1"}) == {"decision": "external_1"}


def test_retention_rejects_unsupported_policies_before_storing() -> None:
    # Given/When: content is filtered through an unsupported policy
    with pytest.raises(DecisionIoError) as error:
        retained_content(RawRetentionPolicy.DELETE_AFTER_EXTRACTION, {})
    # Then: the unsupported mode is refused
    assert error.value.reason_code == "retention_unsupported"
