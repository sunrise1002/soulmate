"""Atomic Decision I/O persistence contract.

One accepted request commits its raw event, correlation links, and lifecycle
projection together or not at all. No LLM or network call belongs on this path.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from soulmate_core.decision_io.policy import DecisionIoError
from soulmate_core.domain import (
    DecisionEvent,
    DecisionOption,
    DecisionResolution,
    Evidence,
    ObservationStatus,
    OutcomeObservation,
    RawEvent,
    ResolutionObservation,
)


class DecisionIoConflictError(DecisionIoError):
    """An external event ID was reused with different canonical content."""

    def __init__(
        self, message: str = "The external event ID was already used for other content."
    ) -> None:
        super().__init__("external_event_conflict", message)


@dataclass(frozen=True, slots=True)
class IngestionWrite:
    """Everything one accepted event may persist in a single transaction."""

    event: RawEvent
    decision: tuple[DecisionEvent, tuple[DecisionOption, ...]] | None = None
    resolution_observation: ResolutionObservation | None = None
    outcome_observation: OutcomeObservation | None = None
    # A promotion commits with the event; only the model rebuild happens later.
    resolution: DecisionResolution | None = None
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        if self.event.source_id is None or self.event.provenance.external_event_id is None:
            raise ValueError("An ingested event must carry its source and external event ID.")
        if self.event.provenance.content_fingerprint is None:
            raise ValueError("An ingested event must carry its content fingerprint.")
        for observation in (self.resolution_observation, self.outcome_observation):
            if observation is not None and observation.source_event_id != self.event.id:
                raise ValueError("An observation must reference the event that reported it.")
        if self.decision is not None and self.decision[0].source_id != self.event.source_id:
            raise ValueError("An ingested decision must belong to the reporting source.")
        if self.evidence and self.resolution is None:
            raise ValueError("Ingested Evidence may only come from a promoted resolution.")
        if self.resolution is not None:
            observation = self.resolution_observation
            if (
                observation is None
                or observation.status is not ObservationStatus.CONFIRMED
                or observation.decision_id != self.resolution.decision_id
                or observation.chosen_option_id != self.resolution.chosen_option_id
                or self.resolution.source_event_id != self.event.id
            ):
                raise ValueError("A promoted resolution must match its confirmed observation.")
        if any(item.source_event_id != self.event.id for item in self.evidence):
            raise ValueError("Promoted Evidence must reference the event that reported it.")


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """What one ingestion call persisted, or replayed for an identical retry."""

    event_id: str
    duplicate: bool
    decision_id: str | None = None
    resolution_observation_id: str | None = None
    outcome_observation_id: str | None = None
    observation_status: ObservationStatus | None = None


@dataclass(frozen=True, slots=True)
class SourceObservationCounts:
    """Owner-visible volume of what one source has produced."""

    source_id: str
    raw_event_count: int
    decision_count: int
    resolution_observation_count: int
    outcome_observation_count: int
    unmatched_observation_count: int


@dataclass(frozen=True, slots=True)
class DecisionIoSourceRemoval:
    """What removing one pushed source deleted from the provenance graph."""

    source_id: str
    raw_event_count: int
    decision_count: int
    observation_count: int
    evidence_count: int


class DecisionIoRepository(Protocol):
    """Transactional Decision I/O persistence owned by the storage adapter."""

    def ingest(self, write: IngestionWrite) -> IngestionResult:
        """Persist one event and its projection, or replay an identical retry.

        A new decision attaches earlier unmatched observations that its own source
        reported for the same external decision ID, in the same transaction.

        Raises ``DecisionIoConflictError`` when the external event ID was already
        used with a different content fingerprint.
        """
        ...

    def find_decision_by_external_id(
        self, profile_id: str, source_id: str, external_decision_id: str
    ) -> tuple[DecisionEvent, tuple[DecisionOption, ...]] | None: ...

    def list_resolution_observations(
        self, profile_id: str, status: ObservationStatus | None = None
    ) -> tuple[ResolutionObservation, ...]: ...

    def list_outcome_observations(
        self, profile_id: str, status: ObservationStatus | None = None
    ) -> tuple[OutcomeObservation, ...]: ...

    def get_outcome_observation(
        self, profile_id: str, observation_id: str
    ) -> OutcomeObservation | None: ...

    def get_resolution_observation(
        self, profile_id: str, observation_id: str
    ) -> ResolutionObservation | None: ...

    def set_resolution_observation_status(
        self,
        observation_id: str,
        expected: ObservationStatus,
        status: ObservationStatus,
        reason_code: str,
        changed_at: datetime | None,
    ) -> bool: ...

    def set_outcome_observation_status(
        self,
        observation_id: str,
        expected: ObservationStatus,
        status: ObservationStatus,
        reason_code: str,
        changed_at: datetime | None,
    ) -> bool: ...

    def confirm_resolution_observation(
        self,
        observation_id: str,
        expected: ObservationStatus,
        resolution: DecisionResolution,
        evidence: tuple[Evidence, ...],
        confirmed_at: datetime,
    ) -> bool:
        """Confirm a reported choice and apply its canonical resolution atomically.

        Returns ``False`` without writing when the observation left ``expected``.
        """
        ...

    def counts_for_source(self, profile_id: str, source_id: str) -> SourceObservationCounts: ...

    def remove_source(self, profile_id: str, source_id: str) -> DecisionIoSourceRemoval | None:
        """Remove a pushed source with every record derived from it."""
        ...


__all__ = [
    "DecisionIoConflictError",
    "DecisionIoRepository",
    "DecisionIoSourceRemoval",
    "IngestionResult",
    "IngestionWrite",
    "SourceObservationCounts",
]
