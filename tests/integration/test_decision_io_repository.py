"""Transactional guarantees of the SQLite Decision I/O repository (P13-05)."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from soulmate_core.decision_io import (
    DecisionIoConflictError,
    DecisionIoError,
    IngestionWrite,
    content_fingerprint,
)
from soulmate_core.domain import (
    AcquisitionMethod,
    ConsentMode,
    DataClass,
    DecisionEvent,
    DecisionOption,
    DecisionOrigin,
    DecisionPurpose,
    DecisionResolution,
    DecisionStatus,
    EventActorType,
    EventProvenance,
    ObservationStatus,
    Profile,
    RawEvent,
    ResolutionObservation,
    Source,
    SourceProvenance,
    UserDisposition,
)
from soulmate_storage_sqlite import Database, Repositories

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
PROFILE = "profile_repository"
SOURCE = "source_agent"


def _storage(tmp_path: Path) -> tuple[Database, Repositories]:
    database = Database(tmp_path / "soulmate.db")
    database.migrate()
    assert database.session_factory is not None
    repositories = Repositories(database.session_factory)
    repositories.profiles.add(Profile(PROFILE, None, NOW))
    repositories.sources.add(
        Source(
            SOURCE,
            PROFILE,
            "agent:synthetic",
            "Synthetic agent",
            NOW,
            SourceProvenance(
                provider="synthetic",
                acquisition_method=AcquisitionMethod.AGENT_PUSH,
                consent_mode=ConsentMode.OWNER_EXPLICIT,
                consent_at=NOW,
                data_classes=(DataClass.METADATA, DataClass.DECISION),
                service_identity_id="service_1",
            ),
        )
    )
    return database, repositories


def _event(event_id: str, external_id: str, content: dict[str, object]) -> RawEvent:
    return RawEvent(
        id=event_id,
        profile_id=PROFILE,
        source_id=SOURCE,
        event_type="decision_resolution",
        content=content,
        created_at=NOW,
        ingested_at=NOW,
        provenance=EventProvenance(
            external_event_id=external_id,
            actor_type=EventActorType.OWNER,
            content_fingerprint=content_fingerprint(content),
        ),
    )


def _resolved_decision(repositories: Repositories) -> tuple[DecisionEvent, DecisionOption]:
    decision = DecisionEvent(
        "decision_1",
        PROFILE,
        "code",
        "Which fix?",
        {},
        DecisionStatus.OPEN,
        NOW,
        origin=DecisionOrigin.EXTERNAL_SERVICE,
        purpose=DecisionPurpose.OBSERVED,
        source_id=SOURCE,
        external_decision_id="external_decision_1",
    )
    options = tuple(
        DecisionOption(f"option_{name}", decision.id, name, name, {"code.simple": 1.0}, 1.0)
        for name in ("a", "b")
    )
    repositories.decisions.add(decision, options)
    repositories.raw_events.add(RawEvent("event_owner", PROFILE, None, "x", {}, NOW, NOW))
    repositories.decisions.resolve(
        DecisionResolution("resolution_1", decision.id, options[0].id, "event_owner", NOW)
    )
    return decision, options[1]


def test_a_failed_promotion_leaves_no_partial_state(tmp_path: Path) -> None:
    # Given: a decision that is already resolved
    database, repositories = _storage(tmp_path)
    decision, option = _resolved_decision(repositories)
    event = _event("event_late", "late-1", {"chosen": "b"})
    observation = ResolutionObservation(
        id="observation_late",
        profile_id=PROFILE,
        source_id=SOURCE,
        source_event_id=event.id,
        actor_type=EventActorType.OWNER,
        status=ObservationStatus.CONFIRMED,
        disposition=UserDisposition.ACCEPTED,
        created_at=NOW,
        decision_id=decision.id,
        external_decision_id="external_decision_1",
        chosen_option_id=option.id,
        confirmed_at=NOW,
    )
    write = IngestionWrite(
        event=event,
        resolution_observation=observation,
        resolution=DecisionResolution("resolution_2", decision.id, option.id, event.id, NOW),
    )
    # When: the write tries to resolve it a second time
    with pytest.raises(DecisionIoError) as error:
        repositories.decision_io.ingest(write)
    # Then: the event, observation, and resolution were all rolled back
    assert error.value.reason_code == "decision_already_resolved"
    assert repositories.raw_events.get(event.id) is None
    assert repositories.decision_io.list_resolution_observations(PROFILE) == ()
    resolution = repositories.decisions.get_resolution(decision.id)
    assert resolution is not None and resolution.id == "resolution_1"
    database.close()


def test_retries_replay_and_conflicts_do_not_write(tmp_path: Path) -> None:
    # Given: one ingested event
    database, repositories = _storage(tmp_path)
    first = repositories.decision_io.ingest(
        IngestionWrite(event=_event("event_1", "external-1", {"a": 1}))
    )
    # When: the same external event is retried, then reused for other content
    retry = repositories.decision_io.ingest(
        IngestionWrite(event=_event("event_2", "external-1", {"a": 1}))
    )
    with pytest.raises(DecisionIoConflictError):
        repositories.decision_io.ingest(
            IngestionWrite(event=_event("event_3", "external-1", {"a": 2}))
        )
    # Then: only the first event exists and the retry points at it
    assert (first.duplicate, retry.duplicate) == (False, True)
    assert retry.event_id == first.event_id == "event_1"
    assert repositories.raw_events.get("event_2") is None
    assert repositories.raw_events.get("event_3") is None
    assert repositories.decision_io.counts_for_source(PROFILE, SOURCE).raw_event_count == 1
    database.close()


def test_confirmation_requires_the_expected_state(tmp_path: Path) -> None:
    # Given: an open decision and a pending reported choice
    database, repositories = _storage(tmp_path)
    decision = DecisionEvent(
        "decision_open",
        PROFILE,
        "code",
        "Which fix?",
        {},
        DecisionStatus.OPEN,
        NOW,
        source_id=SOURCE,
        external_decision_id="external_open",
    )
    option = DecisionOption("option_open", decision.id, "A", "A", {"code.simple": 1.0}, 1.0)
    repositories.decisions.add(decision, (option, replace(option, id="option_other")))
    event = _event("event_choice", "choice-1", {"chosen": "a"})
    pending = ResolutionObservation(
        id="observation_pending",
        profile_id=PROFILE,
        source_id=SOURCE,
        source_event_id=event.id,
        actor_type=EventActorType.AGENT,
        status=ObservationStatus.PENDING,
        disposition=UserDisposition.ACCEPTED,
        created_at=NOW,
        decision_id=decision.id,
        chosen_option_id=option.id,
    )
    repositories.decision_io.ingest(IngestionWrite(event=event, resolution_observation=pending))
    resolution = DecisionResolution("resolution_open", decision.id, option.id, event.id, NOW)
    # When: a stale confirmation expects another state
    stale = repositories.decision_io.confirm_resolution_observation(
        pending.id, ObservationStatus.UNMATCHED, resolution, (), NOW
    )
    # Then: nothing is written until the expected state matches
    assert stale is False
    assert repositories.decisions.get_resolution(decision.id) is None
    applied = repositories.decision_io.confirm_resolution_observation(
        pending.id, ObservationStatus.PENDING, resolution, (), NOW
    )
    assert applied is True
    assert repositories.decisions.get_resolution(decision.id) is not None
    database.close()


def test_only_pushed_sources_can_be_removed_through_decision_io(tmp_path: Path) -> None:
    # Given: an imported source next to the pushed one
    database, repositories = _storage(tmp_path)
    repositories.sources.add(Source("source_import", PROFILE, "import:json", "Import", NOW))
    # When: Decision I/O removal targets it or an unknown source
    imported = repositories.decision_io.remove_source(PROFILE, "source_import")
    missing = repositories.decision_io.remove_source(PROFILE, "source_missing")
    # Then: neither is touched, so each removal path keeps its own rules
    assert imported is None and missing is None
    assert repositories.sources.get("source_import") is not None
    database.close()
