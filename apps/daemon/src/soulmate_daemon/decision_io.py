"""Decision I/O ingestion: classify, project, persist, and correlate one event.

The daemon assigns profile, source, actor trust, and evidence eligibility. An
external adapter only reports what it saw. See ADR-014.
"""

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from soulmate_core.decision_io import (
    POLICY_PROFILE_VERSION,
    DecisionIoError,
    DecisionIoRepository,
    EventClassification,
    IngestionResult,
    IngestionWrite,
    classify_event,
    content_fingerprint,
    may_promote_resolution,
    outcome_kind_for,
    retained_content,
)
from soulmate_core.decisions import resolution_evidence
from soulmate_core.domain import (
    AcquisitionMethod,
    AuditEvent,
    AuditEventRepository,
    AuthorScope,
    ConsentMode,
    DataClass,
    DecisionEvent,
    DecisionIoEventType,
    DecisionOption,
    DecisionOrigin,
    DecisionPurpose,
    DecisionRepository,
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
    SourceRepository,
    TechnicalOutcomeStatus,
    UserDisposition,
)

INGESTION_SENSITIVITY = "normal"
COMPATIBILITY_PROVIDER = "legacy_record_outcome"


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """The provider-neutral envelope an adapter may report."""

    source_id: str
    external_event_id: str
    event_type: DecisionIoEventType
    actor_type: EventActorType
    occurred_at: datetime
    content: dict[str, Any]
    schema_version: int = 1
    correlation_id: str | None = None
    causation_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class DecisionProjection:
    """An externally reported decision and its stable option identifiers."""

    external_decision_id: str
    domain: str
    question: str
    context: dict[str, object]
    options: tuple[tuple[str, str, str, dict[str, float]], ...]


@dataclass(frozen=True, slots=True)
class ResolutionReport:
    """A reported choice for one externally identified decision."""

    external_decision_id: str
    external_option_id: str
    disposition: UserDisposition = UserDisposition.ACCEPTED


@dataclass(frozen=True, slots=True)
class OutcomeReport:
    """A reported result; wellbeing stays unconfirmed until the owner says so."""

    external_decision_id: str
    technical_status: TechnicalOutcomeStatus | None = None
    disposition: UserDisposition | None = None
    satisfaction: float | None = None
    regret: bool | None = None


@dataclass(frozen=True, slots=True)
class PromotedResolution:
    """What the daemon promoted to the canonical decision path, if anything."""

    decision_id: str
    chosen_option_id: str


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """The stored result plus the promotion the daemon allowed."""

    result: IngestionResult
    classification: EventClassification
    promoted: PromotedResolution | None = None


def _reported_payload(
    envelope: EventEnvelope,
    decision: DecisionProjection | None,
    resolution: ResolutionReport | None,
    outcome: OutcomeReport | None,
) -> dict[str, Any]:
    """Everything the adapter reported, so a changed projection is a conflict."""
    return {
        "event_type": envelope.event_type.value,
        "actor_type": envelope.actor_type.value,
        "occurred_at": envelope.occurred_at.isoformat(),
        "schema_version": envelope.schema_version,
        "correlation_id": envelope.correlation_id,
        "causation_event_id": envelope.causation_event_id,
        "content": envelope.content,
        "decision": None if decision is None else asdict(decision),
        "resolution": None if resolution is None else asdict(resolution),
        "outcome": None if outcome is None else asdict(outcome),
    }


