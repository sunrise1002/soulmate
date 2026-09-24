"""SQLite persistence for Decision I/O provenance and lifecycle observations."""

import json
from datetime import UTC, datetime
from typing import cast

from soulmate_core.decision_io import (
    DecisionIoConflictError,
    DecisionIoError,
    DecisionIoSourceRemoval,
    IngestionResult,
    IngestionWrite,
    SourceObservationCounts,
)
from soulmate_core.domain import (
    AcquisitionMethod,
    AuthorScope,
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
    Evidence,
    EvidenceEligibility,
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
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from soulmate_storage_sqlite.key_aliases import bump_evidence_revision, prune_unsupported_keys
from soulmate_storage_sqlite.schema import (
    DecisionEventRow,
    DecisionOptionRow,
    DecisionResolutionRow,
    EvidenceRow,
    OutcomeObservationRow,
    RawEventRow,
    ResolutionObservationRow,
    SourceRow,
)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


def source_provenance_columns(provenance: SourceProvenance) -> dict[str, object]:
    """Column values for one source's acquisition metadata."""
    return {
        "provider": provenance.provider,
        "acquisition_method": provenance.acquisition_method.value,
        "consent_mode": provenance.consent_mode.value,
        "consent_at": provenance.consent_at,
        "data_classes_json": json.dumps(
            [item.value for item in provenance.data_classes], sort_keys=True
        ),
        "author_scope": provenance.author_scope.value,
        "raw_retention_policy": provenance.raw_retention_policy.value,
        "adapter_version": provenance.adapter_version,
        "parser_version": provenance.parser_version,
        "policy_profile_version": provenance.policy_profile_version,
        "service_identity_id": provenance.service_identity_id,
    }


def source_provenance_of(row: SourceRow) -> SourceProvenance:
    return SourceProvenance(
        provider=row.provider,
        acquisition_method=AcquisitionMethod(row.acquisition_method),
        consent_mode=ConsentMode(row.consent_mode),
        consent_at=_optional_utc(row.consent_at),
        data_classes=tuple(DataClass(item) for item in json.loads(row.data_classes_json)),
        author_scope=AuthorScope(row.author_scope),
        raw_retention_policy=RawRetentionPolicy(row.raw_retention_policy),
        adapter_version=row.adapter_version,
        parser_version=row.parser_version,
        policy_profile_version=row.policy_profile_version,
        service_identity_id=row.service_identity_id,
    )


def event_provenance_columns(provenance: EventProvenance) -> dict[str, object]:
    """Column values for one raw event's normalized envelope."""
    return {
        "schema_version": provenance.schema_version,
        "external_event_id": provenance.external_event_id,
        "actor_type": provenance.actor_type.value,
        "evidence_eligibility": provenance.evidence_eligibility.value,
        "correlation_id": provenance.correlation_id,
        "causation_event_id": provenance.causation_event_id,
        "content_fingerprint": provenance.content_fingerprint,
    }


def event_provenance_of(row: RawEventRow) -> EventProvenance:
    return EventProvenance(
        schema_version=row.schema_version,
        external_event_id=row.external_event_id,
        actor_type=EventActorType(row.actor_type),
        evidence_eligibility=EvidenceEligibility(row.evidence_eligibility),
        correlation_id=row.correlation_id,
        causation_event_id=row.causation_event_id,
        content_fingerprint=row.content_fingerprint,
    )


def evidence_row(evidence: Evidence) -> EvidenceRow:
    """Row values for one Evidence item; callers bump the evidence revision."""
    return EvidenceRow(
        id=evidence.id,
        profile_id=evidence.profile_id,
        target_type=evidence.target_type.value,
        target_key=evidence.target_key,
        value_json=_json_dump(evidence.value),
        strength=evidence.strength,
        confidence=evidence.confidence,
        context_json=_json_dump(evidence.context),
        source_type=evidence.source_type,
        source_event_id=evidence.source_event_id,
        extractor_version=evidence.extractor_version,
        extractor_model=evidence.extractor_model,
        source_message_id=evidence.source_message_id,
        created_at=evidence.created_at,
    )


def source_of(row: SourceRow) -> Source:
    return Source(
        id=row.id,
        profile_id=row.profile_id,
        source_type=row.source_type,
        name=row.name,
        created_at=_utc(row.created_at),
        provenance=source_provenance_of(row),
    )


def raw_event_of(row: RawEventRow) -> RawEvent:
    return RawEvent(
        id=row.id,
        profile_id=row.profile_id,
        source_id=row.source_id,
        event_type=row.event_type,
        content=json.loads(row.content_json),
        created_at=_utc(row.created_at),
        ingested_at=_utc(row.ingested_at),
        sensitivity=row.sensitivity,
        provenance=event_provenance_of(row),
    )


def decision_of(row: DecisionEventRow) -> DecisionEvent:
    return DecisionEvent(
        id=row.id,
        profile_id=row.profile_id,
        domain=row.domain,
        question=row.question,
        context=json.loads(row.context_json),
        status=DecisionStatus(row.status),
        created_at=_utc(row.created_at),
        origin=DecisionOrigin(row.origin),
        purpose=DecisionPurpose(row.purpose),
        source_id=row.source_id,
        external_decision_id=row.external_decision_id,
        source_event_id=row.source_event_id,
    )


def option_of(row: DecisionOptionRow) -> DecisionOption:
    return DecisionOption(
        id=row.id,
        decision_id=row.decision_id,
        label=row.label,
        description=row.description,
        features=json.loads(row.features_json),
        feature_confidence=row.feature_confidence,
        external_option_id=row.external_option_id,
    )


def _resolution_of(row: ResolutionObservationRow) -> ResolutionObservation:
    return ResolutionObservation(
        id=row.id,
        profile_id=row.profile_id,
        source_id=row.source_id,
        source_event_id=row.source_event_id,
        actor_type=EventActorType(row.actor_type),
        status=ObservationStatus(row.status),
        disposition=UserDisposition(row.disposition),
        created_at=_utc(row.created_at),
        decision_id=row.decision_id,
        external_decision_id=row.external_decision_id,
        chosen_option_id=row.chosen_option_id,
        external_option_id=row.external_option_id,
        correlation_confidence=row.correlation_confidence,
        confirmed_at=_optional_utc(row.confirmed_at),
        reason_code=row.reason_code,
    )


def _outcome_of(row: OutcomeObservationRow) -> OutcomeObservation:
    return OutcomeObservation(
        id=row.id,
        profile_id=row.profile_id,
        source_id=row.source_id,
        source_event_id=row.source_event_id,
        kind=OutcomeKind(row.kind),
        actor_type=EventActorType(row.actor_type),
        status=ObservationStatus(row.status),
        created_at=_utc(row.created_at),
        decision_id=row.decision_id,
        external_decision_id=row.external_decision_id,
        technical_status=(
            None if row.technical_status is None else TechnicalOutcomeStatus(row.technical_status)
        ),
        disposition=None if row.disposition is None else UserDisposition(row.disposition),
        satisfaction=row.satisfaction,
        regret=row.regret,
        confirmed_at=_optional_utc(row.confirmed_at),
        reason_code=row.reason_code,
    )


class SqliteDecisionIoRepository:
    """Commit one ingested event and its projection atomically, or nothing."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def ingest(self, write: IngestionWrite) -> IngestionResult:
        event = write.event
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(RawEventRow).where(
                    RawEventRow.source_id == event.source_id,
                    RawEventRow.external_event_id == event.provenance.external_event_id,
                )
            )
            if existing is not None:
                if existing.content_fingerprint != event.provenance.content_fingerprint:
                    raise DecisionIoConflictError
                return self._replay(session, existing)
            session.add(
                RawEventRow(
                    id=event.id,
                    profile_id=event.profile_id,
                    source_id=event.source_id,
                    event_type=event.event_type,
                    content_json=_json_dump(event.content),
                    created_at=event.created_at,
                    ingested_at=event.ingested_at,
                    sensitivity=event.sensitivity,
                    **event_provenance_columns(event.provenance),
                )
            )
            session.flush()
            decision_id: str | None = None
            if write.decision is not None:
                decision, options = write.decision
                decision_id = decision.id
                session.add(
                    DecisionEventRow(
                        id=decision.id,
                        profile_id=decision.profile_id,
                        domain=decision.domain,
                        question=decision.question,
                        context_json=_json_dump(decision.context),
                        status=decision.status.value,
                        created_at=decision.created_at,
                        origin=decision.origin.value,
                        purpose=decision.purpose.value,
                        source_id=decision.source_id,
                        external_decision_id=decision.external_decision_id,
                        source_event_id=decision.source_event_id,
                    )
                )
                session.flush()
                session.add_all(
                    DecisionOptionRow(
                        id=item.id,
                        decision_id=item.decision_id,
                        label=item.label,
                        description=item.description,
                        features_json=_json_dump(item.features),
                        feature_confidence=item.feature_confidence,
                        external_option_id=item.external_option_id,
                    )
                    for item in options
                )
                session.flush()
                if decision.external_decision_id is not None and decision.source_id is not None:
                    self._attach_unmatched(
                        session,
                        decision.profile_id,
                        decision.source_id,
                        decision.external_decision_id,
                        decision.id,
                    )
            status: ObservationStatus | None = None
            resolution_id: str | None = None
            outcome_id: str | None = None
            if write.resolution_observation is not None:
                observation = write.resolution_observation
                resolution_id = observation.id
                status = observation.status
                session.add(
                    ResolutionObservationRow(
                        id=observation.id,
                        profile_id=observation.profile_id,
                        source_id=observation.source_id,
                        source_event_id=observation.source_event_id,
                        actor_type=observation.actor_type.value,
                        status=observation.status.value,
                        disposition=observation.disposition.value,
                        decision_id=observation.decision_id,
                        external_decision_id=observation.external_decision_id,
                        chosen_option_id=observation.chosen_option_id,
                        external_option_id=observation.external_option_id,
                        correlation_confidence=observation.correlation_confidence,
                        created_at=observation.created_at,
                        confirmed_at=observation.confirmed_at,
                        reason_code=observation.reason_code,
                    )
                )
            if write.outcome_observation is not None:
                outcome = write.outcome_observation
                outcome_id = outcome.id
                status = outcome.status
                session.add(
                    OutcomeObservationRow(
                        id=outcome.id,
                        profile_id=outcome.profile_id,
                        source_id=outcome.source_id,
                        source_event_id=outcome.source_event_id,
                        kind=outcome.kind.value,
                        actor_type=outcome.actor_type.value,
                        status=outcome.status.value,
                        decision_id=outcome.decision_id,
                        external_decision_id=outcome.external_decision_id,
                        technical_status=(
                            None
                            if outcome.technical_status is None
                            else outcome.technical_status.value
                        ),
                        disposition=(
                            None if outcome.disposition is None else outcome.disposition.value
                        ),
                        satisfaction=outcome.satisfaction,
                        regret=outcome.regret,
                        created_at=outcome.created_at,
                        confirmed_at=outcome.confirmed_at,
                        reason_code=outcome.reason_code,
                    )
                )
            if write.resolution is not None:
                self._apply_resolution(session, write.resolution, write.evidence)
            return IngestionResult(
                event_id=event.id,
                duplicate=False,
                decision_id=decision_id,
                resolution_observation_id=resolution_id,
                outcome_observation_id=outcome_id,
                observation_status=status,
            )

    def confirm_resolution_observation(
        self,
        observation_id: str,
        expected: ObservationStatus,
        resolution: DecisionResolution,
        evidence: tuple[Evidence, ...],
        confirmed_at: datetime,
    ) -> bool:
        with self._sessions.begin() as session:
            observation = session.get(ResolutionObservationRow, observation_id)
            if (
                observation is None
                or observation.status != expected.value
                or observation.decision_id != resolution.decision_id
                or observation.chosen_option_id != resolution.chosen_option_id
                or observation.source_event_id != resolution.source_event_id
            ):
                return False
            observation.status = ObservationStatus.CONFIRMED.value
            observation.confirmed_at = confirmed_at
            observation.reason_code = "owner_confirmed"
            self._apply_resolution(session, resolution, evidence)
            return True

    @staticmethod
    def _apply_resolution(
        session: Session, resolution: DecisionResolution, evidence: tuple[Evidence, ...]
    ) -> None:
        """Resolve the decision and add its choice Evidence in the caller's transaction."""
        decision = session.get(DecisionEventRow, resolution.decision_id)
        option = session.get(DecisionOptionRow, resolution.chosen_option_id)
        if decision is None or option is None or option.decision_id != decision.id:
            raise DecisionIoError(
                "option_not_found", "The reported option does not belong to that decision."
            )
        if decision.status != DecisionStatus.OPEN.value:
            raise DecisionIoError(
                "decision_already_resolved", "The decision has already been resolved."
            )
        session.add(
            DecisionResolutionRow(
                id=resolution.id,
                decision_id=resolution.decision_id,
                chosen_option_id=resolution.chosen_option_id,
                source_event_id=resolution.source_event_id,
                created_at=resolution.created_at,
            )
        )
        decision.status = DecisionStatus.RESOLVED.value
        session.add_all(evidence_row(item) for item in evidence)
        if evidence:
            session.flush()
            bump_evidence_revision(session, decision.profile_id)

    def find_decision_by_external_id(
        self, profile_id: str, source_id: str, external_decision_id: str
    ) -> tuple[DecisionEvent, tuple[DecisionOption, ...]] | None:
        with self._sessions() as session:
            row = session.scalar(
                select(DecisionEventRow).where(
                    DecisionEventRow.profile_id == profile_id,
                    DecisionEventRow.source_id == source_id,
                    DecisionEventRow.external_decision_id == external_decision_id,
                )
            )
            if row is None:
                return None
            options = session.scalars(
                select(DecisionOptionRow)
                .where(DecisionOptionRow.decision_id == row.id)
                .order_by(DecisionOptionRow.id)
            )
            return decision_of(row), tuple(option_of(item) for item in options)

    def list_resolution_observations(
        self, profile_id: str, status: ObservationStatus | None = None
    ) -> tuple[ResolutionObservation, ...]:
        with self._sessions() as session:
            query = select(ResolutionObservationRow).where(
                ResolutionObservationRow.profile_id == profile_id
            )
            if status is not None:
                query = query.where(ResolutionObservationRow.status == status.value)
            rows = session.scalars(
                query.order_by(
                    ResolutionObservationRow.created_at.desc(), ResolutionObservationRow.id.desc()
                )
            )
            return tuple(_resolution_of(row) for row in rows)

    def list_outcome_observations(
        self, profile_id: str, status: ObservationStatus | None = None
    ) -> tuple[OutcomeObservation, ...]:
        with self._sessions() as session:
            query = select(OutcomeObservationRow).where(
                OutcomeObservationRow.profile_id == profile_id
            )
            if status is not None:
                query = query.where(OutcomeObservationRow.status == status.value)
            rows = session.scalars(
                query.order_by(
                    OutcomeObservationRow.created_at.desc(), OutcomeObservationRow.id.desc()
                )
            )
            return tuple(_outcome_of(row) for row in rows)

    def get_resolution_observation(
        self, profile_id: str, observation_id: str
    ) -> ResolutionObservation | None:
        with self._sessions() as session:
            row = session.get(ResolutionObservationRow, observation_id)
            if row is None or row.profile_id != profile_id:
                return None
            return _resolution_of(row)

    def get_outcome_observation(
        self, profile_id: str, observation_id: str
    ) -> OutcomeObservation | None:
        with self._sessions() as session:
            row = session.get(OutcomeObservationRow, observation_id)
            if row is None or row.profile_id != profile_id:
                return None
            return _outcome_of(row)

    def set_resolution_observation_status(
        self,
        observation_id: str,
        expected: ObservationStatus,
        status: ObservationStatus,
        reason_code: str,
        changed_at: datetime | None,
    ) -> bool:
        with self._sessions.begin() as session:
            changed = session.execute(
                update(ResolutionObservationRow)
                .where(
                    ResolutionObservationRow.id == observation_id,
                    ResolutionObservationRow.status == expected.value,
                )
                .values(
                    status=status.value,
                    reason_code=reason_code,
                    confirmed_at=(changed_at if status is ObservationStatus.CONFIRMED else None),
                )
                .returning(ResolutionObservationRow.id)
            ).scalar_one_or_none()
            return changed is not None

    def set_outcome_observation_status(
        self,
        observation_id: str,
        expected: ObservationStatus,
        status: ObservationStatus,
        reason_code: str,
        changed_at: datetime | None,
    ) -> bool:
        with self._sessions.begin() as session:
            changed = session.execute(
                update(OutcomeObservationRow)
                .where(
                    OutcomeObservationRow.id == observation_id,
                    OutcomeObservationRow.status == expected.value,
                )
                .values(
                    status=status.value,
                    reason_code=reason_code,
                    confirmed_at=(changed_at if status is ObservationStatus.CONFIRMED else None),
                )
                .returning(OutcomeObservationRow.id)
            ).scalar_one_or_none()
            return changed is not None

    @staticmethod
    def _attach_unmatched(
        session: Session,
        profile_id: str,
        source_id: str,
        external_decision_id: str,
        decision_id: str,
    ) -> int:
        """Attach only observations whose own source reported the same decision ID."""
        attached = len(
            session.execute(
                update(ResolutionObservationRow)
                .where(
                    ResolutionObservationRow.profile_id == profile_id,
                    ResolutionObservationRow.source_id == source_id,
                    ResolutionObservationRow.external_decision_id == external_decision_id,
                    ResolutionObservationRow.decision_id.is_(None),
                    ResolutionObservationRow.status == ObservationStatus.UNMATCHED.value,
                )
                .values(decision_id=decision_id, status=ObservationStatus.PENDING.value)
                .returning(ResolutionObservationRow.id)
            )
            .scalars()
            .all()
        )
        attached += len(
            session.execute(
                update(OutcomeObservationRow)
                .where(
                    OutcomeObservationRow.profile_id == profile_id,
                    OutcomeObservationRow.source_id == source_id,
                    OutcomeObservationRow.external_decision_id == external_decision_id,
                    OutcomeObservationRow.decision_id.is_(None),
                    OutcomeObservationRow.status == ObservationStatus.UNMATCHED.value,
                )
                .values(decision_id=decision_id, status=ObservationStatus.PENDING.value)
                .returning(OutcomeObservationRow.id)
            )
            .scalars()
            .all()
        )
        return attached

    def counts_for_source(self, profile_id: str, source_id: str) -> SourceObservationCounts:
        with self._sessions() as session:
            unmatched = ObservationStatus.UNMATCHED.value
            return SourceObservationCounts(
                source_id=source_id,
                raw_event_count=self._count(
                    session, RawEventRow, RawEventRow.source_id == source_id
                ),
                decision_count=self._count(
                    session,
                    DecisionEventRow,
                    DecisionEventRow.source_id == source_id,
                    DecisionEventRow.profile_id == profile_id,
                ),
                resolution_observation_count=self._count(
                    session,
                    ResolutionObservationRow,
                    ResolutionObservationRow.source_id == source_id,
                    ResolutionObservationRow.profile_id == profile_id,
                ),
                outcome_observation_count=self._count(
                    session,
                    OutcomeObservationRow,
                    OutcomeObservationRow.source_id == source_id,
                    OutcomeObservationRow.profile_id == profile_id,
                ),
                unmatched_observation_count=self._count(
                    session,
                    ResolutionObservationRow,
                    ResolutionObservationRow.source_id == source_id,
                    ResolutionObservationRow.status == unmatched,
                )
                + self._count(
                    session,
                    OutcomeObservationRow,
                    OutcomeObservationRow.source_id == source_id,
                    OutcomeObservationRow.status == unmatched,
                ),
            )

    def remove_source(self, profile_id: str, source_id: str) -> DecisionIoSourceRemoval | None:
        """Delete a pushed source with its events, decisions, observations, Evidence."""
        with self._sessions.begin() as session:
            source = session.get(SourceRow, source_id)
            if (
                source is None
                or source.profile_id != profile_id
                or source.acquisition_method != AcquisitionMethod.AGENT_PUSH.value
            ):
                return None
            event_ids = select(RawEventRow.id).where(RawEventRow.source_id == source_id)
            counts = DecisionIoSourceRemoval(
                source_id=source_id,
                raw_event_count=self._count(
                    session, RawEventRow, RawEventRow.source_id == source_id
                ),
                decision_count=self._count(
                    session, DecisionEventRow, DecisionEventRow.source_id == source_id
                ),
                observation_count=self._count(
                    session,
                    ResolutionObservationRow,
                    ResolutionObservationRow.source_id == source_id,
                )
                + self._count(
                    session, OutcomeObservationRow, OutcomeObservationRow.source_id == source_id
                ),
                evidence_count=self._count(
                    session, EvidenceRow, EvidenceRow.source_event_id.in_(event_ids)
                ),
            )
            # Observations first, then decisions, so no resolution still restricts
            # the raw events that produced it.
            session.execute(
                delete(ResolutionObservationRow).where(
                    ResolutionObservationRow.source_id == source_id
                )
            )
            session.execute(
                delete(OutcomeObservationRow).where(OutcomeObservationRow.source_id == source_id)
            )
            session.execute(delete(DecisionEventRow).where(DecisionEventRow.source_id == source_id))
            session.flush()
            session.execute(delete(EvidenceRow).where(EvidenceRow.source_event_id.in_(event_ids)))
            session.execute(delete(RawEventRow).where(RawEventRow.source_id == source_id))
            session.delete(source)
            if counts.evidence_count:
                prune_unsupported_keys(session, profile_id)
                bump_evidence_revision(session, profile_id)
            return counts

    @staticmethod
    def _count(session: Session, row_type: type, *conditions: object) -> int:
        return cast(
            int,
            session.scalar(select(func.count()).select_from(row_type).where(*conditions)),  # type: ignore[arg-type]
        )

    def _replay(self, session: Session, existing: RawEventRow) -> IngestionResult:
        resolution = session.scalar(
            select(ResolutionObservationRow).where(
                ResolutionObservationRow.source_event_id == existing.id
            )
        )
        outcome = session.scalar(
            select(OutcomeObservationRow).where(
                OutcomeObservationRow.source_event_id == existing.id
            )
        )
        decision = session.scalar(
            select(DecisionEventRow).where(DecisionEventRow.source_event_id == existing.id)
        )
        status = (
            ObservationStatus(resolution.status)
            if resolution is not None
            else ObservationStatus(outcome.status)
            if outcome is not None
            else None
        )
        return IngestionResult(
            event_id=existing.id,
            duplicate=True,
            decision_id=None if decision is None else decision.id,
            resolution_observation_id=None if resolution is None else resolution.id,
            outcome_observation_id=None if outcome is None else outcome.id,
            observation_status=status,
        )


__all__ = [
    "SqliteDecisionIoRepository",
    "decision_of",
    "event_provenance_columns",
    "event_provenance_of",
    "evidence_row",
    "option_of",
    "raw_event_of",
    "source_of",
    "source_provenance_columns",
    "source_provenance_of",
]
