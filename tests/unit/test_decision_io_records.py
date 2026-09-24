"""Invariants of the Decision I/O provenance and observation records (ADR-014)."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from soulmate_core.decision_io import IngestionWrite
from soulmate_core.domain import (
    AcquisitionMethod,
    AuthorScope,
    ConsentMode,
    DataClass,
    DecisionEvent,
    DecisionOrigin,
    DecisionPurpose,
    DecisionResolution,
    DecisionStatus,
    EventActorType,
    EventProvenance,
    Evidence,
    EvidenceEligibility,
    EvidenceTargetType,
    ObservationStatus,
    OutcomeKind,
    OutcomeObservation,
    RawEvent,
    RawRetentionPolicy,
    ResolutionObservation,
    Source,
    SourceProvenance,
    TechnicalOutcomeStatus,
    UserDisposition,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def resolution_observation(**overrides: object) -> ResolutionObservation:
    arguments: dict[str, object] = {
        "id": "resolution_observation_1",
        "profile_id": "profile_1",
        "source_id": "source_1",
        "source_event_id": "event_1",
        "actor_type": EventActorType.OWNER,
        "status": ObservationStatus.UNMATCHED,
        "disposition": UserDisposition.ACCEPTED,
        "created_at": NOW,
        "external_decision_id": "external_decision_1",
    }
    arguments.update(overrides)
    return ResolutionObservation(**arguments)  # type: ignore[arg-type]


def outcome_observation(**overrides: object) -> OutcomeObservation:
    arguments: dict[str, object] = {
        "id": "outcome_observation_1",
        "profile_id": "profile_1",
        "source_id": "source_1",
        "source_event_id": "event_1",
        "kind": OutcomeKind.TECHNICAL,
        "actor_type": EventActorType.AGENT,
        "status": ObservationStatus.UNMATCHED,
        "created_at": NOW,
        "external_decision_id": "external_decision_1",
        "technical_status": TechnicalOutcomeStatus.SUCCEEDED,
    }
    arguments.update(overrides)
    return OutcomeObservation(**arguments)  # type: ignore[arg-type]


def test_existing_records_keep_conservative_provenance_defaults() -> None:
    # Given: a source and event created without Decision I/O metadata
    source = Source("source_1", "profile_1", "manual", "Fixture", NOW)
    event = RawEvent("event_1", "profile_1", None, "interaction", {}, NOW, NOW)
    # When: their provenance is inspected
    # Then: nothing is assumed about consent, acquisition, actor, or eligibility
    assert source.provenance.acquisition_method is AcquisitionMethod.LEGACY_UNVERIFIED
    assert source.provenance.consent_mode is ConsentMode.LEGACY_UNVERIFIED
    assert source.provenance.raw_retention_policy is RawRetentionPolicy.METADATA_ONLY
    assert event.provenance.actor_type is EventActorType.UNKNOWN
    assert event.provenance.evidence_eligibility is EvidenceEligibility.CONTEXTUAL_ONLY


def test_decisions_default_to_owner_interactive_origin() -> None:
    # Given/When: a decision is created without explicit provenance
    decision = DecisionEvent(
        "decision_1", "profile_1", "code", "Which fix?", {}, DecisionStatus.OPEN, NOW
    )
    # Then: it is attributed to the owner's own app, not an external service
    assert decision.origin is DecisionOrigin.OWNER_APP
    assert decision.purpose is DecisionPurpose.OWNER_INTERACTIVE
    assert decision.source_id is None


def test_external_identifiers_require_a_source() -> None:
    # Given/When: an externally identified decision omits its source
    with pytest.raises(ValueError, match="must reference its source"):
        DecisionEvent(
            "decision_1",
            "profile_1",
            "code",
            "Which fix?",
            {},
            DecisionStatus.OPEN,
            NOW,
            origin=DecisionOrigin.EXTERNAL_SERVICE,
            purpose=DecisionPurpose.AGENT_CONSULTATION,
            external_decision_id="external_1",
        )
    # Then: the same rule holds for events
    with pytest.raises(ValueError, match="must reference its source"):
        RawEvent(
            "event_1",
            "profile_1",
            None,
            "interaction",
            {},
            NOW,
            NOW,
            provenance=EventProvenance(external_event_id="external_1"),
        )


def test_source_provenance_rejects_empty_or_repeated_data_classes() -> None:
    # Given/When: a source declares no data class, or repeats one
    with pytest.raises(ValueError, match="at least one data class"):
        SourceProvenance(data_classes=())
    with pytest.raises(ValueError, match="must not repeat"):
        SourceProvenance(data_classes=(DataClass.DECISION, DataClass.DECISION))


def test_explicit_consent_must_record_when_it_was_granted() -> None:
    # Given/When: a source claims explicit consent without a timestamp
    with pytest.raises(ValueError, match="when it was granted"):
        SourceProvenance(consent_mode=ConsentMode.OWNER_EXPLICIT)


def test_source_provenance_rejects_naive_consent_timestamps() -> None:
    # Given/When: consent is recorded without a UTC offset
    with pytest.raises(ValueError, match="timezone-aware"):
        SourceProvenance(
            consent_mode=ConsentMode.OWNER_EXPLICIT, consent_at=datetime(2026, 9, 23, 12, 0)
        )


def test_source_provenance_must_record_a_policy_profile_version() -> None:
    # Given/When: the policy profile version is blank
    with pytest.raises(ValueError, match="policy profile version"):
        SourceProvenance(policy_profile_version="   ")


def test_author_scope_covers_exactly_the_declared_authors() -> None:
    # Given: one source per author scope
    owner_only = SourceProvenance(author_scope=AuthorScope.OWNER_ONLY)
    agent_only = SourceProvenance(author_scope=AuthorScope.AGENT_ONLY)
    mixed = SourceProvenance(author_scope=AuthorScope.MIXED)
    # When/Then: each accepts only the actors it declared
    assert owner_only.allows_actor(EventActorType.OWNER)
    assert not owner_only.allows_actor(EventActorType.AGENT)
    assert agent_only.allows_actor(EventActorType.ASSISTANT)
    assert not agent_only.allows_actor(EventActorType.OWNER)
    assert mixed.allows_actor(EventActorType.OWNER)
    assert mixed.allows_actor(EventActorType.THIRD_PARTY)


def test_event_provenance_rejects_invalid_envelopes() -> None:
    # Given/When: a schema version below one, a blank external ID, or an
    # uncorrelated causation link is supplied
    with pytest.raises(ValueError, match="must be positive"):
        EventProvenance(schema_version=0)
    with pytest.raises(ValueError, match="omitted or contain text"):
        EventProvenance(external_event_id="   ")
    with pytest.raises(ValueError, match="correlation"):
        EventProvenance(causation_event_id="event_1")


def test_an_observation_must_reference_a_decision_identifier() -> None:
    # Given/When: neither the internal nor the external decision ID is known
    with pytest.raises(ValueError, match="decision identifier"):
        resolution_observation(external_decision_id=None)
    with pytest.raises(ValueError, match="decision identifier"):
        outcome_observation(external_decision_id=None)


def test_a_matched_observation_leaves_the_unmatched_state() -> None:
    # Given/When: an observation names a stored decision but stays unmatched
    with pytest.raises(ValueError, match="unmatched status"):
        resolution_observation(decision_id="decision_1")
    with pytest.raises(ValueError, match="unmatched status"):
        outcome_observation(decision_id="decision_1")


def test_confirmation_requires_both_a_time_and_a_stored_decision() -> None:
    # Given/When: confirmation is claimed without a timestamp or a decision
    with pytest.raises(ValueError, match="must agree"):
        resolution_observation(
            status=ObservationStatus.CONFIRMED, decision_id="decision_1", confirmed_at=None
        )
    with pytest.raises(ValueError, match="stored decision"):
        outcome_observation(status=ObservationStatus.CONFIRMED, confirmed_at=NOW, decision_id=None)


def test_an_unconfirmed_observation_must_not_carry_a_confirmation_time() -> None:
    # Given/When: a pending observation records a confirmation timestamp
    with pytest.raises(ValueError, match="must agree"):
        resolution_observation(
            status=ObservationStatus.PENDING, decision_id="decision_1", confirmed_at=NOW
        )


def test_correlation_confidence_stays_within_its_range() -> None:
    # Given/When: the boundaries and one value outside them are supplied
    assert resolution_observation(correlation_confidence=0.0).correlation_confidence == 0.0
    assert resolution_observation(correlation_confidence=1.0).correlation_confidence == 1.0
    with pytest.raises(ValueError, match="between 0 and 1"):
        resolution_observation(correlation_confidence=1.01)


def test_technical_results_cannot_carry_satisfaction_or_regret() -> None:
    # Given/When: an agent reports a technical result as owner wellbeing
    with pytest.raises(ValueError, match="owner-reported outcomes only"):
        outcome_observation(satisfaction=0.9)
    with pytest.raises(ValueError, match="owner-reported outcomes only"):
        outcome_observation(regret=False)


def test_each_outcome_kind_carries_only_its_own_fields() -> None:
    # Given/When: a kind is combined with another kind's fields, or misses its own
    with pytest.raises(ValueError, match="technical status"):
        outcome_observation(kind=OutcomeKind.USER_BEHAVIOR, disposition=UserDisposition.ACCEPTED)
    with pytest.raises(ValueError, match="must record its technical status"):
        outcome_observation(technical_status=None)
    with pytest.raises(ValueError, match="must record the owner's disposition"):
        outcome_observation(kind=OutcomeKind.USER_BEHAVIOR, technical_status=None)
    with pytest.raises(ValueError, match="report satisfaction and regret"):
        outcome_observation(kind=OutcomeKind.OWNER_REPORTED, technical_status=None)


def test_owner_reported_observations_accept_satisfaction_and_regret() -> None:
    # Given/When: an owner-reported observation is built completely
    observation = outcome_observation(
        kind=OutcomeKind.OWNER_REPORTED,
        technical_status=None,
        satisfaction=0.75,
        regret=False,
    )
    # Then: the wellbeing fields are retained as an unconfirmed report
    assert observation.satisfaction == 0.75
    assert observation.status is ObservationStatus.UNMATCHED


def test_observed_satisfaction_stays_within_its_range() -> None:
    # Given/When: satisfaction is reported outside the 0 to 1 range
    with pytest.raises(ValueError, match="between 0 and 1"):
        outcome_observation(
            kind=OutcomeKind.OWNER_REPORTED,
            technical_status=None,
            satisfaction=1.5,
            regret=True,
        )


def _ingested_event(external_id: str | None = "external_1") -> RawEvent:
    return RawEvent(
        "event_1",
        "profile_1",
        "source_1",
        "decision_resolution",
        {},
        NOW,
        NOW,
        provenance=EventProvenance(external_event_id=external_id, content_fingerprint="digest"),
    )


def test_an_ingestion_write_requires_source_identity_and_fingerprint() -> None:
    # Given/When: an event without an external ID or without a fingerprint
    with pytest.raises(ValueError, match="source and external event ID"):
        IngestionWrite(event=_ingested_event(None))
    unfingerprinted = RawEvent(
        "event_1",
        "profile_1",
        "source_1",
        "interaction",
        {},
        NOW,
        NOW,
        provenance=EventProvenance(external_event_id="external_1"),
    )
    # Then: both are refused before reaching storage
    with pytest.raises(ValueError, match="content fingerprint"):
        IngestionWrite(event=unfingerprinted)


def test_a_promoted_resolution_must_match_its_confirmed_observation() -> None:
    # Given: a pending observation and a resolution for it
    pending = resolution_observation(
        status=ObservationStatus.PENDING,
        decision_id="decision_1",
        chosen_option_id="option_a",
    )
    resolution = DecisionResolution("resolution_1", "decision_1", "option_a", "event_1", NOW)
    # When/Then: promotion without confirmation, or of another option, is refused
    with pytest.raises(ValueError, match="confirmed observation"):
        IngestionWrite(
            event=_ingested_event(), resolution_observation=pending, resolution=resolution
        )
    confirmed = replace(pending, status=ObservationStatus.CONFIRMED, confirmed_at=NOW)
    with pytest.raises(ValueError, match="confirmed observation"):
        IngestionWrite(
            event=_ingested_event(),
            resolution_observation=confirmed,
            resolution=replace(resolution, chosen_option_id="option_b"),
        )
    accepted = IngestionWrite(
        event=_ingested_event(), resolution_observation=confirmed, resolution=resolution
    )
    assert accepted.resolution == resolution


def test_ingested_evidence_needs_a_promoted_resolution() -> None:
    # Given: Evidence that no promoted resolution produced
    evidence = Evidence(
        id="evidence_1",
        profile_id="profile_1",
        target_type=EvidenceTargetType.PREFERENCE,
        target_key="code.simple",
        value=1.0,
        strength=1.0,
        confidence=1.0,
        context={},
        source_type="decision_choice",
        source_event_id="event_1",
        extractor_version="synthetic-v1",
        created_at=NOW,
    )
    # When/Then: it cannot ride along with an ingested event
    with pytest.raises(ValueError, match="promoted resolution"):
        IngestionWrite(event=_ingested_event(), evidence=(evidence,))