class DecisionIoService:
    """Validate, classify, and atomically persist one reported event."""

    def __init__(
        self,
        *,
        sources: SourceRepository,
        decision_io: DecisionIoRepository,
        decisions: DecisionRepository,
        audits: AuditEventRepository,
    ) -> None:
        self._sources = sources
        self._decision_io = decision_io
        self._decisions = decisions
        self._audits = audits

    def ingestible_source(
        self, profile_id: str, source_id: str, service_identity_id: str | None
    ) -> Source:
        """Return the owner-approved source this identity may write, or refuse."""
        source = self._sources.get(source_id)
        if source is None or source.profile_id != profile_id:
            raise DecisionIoError("source_not_found", "The source was not found.")
        provenance = source.provenance
        if provenance.acquisition_method is not AcquisitionMethod.AGENT_PUSH:
            raise DecisionIoError(
                "source_not_ingestible", "The source is not approved for pushed events."
            )
        if service_identity_id is None or provenance.service_identity_id != service_identity_id:
            raise DecisionIoError(
                "source_identity_mismatch",
                "The source belongs to another service identity.",
            )
        return source

    def compatibility_source(
        self, profile_id: str, service_identity_id: str, identity_name: str, now: datetime
    ) -> Source:
        """Find or create the source that represents one identity's legacy writes.

        The owner approved this identity and its scope, so its reports are stored
        with provenance instead of being written as if the owner had made them.
        """
        source_type = f"agent:{COMPATIBILITY_PROVIDER}"
        existing = next(
            (
                item
                for item in self._sources.list_for_profile(profile_id)
                if item.source_type == source_type
                and item.provenance.service_identity_id == service_identity_id
            ),
            None,
        )
        if existing is not None:
            return existing
        source = Source(
            id=f"source_{uuid4().hex}",
            profile_id=profile_id,
            source_type=source_type,
            name=f"{identity_name} (compatibility)",
            created_at=now,
            provenance=SourceProvenance(
                provider=COMPATIBILITY_PROVIDER,
                acquisition_method=AcquisitionMethod.AGENT_PUSH,
                consent_mode=ConsentMode.OWNER_IMPLICIT,
                consent_at=now,
                data_classes=(DataClass.OUTCOME,),
                author_scope=AuthorScope.AGENT_ONLY,
                raw_retention_policy=RawRetentionPolicy.STRUCTURED_ONLY,
                policy_profile_version=POLICY_PROFILE_VERSION,
                service_identity_id=service_identity_id,
            ),
        )
        self._sources.add(source)
        return source

    def record_reported_wellbeing(
        self,
        *,
        profile_id: str,
        source: Source,
        decision_id: str,
        satisfaction: float,
        regret: bool,
        notes: str | None,
        now: datetime | None = None,
    ) -> IngestionResult:
        """Store a legacy external outcome report as an unconfirmed observation.

        Only an owner confirmation turns this into `DecisionOutcome` wellbeing.
        """
        ingested_at = datetime.now(UTC) if now is None else now
        content: dict[str, Any] = {
            "decision_id": decision_id,
            "satisfaction": satisfaction,
            "regret": regret,
            "notes": notes,
        }
        event = RawEvent(
            id=f"event_{uuid4().hex}",
            profile_id=profile_id,
            source_id=source.id,
            event_type=DecisionIoEventType.USER_OUTCOME.value,
            content=content,
            created_at=ingested_at,
            ingested_at=ingested_at,
            sensitivity=INGESTION_SENSITIVITY,
            provenance=EventProvenance(
                external_event_id=f"legacy_outcome:{decision_id}",
                actor_type=EventActorType.AGENT,
                evidence_eligibility=EvidenceEligibility.CONTEXTUAL_ONLY,
                content_fingerprint=content_fingerprint(content),
            ),
        )
        observation = OutcomeObservation(
            id=f"outcome_observation_{uuid4().hex}",
            profile_id=profile_id,
            source_id=source.id,
            source_event_id=event.id,
            kind=OutcomeKind.OWNER_REPORTED,
            actor_type=EventActorType.AGENT,
            status=ObservationStatus.PENDING,
            created_at=ingested_at,
            decision_id=decision_id,
            satisfaction=satisfaction,
            regret=regret,
            reason_code="awaiting_owner_confirmation",
        )
        result = self._decision_io.ingest(
            IngestionWrite(event=event, outcome_observation=observation)
        )
        self._audits.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                profile_id=profile_id,
                action="decision_io.wellbeing_observed",
                actor_type="service",
                actor_id=source.provenance.service_identity_id,
                metadata={
                    "source_id": source.id,
                    "decision_id": decision_id,
                    "duplicate": result.duplicate,
                    "status": ObservationStatus.PENDING.value,
                },
                created_at=ingested_at,
            )
        )
        return result

    def record_event(
        self,
        *,
        profile_id: str,
        service_identity_id: str | None,
        envelope: EventEnvelope,
        decision: DecisionProjection | None = None,
        resolution: ResolutionReport | None = None,
        outcome: OutcomeReport | None = None,
        now: datetime | None = None,
    ) -> IngestionOutcome:
        source = self.ingestible_source(profile_id, envelope.source_id, service_identity_id)
        classification = classify_event(
            provenance=source.provenance,
            event_type=envelope.event_type,
            reported_actor=envelope.actor_type,
            schema_version=envelope.schema_version,
            content=envelope.content,
            occurred_at=envelope.occurred_at,
            external_event_id=envelope.external_event_id,
        )
        ingested_at = datetime.now(UTC) if now is None else now
        event = RawEvent(
            id=f"event_{uuid4().hex}",
            profile_id=profile_id,
            source_id=source.id,
            event_type=envelope.event_type.value,
            content=retained_content(source.provenance.raw_retention_policy, envelope.content),
            created_at=envelope.occurred_at,
            ingested_at=ingested_at,
            sensitivity=INGESTION_SENSITIVITY,
            provenance=EventProvenance(
                schema_version=envelope.schema_version,
                external_event_id=envelope.external_event_id.strip(),
                actor_type=classification.actor_type,
                evidence_eligibility=classification.eligibility,
                correlation_id=envelope.correlation_id,
                causation_event_id=envelope.causation_event_id,
                content_fingerprint=content_fingerprint(
                    _reported_payload(envelope, decision, resolution, outcome)
                ),
            ),
        )
        projected = None if decision is None else self._project(profile_id, source, event, decision)
        stored_decision = self._existing_decision(
            profile_id,
            source.id,
            self._referenced_decision_id(decision, resolution, outcome),
        )
        observation = (
            None
            if resolution is None
            else self._resolution_observation(
                profile_id, source, event, classification, resolution, stored_decision
            )
        )
        promotion = (
            None
            if observation is None or stored_decision is None
            else self._promotion_records(observation, stored_decision, event.ingested_at)
        )
        write = IngestionWrite(
            event=event,
            decision=projected,
            resolution_observation=observation,
            outcome_observation=(
                None
                if outcome is None
                else self._outcome_observation(
                    profile_id, source, event, classification, outcome, stored_decision
                )
            ),
            resolution=None if promotion is None else promotion[0],
            evidence=() if promotion is None else promotion[1],
        )
        result = self._decision_io.ingest(write)
        promoted = (
            None
            if result.duplicate or write.resolution is None
            else PromotedResolution(write.resolution.decision_id, write.resolution.chosen_option_id)
        )
        self._audit(profile_id, source, event, classification, result, promoted)
        return IngestionOutcome(result=result, classification=classification, promoted=promoted)

    def _project(
        self,
        profile_id: str,
        source: Source,
        event: RawEvent,
        decision: DecisionProjection,
    ) -> tuple[DecisionEvent, tuple[DecisionOption, ...]]:
        if len(decision.options) < 2:
            raise DecisionIoError(
                "decision_options_invalid", "A decision requires at least two options."
            )
        external_ids = [item[0] for item in decision.options]
        if len(set(external_ids)) != len(external_ids):
            raise DecisionIoError("decision_options_invalid", "External option IDs must be unique.")
        decision_id = f"decision_{uuid4().hex}"
        try:
            record = DecisionEvent(
                id=decision_id,
                profile_id=profile_id,
                domain=decision.domain,
                question=decision.question,
                context=decision.context,
                status=DecisionStatus.OPEN,
                created_at=event.created_at,
                origin=DecisionOrigin.EXTERNAL_SERVICE,
                purpose=DecisionPurpose.OBSERVED,
                source_id=source.id,
                external_decision_id=decision.external_decision_id,
                source_event_id=event.id,
            )
            options = tuple(
                DecisionOption(
                    id=f"option_{uuid4().hex}",
                    decision_id=decision_id,
                    label=label,
                    description=description,
                    features=features,
                    feature_confidence=1.0,
                    external_option_id=external_id,
                )
                for external_id, label, description, features in decision.options
            )
        except ValueError as error:
            raise DecisionIoError("decision_invalid", str(error)) from error
        return record, options

    def _existing_decision(
        self, profile_id: str, source_id: str, external_decision_id: str | None
    ) -> tuple[DecisionEvent, tuple[DecisionOption, ...]] | None:
        if external_decision_id is None:
            return None
        return self._decision_io.find_decision_by_external_id(
            profile_id, source_id, external_decision_id
        )

    @staticmethod
    def _referenced_decision_id(
        decision: DecisionProjection | None,
        resolution: ResolutionReport | None,
        outcome: OutcomeReport | None,
    ) -> str | None:
        if resolution is not None:
            return resolution.external_decision_id
        if outcome is not None:
            return outcome.external_decision_id
        return None if decision is None else decision.external_decision_id

    def _resolution_observation(
        self,
        profile_id: str,
        source: Source,
        event: RawEvent,
        classification: EventClassification,
        report: ResolutionReport,
        stored: tuple[DecisionEvent, tuple[DecisionOption, ...]] | None,
    ) -> ResolutionObservation:
        decision_id = None if stored is None else stored[0].id
        chosen = (
            None
            if stored is None
            else next(
                (
                    item.id
                    for item in stored[1]
                    if item.external_option_id == report.external_option_id
                ),
                None,
            )
        )
        if stored is not None and chosen is None:
            raise DecisionIoError(
                "option_not_found", "The reported option does not belong to that decision."
            )
        already_resolved = stored is not None and stored[0].status is DecisionStatus.RESOLVED
        confirmed = (
            decision_id is not None
            and not already_resolved
            and may_promote_resolution(classification)
        )
        status = (
            ObservationStatus.CONFIRMED
            if confirmed
            else ObservationStatus.PENDING
            if decision_id is not None
            else ObservationStatus.UNMATCHED
        )
        reason = (
            "owner_choice_promoted"
            if confirmed
            else "decision_already_resolved"
            if already_resolved
            else "awaiting_owner_confirmation"
        )
        return ResolutionObservation(
            id=f"resolution_observation_{uuid4().hex}",
            profile_id=profile_id,
            source_id=source.id,
            source_event_id=event.id,
            actor_type=classification.actor_type,
            status=status,
            disposition=report.disposition,
            created_at=event.ingested_at,
            decision_id=decision_id,
            external_decision_id=report.external_decision_id,
            chosen_option_id=chosen,
            external_option_id=report.external_option_id,
            correlation_confidence=None if decision_id is None else 1.0,
            confirmed_at=event.ingested_at if confirmed else None,
            reason_code=reason,
        )

    def _outcome_observation(
        self,
        profile_id: str,
        source: Source,
        event: RawEvent,
        classification: EventClassification,
        report: OutcomeReport,
        stored: tuple[DecisionEvent, tuple[DecisionOption, ...]] | None,
    ) -> OutcomeObservation:
        kind = outcome_kind_for(classification.event_type)
        if kind is OutcomeKind.TECHNICAL and report.technical_status is None:
            raise DecisionIoError(
                "technical_status_required", "A technical outcome must report its status."
            )
        if kind is OutcomeKind.USER_BEHAVIOR and report.disposition is None:
            raise DecisionIoError(
                "disposition_required", "A user outcome must report what the owner did."
            )
        if report.satisfaction is not None or report.regret is not None:
            raise DecisionIoError(
                "wellbeing_not_reportable",
                "Satisfaction and regret require an owner confirmation.",
            )
        decision_id = None if stored is None else stored[0].id
        return OutcomeObservation(
            id=f"outcome_observation_{uuid4().hex}",
            profile_id=profile_id,
            source_id=source.id,
            source_event_id=event.id,
            kind=kind,
            actor_type=classification.actor_type,
            status=(
                ObservationStatus.PENDING
                if decision_id is not None
                else ObservationStatus.UNMATCHED
            ),
            created_at=event.ingested_at,
            decision_id=decision_id,
            external_decision_id=report.external_decision_id,
            technical_status=report.technical_status if kind is OutcomeKind.TECHNICAL else None,
            disposition=report.disposition if kind is OutcomeKind.USER_BEHAVIOR else None,
            reason_code="observed_only",
        )

    @staticmethod
    def _promotion_records(
        observation: ResolutionObservation,
        stored: tuple[DecisionEvent, tuple[DecisionOption, ...]],
        now: datetime,
    ) -> tuple[DecisionResolution, tuple[Evidence, ...]] | None:
        """Build the canonical resolution and choice Evidence for a confirmed choice."""
        if observation.status is not ObservationStatus.CONFIRMED:
            return None
        if observation.chosen_option_id is None:
            return None
        decision, options = stored
        record = DecisionResolution(
            id=f"resolution_{uuid4().hex}",
            decision_id=decision.id,
            chosen_option_id=observation.chosen_option_id,
            source_event_id=observation.source_event_id,
            created_at=now,
        )
        return record, resolution_evidence(
            resolution=record,
            decision=decision,
            options=options,
            profile_id=decision.profile_id,
            created_at=now,
        )

    def confirm_resolution(
        self, profile_id: str, observation_id: str, now: datetime | None = None
    ) -> PromotedResolution:
        """Apply the owner's confirmation of a reported choice exactly once."""
        observation = self._decision_io.get_resolution_observation(profile_id, observation_id)
        if observation is None:
            raise DecisionIoError("observation_not_found", "The observation was not found.")
        if observation.status is not ObservationStatus.PENDING or observation.decision_id is None:
            raise DecisionIoError(
                "observation_not_confirmable", "Only a matched, pending choice can be confirmed."
            )
        stored = self._decisions.get(observation.decision_id)
        if stored is None or stored[0].profile_id != profile_id:
            raise DecisionIoError("decision_not_found", "The decision was not found.")
        if stored[0].status is DecisionStatus.RESOLVED:
            raise DecisionIoError(
                "decision_already_resolved", "The decision has already been resolved."
            )
        confirmed_at = datetime.now(UTC) if now is None else now
        records = self._promotion_records(
            replace(observation, status=ObservationStatus.CONFIRMED, confirmed_at=confirmed_at),
            stored,
            confirmed_at,
        )
        if records is None or not self._decision_io.confirm_resolution_observation(
            observation.id, ObservationStatus.PENDING, records[0], records[1], confirmed_at
        ):
            raise DecisionIoError(
                "observation_state_changed", "The observation state changed before review."
            )
        return PromotedResolution(records[0].decision_id, records[0].chosen_option_id)

    def _audit(
        self,
        profile_id: str,
        source: Source,
        event: RawEvent,
        classification: EventClassification,
        result: IngestionResult,
        promoted: PromotedResolution | None,
    ) -> None:
        """Record identifiers, counts, and reason codes only; never event content."""
        self._audits.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                profile_id=profile_id,
                action="decision_io.ingest",
                actor_type="service",
                actor_id=source.provenance.service_identity_id,
                metadata={
                    "source_id": source.id,
                    "event_type": classification.event_type.value,
                    "actor_type": classification.actor_type.value,
                    "evidence_eligibility": classification.eligibility.value,
                    "policy_profile_version": classification.policy_profile_version,
                    "duplicate": result.duplicate,
                    "promoted": promoted is not None,
                    "schema_version": event.provenance.schema_version,
                },
                created_at=event.ingested_at,
            )
        )


__all__ = [
    "DecisionIoService",
    "DecisionProjection",
    "EventEnvelope",
    "IngestionOutcome",
    "OutcomeReport",
    "PromotedResolution",
    "ResolutionReport",
]
