"""SQLAlchemy implementations of Soulmate repository ports."""

import json
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from soulmate_connector_sdk import (
    ConnectorPermission,
    ConnectorRegistration,
    ConnectorRemoval,
    ConnectorSyncStatus,
    PersistedConnectorEvent,
    StoredSyncResult,
)
from soulmate_core.domain.models import (
    ActiveQuestion,
    ActiveQuestionStatus,
    AdviceRankingItem,
    ApiCredential,
    AuditEvent,
    Constraint,
    Conversation,
    DecisionAdvice,
    DecisionEvent,
    DecisionImpact,
    DecisionOption,
    DecisionOutcome,
    DecisionPrediction,
    DecisionResolution,
    DecisionStatus,
    DelegationPolicy,
    DelegationRequest,
    DelegationStatus,
    DerivedModel,
    Evidence,
    EvidenceTargetType,
    Fact,
    Goal,
    Job,
    JobStatus,
    Message,
    MessageRole,
    OptionProbability,
    PairedDevice,
    PairingToken,
    Preference,
    Profile,
    QuestionAnswer,
    RawEvent,
    ServiceIdentity,
    Source,
    SourceDeletion,
    UserModelSnapshot,
)
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from soulmate_storage_sqlite.key_aliases import (
    SqliteTargetKeyAliasRepository,
    bump_evidence_revision,
    prune_unsupported_keys,
)
from soulmate_storage_sqlite.key_metadata import (
    SqliteTargetKeyCatalogRepository,
    SqliteTargetKeyEmbeddingRepository,
)
from soulmate_storage_sqlite.schema import (
    ActiveQuestionRow,
    ApiCredentialRow,
    AuditEventRow,
    ConnectorItemRow,
    ConnectorRegistrationRow,
    ConstraintRow,
    ConversationRow,
    DecisionAdviceRow,
    DecisionEventRow,
    DecisionOptionRow,
    DecisionOutcomeRow,
    DecisionPredictionRow,
    DecisionResolutionRow,
    DelegationPolicyRow,
    DelegationRequestRow,
    EvidenceRevisionRow,
    EvidenceRow,
    FactRow,
    GoalRow,
    JobRow,
    MessageRow,
    PairedDeviceRow,
    PairingTokenRow,
    PreferenceRow,
    ProfileRow,
    QuestionAnswerRow,
    RawEventRow,
    ServiceIdentityRow,
    ServiceIdentityScopeRow,
    SourceRow,
    SystemMetadataRow,
    UserModelSnapshotRow,
)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqliteProfileRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, profile: Profile) -> None:
        with self._sessions.begin() as session:
            session.add(
                ProfileRow(
                    id=profile.id,
                    display_name=profile.display_name,
                    created_at=profile.created_at,
                )
            )

    def get(self, profile_id: str) -> Profile | None:
        with self._sessions() as session:
            row = session.get(ProfileRow, profile_id)
            if row is None:
                return None
            return Profile(row.id, row.display_name, _utc(row.created_at))


class SqliteSourceRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, source: Source) -> None:
        with self._sessions.begin() as session:
            session.add(
                SourceRow(
                    id=source.id,
                    profile_id=source.profile_id,
                    source_type=source.source_type,
                    name=source.name,
                    created_at=source.created_at,
                )
            )

    def get(self, source_id: str) -> Source | None:
        with self._sessions() as session:
            row = session.get(SourceRow, source_id)
            if row is None:
                return None
            return Source(row.id, row.profile_id, row.source_type, row.name, _utc(row.created_at))

    def list_for_profile(self, profile_id: str) -> tuple[Source, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(SourceRow)
                .where(SourceRow.profile_id == profile_id)
                .order_by(SourceRow.created_at.desc(), SourceRow.id.desc())
            )
            return tuple(
                Source(row.id, row.profile_id, row.source_type, row.name, _utc(row.created_at))
                for row in rows
            )

    def add_import(
        self,
        source: Source,
        conversations: tuple[Conversation, ...],
        messages: tuple[Message, ...],
        events: tuple[RawEvent, ...],
    ) -> None:
        conversation_ids = {item.id for item in conversations}
        if (
            not source.source_type.startswith("import:")
            or any(
                item.profile_id != source.profile_id or item.source_id != source.id
                for item in conversations
            )
            or any(item.conversation_id not in conversation_ids for item in messages)
            or any(
                item.profile_id != source.profile_id or item.source_id != source.id
                for item in events
            )
        ):
            raise ValueError("Imported records must belong to one import source and profile.")
        with self._sessions.begin() as session:
            session.add(
                SourceRow(
                    id=source.id,
                    profile_id=source.profile_id,
                    source_type=source.source_type,
                    name=source.name,
                    created_at=source.created_at,
                )
            )
            session.flush()
            session.add_all(
                ConversationRow(
                    id=item.id,
                    profile_id=item.profile_id,
                    source_id=item.source_id,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in conversations
            )
            session.flush()
            session.add_all(
                MessageRow(
                    id=item.id,
                    conversation_id=item.conversation_id,
                    role=item.role.value,
                    content=item.content,
                    provider_model=item.provider_model,
                    created_at=item.created_at,
                )
                for item in messages
            )
            session.add_all(
                RawEventRow(
                    id=item.id,
                    profile_id=item.profile_id,
                    source_id=item.source_id,
                    event_type=item.event_type,
                    content_json=_json_dump(item.content),
                    created_at=item.created_at,
                    ingested_at=item.ingested_at,
                    sensitivity=item.sensitivity,
                )
                for item in events
            )

    def remove_import(self, profile_id: str, source_id: str) -> SourceDeletion | None:
        with self._sessions.begin() as session:
            source = session.get(SourceRow, source_id)
            if (
                source is None
                or source.profile_id != profile_id
                or not source.source_type.startswith("import:")
            ):
                return None
            event_ids = select(RawEventRow.id).where(RawEventRow.source_id == source_id)
            conversation_ids = select(ConversationRow.id).where(
                ConversationRow.source_id == source_id
            )
            evidence_filter = or_(
                EvidenceRow.source_event_id.in_(event_ids),
                EvidenceRow.source_message_id.in_(
                    select(MessageRow.id).where(MessageRow.conversation_id.in_(conversation_ids))
                ),
            )
            counts = SourceDeletion(
                source_id=source_id,
                raw_event_count=cast(
                    int,
                    session.scalar(
                        select(func.count())
                        .select_from(RawEventRow)
                        .where(RawEventRow.source_id == source_id)
                    ),
                ),
                conversation_count=cast(
                    int,
                    session.scalar(
                        select(func.count())
                        .select_from(ConversationRow)
                        .where(ConversationRow.source_id == source_id)
                    ),
                ),
                message_count=cast(
                    int,
                    session.scalar(
                        select(func.count())
                        .select_from(MessageRow)
                        .where(MessageRow.conversation_id.in_(conversation_ids))
                    ),
                ),
                evidence_count=cast(
                    int,
                    session.scalar(
                        select(func.count()).select_from(EvidenceRow).where(evidence_filter)
                    ),
                ),
            )
            session.execute(delete(EvidenceRow).where(evidence_filter))
            session.execute(delete(RawEventRow).where(RawEventRow.source_id == source_id))
            session.execute(delete(ConversationRow).where(ConversationRow.source_id == source_id))
            session.delete(source)
            if counts.evidence_count:
                prune_unsupported_keys(session, profile_id)
                bump_evidence_revision(session, profile_id)
            return counts


class SqliteRawEventRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, event: RawEvent) -> None:
        with self._sessions.begin() as session:
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
                )
            )

    def get(self, event_id: str) -> RawEvent | None:
        with self._sessions() as session:
            row = session.get(RawEventRow, event_id)
            if row is None:
                return None
            return RawEvent(
                id=row.id,
                profile_id=row.profile_id,
                source_id=row.source_id,
                event_type=row.event_type,
                content=json.loads(row.content_json),
                created_at=_utc(row.created_at),
                ingested_at=_utc(row.ingested_at),
                sensitivity=row.sensitivity,
            )


class SqliteConversationRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, conversation: Conversation) -> None:
        with self._sessions.begin() as session:
            session.add(
                ConversationRow(
                    id=conversation.id,
                    profile_id=conversation.profile_id,
                    source_id=conversation.source_id,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                )
            )

    def get(self, conversation_id: str) -> Conversation | None:
        with self._sessions() as session:
            row = session.get(ConversationRow, conversation_id)
            if row is None:
                return None
            return Conversation(
                row.id,
                row.profile_id,
                _utc(row.created_at),
                _utc(row.updated_at),
                row.source_id,
            )

    def list_for_profile(self, profile_id: str) -> tuple[Conversation, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ConversationRow)
                .where(ConversationRow.profile_id == profile_id)
                .order_by(ConversationRow.updated_at.desc(), ConversationRow.id.desc())
            )
            return tuple(
                Conversation(
                    row.id,
                    row.profile_id,
                    _utc(row.created_at),
                    _utc(row.updated_at),
                    row.source_id,
                )
                for row in rows
            )

    def touch(self, conversation_id: str, updated_at: datetime) -> None:
        with self._sessions.begin() as session:
            updated_id = session.execute(
                update(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .values(updated_at=updated_at)
                .returning(ConversationRow.id)
            ).scalar_one_or_none()
            if updated_id is None:
                raise KeyError(conversation_id)


class SqliteMessageRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, message: Message) -> None:
        with self._sessions.begin() as session:
            session.add(
                MessageRow(
                    id=message.id,
                    conversation_id=message.conversation_id,
                    role=message.role.value,
                    content=message.content,
                    provider_model=message.provider_model,
                    created_at=message.created_at,
                )
            )

    def get(self, message_id: str) -> Message | None:
        with self._sessions() as session:
            row = session.get(MessageRow, message_id)
            return None if row is None else self._to_domain(row)

    def list_for_conversation(self, conversation_id: str) -> tuple[Message, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.created_at, MessageRow.id)
            )
            return tuple(self._to_domain(row) for row in rows)

    @staticmethod
    def _to_domain(row: MessageRow) -> Message:
        return Message(
            id=row.id,
            conversation_id=row.conversation_id,
            role=MessageRole(row.role),
            content=row.content,
            provider_model=row.provider_model,
            created_at=_utc(row.created_at),
        )


class SqliteDecisionRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, decision: DecisionEvent, options: tuple[DecisionOption, ...]) -> None:
        if len(options) < 2 or any(item.decision_id != decision.id for item in options):
            raise ValueError("A decision requires at least two options belonging to it.")
        with self._sessions.begin() as session:
            session.add(
                DecisionEventRow(
                    id=decision.id,
                    profile_id=decision.profile_id,
                    domain=decision.domain,
                    question=decision.question,
                    context_json=_json_dump(decision.context),
                    status=decision.status.value,
                    created_at=decision.created_at,
                )
            )
            session.add_all(
                DecisionOptionRow(
                    id=item.id,
                    decision_id=item.decision_id,
                    label=item.label,
                    description=item.description,
                    features_json=_json_dump(item.features),
                    feature_confidence=item.feature_confidence,
                )
                for item in options
            )

    def get(self, decision_id: str) -> tuple[DecisionEvent, tuple[DecisionOption, ...]] | None:
        with self._sessions() as session:
            row = session.get(DecisionEventRow, decision_id)
            if row is None:
                return None
            options = session.scalars(
                select(DecisionOptionRow)
                .where(DecisionOptionRow.decision_id == decision_id)
                .order_by(DecisionOptionRow.id)
            )
            return self._event_to_domain(row), tuple(
                self._option_to_domain(item) for item in options
            )

    def list_for_profile(
        self, profile_id: str
    ) -> tuple[tuple[DecisionEvent, tuple[DecisionOption, ...]], ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DecisionEventRow)
                .where(DecisionEventRow.profile_id == profile_id)
                .order_by(DecisionEventRow.created_at.desc(), DecisionEventRow.id.desc())
            )
            result = []
            for row in rows:
                options = session.scalars(
                    select(DecisionOptionRow)
                    .where(DecisionOptionRow.decision_id == row.id)
                    .order_by(DecisionOptionRow.id)
                )
                result.append(
                    (
                        self._event_to_domain(row),
                        tuple(self._option_to_domain(item) for item in options),
                    )
                )
            return tuple(result)

    def list_resolved(
        self, profile_id: str
    ) -> tuple[tuple[DecisionEvent, tuple[DecisionOption, ...], DecisionResolution], ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DecisionEventRow)
                .where(
                    DecisionEventRow.profile_id == profile_id,
                    DecisionEventRow.status == DecisionStatus.RESOLVED.value,
                )
                .order_by(DecisionEventRow.created_at, DecisionEventRow.id)
            )
            result = []
            for row in rows:
                options = session.scalars(
                    select(DecisionOptionRow)
                    .where(DecisionOptionRow.decision_id == row.id)
                    .order_by(DecisionOptionRow.id)
                )
                resolution = session.scalar(
                    select(DecisionResolutionRow).where(DecisionResolutionRow.decision_id == row.id)
                )
                if resolution is None:
                    raise RuntimeError("Resolved decision is missing its resolution.")
                result.append(
                    (
                        self._event_to_domain(row),
                        tuple(self._option_to_domain(item) for item in options),
                        self._resolution_to_domain(resolution),
                    )
                )
            return tuple(result)

    def add_prediction(self, prediction: DecisionPrediction) -> None:
        with self._sessions.begin() as session:
            decision = session.get(DecisionEventRow, prediction.decision_id)
            if decision is None or decision.profile_id != prediction.profile_id:
                raise ValueError("Prediction must belong to the decision profile.")
            session.add(
                DecisionPredictionRow(
                    id=prediction.id,
                    decision_id=prediction.decision_id,
                    profile_id=prediction.profile_id,
                    ranking_json=_json_dump(
                        [
                            {
                                "option_id": item.option_id,
                                "probability": item.probability,
                                "utility": item.utility,
                            }
                            for item in prediction.ranking
                        ]
                    ),
                    confidence=prediction.confidence,
                    important_factors_json=_json_dump(prediction.important_factors),
                    uncertain_factors_json=_json_dump(prediction.uncertain_factors),
                    supporting_evidence_ids_json=_json_dump(prediction.supporting_evidence_ids),
                    similar_decision_ids_json=_json_dump(prediction.similar_decision_ids),
                    model_snapshot_version=prediction.model_snapshot_version,
                    algorithm_version=prediction.algorithm_version,
                    created_at=prediction.created_at,
                )
            )

    def latest_prediction(self, decision_id: str) -> DecisionPrediction | None:
        with self._sessions() as session:
            row = session.scalar(
                select(DecisionPredictionRow)
                .where(DecisionPredictionRow.decision_id == decision_id)
                .order_by(DecisionPredictionRow.created_at.desc(), DecisionPredictionRow.id.desc())
                .limit(1)
            )
            return None if row is None else self._prediction_to_domain(row)

    def resolve(self, resolution: DecisionResolution) -> None:
        with self._sessions.begin() as session:
            decision = session.get(DecisionEventRow, resolution.decision_id)
            option = session.get(DecisionOptionRow, resolution.chosen_option_id)
            if decision is None or option is None or option.decision_id != resolution.decision_id:
                raise ValueError("Resolution option must belong to the decision.")
            if decision.status != DecisionStatus.OPEN.value:
                raise ValueError("Decision has already been resolved.")
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

    def get_resolution(self, decision_id: str) -> DecisionResolution | None:
        with self._sessions() as session:
            row = session.scalar(
                select(DecisionResolutionRow).where(
                    DecisionResolutionRow.decision_id == decision_id
                )
            )
            return None if row is None else self._resolution_to_domain(row)

    def add_advice(self, advice: DecisionAdvice) -> None:
        with self._sessions.begin() as session:
            decision = session.get(DecisionEventRow, advice.decision_id)
            if decision is None or decision.profile_id != advice.profile_id:
                raise ValueError("Advice must belong to the decision profile.")
            session.add(
                DecisionAdviceRow(
                    id=advice.id,
                    decision_id=advice.decision_id,
                    profile_id=advice.profile_id,
                    behavioral_prediction_id=advice.behavioral_prediction_id,
                    ranking_json=_json_dump(
                        [
                            {
                                "option_id": item.option_id,
                                "recommendation_score": item.recommendation_score,
                                "behavioral_probability": item.behavioral_probability,
                                "wellbeing_score": item.wellbeing_score,
                                "goal_alignment": item.goal_alignment,
                            }
                            for item in advice.ranking
                        ]
                    ),
                    confidence=advice.confidence,
                    rationale_json=_json_dump(advice.rationale),
                    supporting_outcome_ids_json=_json_dump(advice.supporting_outcome_ids),
                    model_snapshot_version=advice.model_snapshot_version,
                    algorithm_version=advice.algorithm_version,
                    created_at=advice.created_at,
                )
            )

    def latest_advice(self, decision_id: str) -> DecisionAdvice | None:
        with self._sessions() as session:
            row = session.scalar(
                select(DecisionAdviceRow)
                .where(DecisionAdviceRow.decision_id == decision_id)
                .order_by(DecisionAdviceRow.created_at.desc(), DecisionAdviceRow.id.desc())
                .limit(1)
            )
            return None if row is None else self._advice_to_domain(row)

    @staticmethod
    def _event_to_domain(row: DecisionEventRow) -> DecisionEvent:
        return DecisionEvent(
            id=row.id,
            profile_id=row.profile_id,
            domain=row.domain,
            question=row.question,
            context=json.loads(row.context_json),
            status=DecisionStatus(row.status),
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _option_to_domain(row: DecisionOptionRow) -> DecisionOption:
        return DecisionOption(
            id=row.id,
            decision_id=row.decision_id,
            label=row.label,
            description=row.description,
            features=json.loads(row.features_json),
            feature_confidence=row.feature_confidence,
        )

    @staticmethod
    def _prediction_to_domain(row: DecisionPredictionRow) -> DecisionPrediction:
        ranking = cast(list[dict[str, object]], json.loads(row.ranking_json))
        return DecisionPrediction(
            id=row.id,
            decision_id=row.decision_id,
            profile_id=row.profile_id,
            ranking=tuple(
                OptionProbability(
                    option_id=str(item["option_id"]),
                    probability=cast(float, item["probability"]),
                    utility=cast(float, item["utility"]),
                )
                for item in ranking
            ),
            confidence=row.confidence,
            important_factors=tuple(json.loads(row.important_factors_json)),
            uncertain_factors=tuple(json.loads(row.uncertain_factors_json)),
            supporting_evidence_ids=tuple(json.loads(row.supporting_evidence_ids_json)),
            similar_decision_ids=tuple(json.loads(row.similar_decision_ids_json)),
            model_snapshot_version=row.model_snapshot_version,
            algorithm_version=row.algorithm_version,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _resolution_to_domain(row: DecisionResolutionRow) -> DecisionResolution:
        return DecisionResolution(
            id=row.id,
            decision_id=row.decision_id,
            chosen_option_id=row.chosen_option_id,
            source_event_id=row.source_event_id,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _advice_to_domain(row: DecisionAdviceRow) -> DecisionAdvice:
        ranking = cast(list[dict[str, object]], json.loads(row.ranking_json))
        return DecisionAdvice(
            id=row.id,
            decision_id=row.decision_id,
            profile_id=row.profile_id,
            behavioral_prediction_id=row.behavioral_prediction_id,
            ranking=tuple(
                AdviceRankingItem(
                    option_id=str(item["option_id"]),
                    recommendation_score=cast(float, item["recommendation_score"]),
                    behavioral_probability=cast(float, item["behavioral_probability"]),
                    wellbeing_score=cast(float | None, item["wellbeing_score"]),
                    goal_alignment=cast(float | None, item["goal_alignment"]),
                )
                for item in ranking
            ),
            confidence=row.confidence,
            rationale=tuple(json.loads(row.rationale_json)),
            supporting_outcome_ids=tuple(json.loads(row.supporting_outcome_ids_json)),
            model_snapshot_version=row.model_snapshot_version,
            algorithm_version=row.algorithm_version,
            created_at=_utc(row.created_at),
        )


class SqliteOutcomeRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, outcome: DecisionOutcome) -> None:
        with self._sessions.begin() as session:
            decision = session.get(DecisionEventRow, outcome.decision_id)
            if decision is None or decision.profile_id != outcome.profile_id:
                raise ValueError("Outcome must belong to the decision profile.")
            session.add(
                DecisionOutcomeRow(
                    id=outcome.id,
                    decision_id=outcome.decision_id,
                    profile_id=outcome.profile_id,
                    satisfaction=outcome.satisfaction,
                    regret=outcome.regret,
                    notes=outcome.notes,
                    source_event_id=outcome.source_event_id,
                    created_at=outcome.created_at,
                )
            )

    def get_for_decision(self, decision_id: str) -> DecisionOutcome | None:
        with self._sessions() as session:
            row = session.scalar(
                select(DecisionOutcomeRow).where(DecisionOutcomeRow.decision_id == decision_id)
            )
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[DecisionOutcome, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DecisionOutcomeRow)
                .where(DecisionOutcomeRow.profile_id == profile_id)
                .order_by(DecisionOutcomeRow.created_at, DecisionOutcomeRow.id)
            )
            return tuple(self._to_domain(row) for row in rows)

    def remove_for_decision(self, decision_id: str) -> bool:
        with self._sessions.begin() as session:
            outcome = session.scalar(
                select(DecisionOutcomeRow).where(DecisionOutcomeRow.decision_id == decision_id)
            )
            if outcome is None:
                return False
            source_event_id = outcome.source_event_id
            session.execute(
                delete(DecisionAdviceRow).where(DecisionAdviceRow.profile_id == outcome.profile_id)
            )
            session.delete(outcome)
            session.flush()
            session.execute(delete(RawEventRow).where(RawEventRow.id == source_event_id))
            return True

    @staticmethod
    def _to_domain(row: DecisionOutcomeRow) -> DecisionOutcome:
        return DecisionOutcome(
            id=row.id,
            decision_id=row.decision_id,
            profile_id=row.profile_id,
            satisfaction=row.satisfaction,
            regret=row.regret,
            notes=row.notes,
            source_event_id=row.source_event_id,
            created_at=_utc(row.created_at),
        )


class SqliteActiveQuestionRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, question: ActiveQuestion) -> None:
        with self._sessions.begin() as session:
            session.add(
                ActiveQuestionRow(
                    id=question.id,
                    profile_id=question.profile_id,
                    prompt=question.prompt,
                    preference_keys_json=_json_dump(question.preference_keys),
                    context_json=_json_dump(question.context),
                    option_a_label=question.option_a_label,
                    option_a_features_json=_json_dump(question.option_a_features),
                    option_b_label=question.option_b_label,
                    option_b_features_json=_json_dump(question.option_b_features),
                    information_gain_score=question.information_gain_score,
                    model_snapshot_version=question.model_snapshot_version,
                    algorithm_version=question.algorithm_version,
                    status=question.status.value,
                    created_at=question.created_at,
                )
            )

    def get(self, question_id: str) -> ActiveQuestion | None:
        with self._sessions() as session:
            row = session.get(ActiveQuestionRow, question_id)
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[ActiveQuestion, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ActiveQuestionRow)
                .where(ActiveQuestionRow.profile_id == profile_id)
                .order_by(ActiveQuestionRow.created_at.desc(), ActiveQuestionRow.id.desc())
            )
            return tuple(self._to_domain(row) for row in rows)

    def add_answer(self, answer: QuestionAnswer) -> None:
        with self._sessions.begin() as session:
            question = session.get(ActiveQuestionRow, answer.question_id)
            if question is None or question.status != ActiveQuestionStatus.PENDING.value:
                raise ValueError("Active question is missing or has already been answered.")
            session.add(
                QuestionAnswerRow(
                    id=answer.id,
                    question_id=answer.question_id,
                    choice=answer.choice,
                    source_event_id=answer.source_event_id,
                    created_at=answer.created_at,
                )
            )
            question.status = ActiveQuestionStatus.ANSWERED.value

    def get_answer(self, question_id: str) -> QuestionAnswer | None:
        with self._sessions() as session:
            row = session.scalar(
                select(QuestionAnswerRow).where(QuestionAnswerRow.question_id == question_id)
            )
            if row is None:
                return None
            return QuestionAnswer(
                id=row.id,
                question_id=row.question_id,
                choice=row.choice,
                source_event_id=row.source_event_id,
                created_at=_utc(row.created_at),
            )

    @staticmethod
    def _to_domain(row: ActiveQuestionRow) -> ActiveQuestion:
        return ActiveQuestion(
            id=row.id,
            profile_id=row.profile_id,
            prompt=row.prompt,
            preference_keys=tuple(json.loads(row.preference_keys_json)),
            context=json.loads(row.context_json),
            option_a_label=row.option_a_label,
            option_a_features=json.loads(row.option_a_features_json),
            option_b_label=row.option_b_label,
            option_b_features=json.loads(row.option_b_features_json),
            information_gain_score=row.information_gain_score,
            model_snapshot_version=row.model_snapshot_version,
            algorithm_version=row.algorithm_version,
            status=ActiveQuestionStatus(row.status),
            created_at=_utc(row.created_at),
        )


class SqliteEvidenceRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, evidence: Evidence) -> None:
        with self._sessions.begin() as session:
            source_event = session.get(RawEventRow, evidence.source_event_id)
            if source_event is None or source_event.profile_id != evidence.profile_id:
                raise ValueError("Evidence source event must belong to the same profile.")
            if evidence.source_message_id is not None:
                source_message = session.get(MessageRow, evidence.source_message_id)
                conversation = (
                    None
                    if source_message is None
                    else session.get(ConversationRow, source_message.conversation_id)
                )
                if conversation is None or conversation.profile_id != evidence.profile_id:
                    raise ValueError("Evidence source message must belong to the same profile.")
            session.add(
                EvidenceRow(
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
            )
            bump_evidence_revision(session, evidence.profile_id)

    def get(self, evidence_id: str) -> Evidence | None:
        with self._sessions() as session:
            row = session.get(EvidenceRow, evidence_id)
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[Evidence, ...]:
        return self.list_for_profile_with_revision(profile_id)[0]

    def list_for_profile_with_revision(self, profile_id: str) -> tuple[tuple[Evidence, ...], int]:
        with self._sessions() as session:
            rows = session.scalars(
                select(EvidenceRow)
                .where(EvidenceRow.profile_id == profile_id)
                .order_by(EvidenceRow.created_at, EvidenceRow.id)
            )
            evidence = tuple(self._to_domain(row) for row in rows)
            revision = session.get(EvidenceRevisionRow, profile_id)
            return evidence, 0 if revision is None else revision.revision

    def list_for_target(self, profile_id: str, target_key: str) -> tuple[Evidence, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(EvidenceRow)
                .where(
                    EvidenceRow.profile_id == profile_id,
                    EvidenceRow.target_key == target_key,
                )
                .order_by(EvidenceRow.created_at, EvidenceRow.id)
            )
            return tuple(self._to_domain(row) for row in rows)

    def remove(self, evidence_id: str) -> bool:
        with self._sessions.begin() as session:
            row = session.get(EvidenceRow, evidence_id)
            if row is None:
                return False
            profile_id = row.profile_id
            session.delete(row)
            session.flush()
            prune_unsupported_keys(session, profile_id)
            bump_evidence_revision(session, profile_id)
            return True

    def current_revision(self, profile_id: str) -> int:
        with self._sessions() as session:
            row = session.get(EvidenceRevisionRow, profile_id)
            return 0 if row is None else row.revision

    @staticmethod
    def _to_domain(row: EvidenceRow) -> Evidence:
        return Evidence(
            id=row.id,
            profile_id=row.profile_id,
            target_type=EvidenceTargetType(row.target_type),
            target_key=row.target_key,
            value=json.loads(row.value_json),
            strength=row.strength,
            confidence=row.confidence,
            context=json.loads(row.context_json),
            source_type=row.source_type,
            source_event_id=row.source_event_id,
            extractor_version=row.extractor_version,
            created_at=_utc(row.created_at),
            extractor_model=row.extractor_model,
            source_message_id=row.source_message_id,
        )


def _record_json(record: Preference | Fact | Goal | Constraint) -> dict[str, object]:
    value: object = record.value
    result: dict[str, object] = {
        "key": record.key,
        "value": value,
        "confidence": record.confidence,
        "context": record.context,
        "supporting_evidence_ids": list(record.supporting_evidence_ids),
        "updated_at": record.updated_at.isoformat(),
        "model_version": record.model_version,
    }
    if isinstance(record, Preference):
        result["uncertainty"] = record.uncertainty
    return result


def _model_json(model: DerivedModel) -> dict[str, object]:
    return {
        "preferences": [_record_json(item) for item in model.preferences],
        "facts": [_record_json(item) for item in model.facts],
        "goals": [_record_json(item) for item in model.goals],
        "constraints": [_record_json(item) for item in model.constraints],
    }


class SqlitePersonalModelRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def replace(
        self,
        profile_id: str,
        model: DerivedModel,
        evidence_revision: int,
        algorithm_version: str,
        created_at: datetime,
    ) -> UserModelSnapshot:
        with self._sessions.begin() as session:
            previous = session.scalar(
                select(func.max(UserModelSnapshotRow.version)).where(
                    UserModelSnapshotRow.profile_id == profile_id
                )
            )
            version = (previous or 0) + 1
            versioned = DerivedModel(
                preferences=tuple(
                    replace(item, model_version=version) for item in model.preferences
                ),
                facts=tuple(replace(item, model_version=version) for item in model.facts),
                goals=tuple(replace(item, model_version=version) for item in model.goals),
                constraints=tuple(
                    replace(item, model_version=version) for item in model.constraints
                ),
            )
            for row_type in (PreferenceRow, FactRow, GoalRow, ConstraintRow):
                session.execute(delete(row_type).where(row_type.profile_id == profile_id))
            session.add_all(
                [
                    PreferenceRow(
                        profile_id=profile_id,
                        key=item.key,
                        context_key=_json_dump(item.context),
                        value=item.value,
                        uncertainty=item.uncertainty,
                        confidence=item.confidence,
                        context_json=_json_dump(item.context),
                        supporting_evidence_ids_json=_json_dump(item.supporting_evidence_ids),
                        updated_at=item.updated_at,
                        model_version=version,
                    )
                    for item in versioned.preferences
                ]
            )
            self._add_categorical(session, profile_id, versioned.facts, FactRow)
            self._add_categorical(session, profile_id, versioned.goals, GoalRow)
            self._add_categorical(session, profile_id, versioned.constraints, ConstraintRow)
            session.add(
                UserModelSnapshotRow(
                    profile_id=profile_id,
                    version=version,
                    algorithm_version=algorithm_version,
                    evidence_revision=evidence_revision,
                    model_json=_json_dump(_model_json(versioned)),
                    created_at=created_at,
                )
            )
        return UserModelSnapshot(
            profile_id=profile_id,
            version=version,
            algorithm_version=algorithm_version,
            evidence_revision=evidence_revision,
            model=versioned,
            created_at=created_at,
        )

    @staticmethod
    def _add_categorical(
        session: Session,
        profile_id: str,
        records: tuple[Fact, ...] | tuple[Goal, ...] | tuple[Constraint, ...],
        row_type: type[FactRow] | type[GoalRow] | type[ConstraintRow],
    ) -> None:
        session.add_all(
            [
                row_type(
                    profile_id=profile_id,
                    key=item.key,
                    context_key=_json_dump(item.context),
                    value_json=_json_dump(item.value),
                    confidence=item.confidence,
                    context_json=_json_dump(item.context),
                    supporting_evidence_ids_json=_json_dump(item.supporting_evidence_ids),
                    updated_at=item.updated_at,
                    model_version=item.model_version,
                )
                for item in records
            ]
        )

    def latest_snapshot(self, profile_id: str) -> UserModelSnapshot | None:
        with self._sessions() as session:
            row = session.scalar(
                select(UserModelSnapshotRow)
                .where(UserModelSnapshotRow.profile_id == profile_id)
                .order_by(UserModelSnapshotRow.version.desc())
                .limit(1)
            )
            return None if row is None else self._snapshot_to_domain(row)

    def list_preferences(self, profile_id: str) -> tuple[Preference, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(PreferenceRow)
                .where(PreferenceRow.profile_id == profile_id)
                .order_by(PreferenceRow.key, PreferenceRow.context_key)
            )
            return tuple(self._preference_to_domain(row) for row in rows)

    def get_preferences(self, profile_id: str, key: str) -> tuple[Preference, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(PreferenceRow)
                .where(PreferenceRow.profile_id == profile_id, PreferenceRow.key == key)
                .order_by(PreferenceRow.context_key)
            )
            return tuple(self._preference_to_domain(row) for row in rows)

    @staticmethod
    def _preference_to_domain(row: PreferenceRow) -> Preference:
        return Preference(
            key=row.key,
            value=row.value,
            uncertainty=row.uncertainty,
            confidence=row.confidence,
            context=json.loads(row.context_json),
            supporting_evidence_ids=tuple(json.loads(row.supporting_evidence_ids_json)),
            updated_at=_utc(row.updated_at),
            model_version=row.model_version,
        )

    @classmethod
    def _snapshot_to_domain(cls, row: UserModelSnapshotRow) -> UserModelSnapshot:
        content = cast(dict[str, list[dict[str, object]]], json.loads(row.model_json))
        model = DerivedModel(
            preferences=tuple(cls._preference_from_json(item) for item in content["preferences"]),
            facts=tuple(cls._categorical_from_json(Fact, item) for item in content["facts"]),
            goals=tuple(cls._categorical_from_json(Goal, item) for item in content["goals"]),
            constraints=tuple(
                cls._categorical_from_json(Constraint, item) for item in content["constraints"]
            ),
        )
        return UserModelSnapshot(
            profile_id=row.profile_id,
            version=row.version,
            algorithm_version=row.algorithm_version,
            evidence_revision=row.evidence_revision,
            model=model,
            created_at=_utc(row.created_at),
        )

    @staticmethod
    def _preference_from_json(item: dict[str, object]) -> Preference:
        return Preference(
            key=str(item["key"]),
            value=cast(float, item["value"]),
            uncertainty=cast(float, item["uncertainty"]),
            confidence=cast(float, item["confidence"]),
            context=cast(dict[str, object], item["context"]),
            supporting_evidence_ids=tuple(cast(list[str], item["supporting_evidence_ids"])),
            updated_at=datetime.fromisoformat(str(item["updated_at"])),
            model_version=cast(int, item["model_version"]),
        )

    @staticmethod
    def _categorical_from_json[DerivedRecord: (Fact, Goal, Constraint)](
        record_type: type[DerivedRecord], item: dict[str, object]
    ) -> DerivedRecord:
        return record_type(
            key=str(item["key"]),
            value=item["value"],
            confidence=cast(float, item["confidence"]),
            context=cast(dict[str, object], item["context"]),
            supporting_evidence_ids=tuple(cast(list[str], item["supporting_evidence_ids"])),
            updated_at=datetime.fromisoformat(str(item["updated_at"])),
            model_version=cast(int, item["model_version"]),
        )


class SqliteAuditEventRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, event: AuditEvent) -> None:
        with self._sessions.begin() as session:
            session.add(
                AuditEventRow(
                    id=event.id,
                    profile_id=event.profile_id,
                    action=event.action,
                    actor_type=event.actor_type,
                    actor_id=event.actor_id,
                    metadata_json=None if event.metadata is None else _json_dump(event.metadata),
                    created_at=event.created_at,
                )
            )

    def get(self, event_id: str) -> AuditEvent | None:
        with self._sessions() as session:
            row = session.get(AuditEventRow, event_id)
            if row is None:
                return None
            metadata = None if row.metadata_json is None else json.loads(row.metadata_json)
            return AuditEvent(
                id=row.id,
                action=row.action,
                actor_type=row.actor_type,
                created_at=_utc(row.created_at),
                profile_id=row.profile_id,
                actor_id=row.actor_id,
                metadata=metadata,
            )

    def list_for_profile(self, profile_id: str, limit: int = 100) -> tuple[AuditEvent, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.profile_id == profile_id)
                .order_by(AuditEventRow.created_at.desc(), AuditEventRow.id.desc())
                .limit(limit)
            )
            return tuple(
                AuditEvent(
                    id=row.id,
                    action=row.action,
                    actor_type=row.actor_type,
                    actor_id=row.actor_id,
                    metadata=(None if row.metadata_json is None else json.loads(row.metadata_json)),
                    created_at=_utc(row.created_at),
                    profile_id=row.profile_id,
                )
                for row in rows
            )


class SqliteJobRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def enqueue(self, job: Job) -> None:
        with self._sessions.begin() as session:
            session.add(
                JobRow(
                    id=job.id,
                    job_type=job.job_type,
                    payload_json=_json_dump(job.payload),
                    status=job.status.value,
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                    available_at=job.available_at,
                    locked_at=job.locked_at,
                    last_error=job.last_error,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                )
            )

    def get(self, job_id: str) -> Job | None:
        with self._sessions() as session:
            row = session.get(JobRow, job_id)
            return None if row is None else self._to_domain(row)

    def claim_next(
        self, now: datetime, stale_before: datetime, job_types: Collection[str]
    ) -> Job | None:
        if not job_types:
            return None
        claimable = and_(
            JobRow.job_type.in_(job_types),
            JobRow.attempts < JobRow.max_attempts,
            or_(
                and_(JobRow.status == JobStatus.QUEUED.value, JobRow.available_at <= now),
                and_(JobRow.status == JobStatus.RUNNING.value, JobRow.locked_at < stale_before),
            ),
        )
        candidate = (
            select(JobRow.id)
            .where(claimable)
            .order_by(
                case((JobRow.status == JobStatus.QUEUED.value, 0), else_=1),
                JobRow.available_at,
                JobRow.created_at,
            )
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(JobRow)
            .where(JobRow.id == candidate, claimable)
            .values(
                status=JobStatus.RUNNING.value,
                attempts=JobRow.attempts + 1,
                locked_at=now,
                updated_at=now,
                last_error=None,
            )
            .returning(JobRow)
        )
        with self._sessions.begin() as session:
            session.execute(
                update(JobRow)
                .where(
                    JobRow.status == JobStatus.RUNNING.value,
                    JobRow.locked_at < stale_before,
                    JobRow.attempts >= JobRow.max_attempts,
                )
                .values(
                    status=JobStatus.FAILED.value,
                    locked_at=None,
                    last_error="Worker interrupted during final attempt",
                    updated_at=now,
                )
            )
            row = session.execute(statement).scalar_one_or_none()
            return None if row is None else self._to_domain(row)

    def mark_succeeded(self, job_id: str, completed_at: datetime) -> None:
        self._finish(job_id, completed_at, JobStatus.SUCCEEDED, None)

    def mark_failed(
        self,
        job_id: str,
        error: str,
        failed_at: datetime,
        retry_at: datetime | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            exhausted = row.attempts >= row.max_attempts
            row.status = JobStatus.FAILED.value if exhausted else JobStatus.QUEUED.value
            if not exhausted and retry_at is not None:
                row.available_at = retry_at
            row.locked_at = None
            row.last_error = error
            row.updated_at = failed_at

    def _finish(self, job_id: str, now: datetime, status: JobStatus, error: str | None) -> None:
        with self._sessions.begin() as session:
            updated_id = session.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(status=status.value, locked_at=None, last_error=error, updated_at=now)
                .returning(JobRow.id)
            ).scalar_one_or_none()
            if updated_id is None:
                raise KeyError(job_id)

    @staticmethod
    def _to_domain(row: JobRow) -> Job:
        return Job(
            id=row.id,
            job_type=row.job_type,
            payload=json.loads(row.payload_json),
            status=JobStatus(row.status),
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            available_at=_utc(row.available_at),
            locked_at=None if row.locked_at is None else _utc(row.locked_at),
            last_error=row.last_error,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )


class SqlitePairingTokenRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, token: PairingToken) -> None:
        with self._sessions.begin() as session:
            session.add(
                PairingTokenRow(
                    id=token.id,
                    profile_id=token.profile_id,
                    token_hash=token.token_hash,
                    created_at=token.created_at,
                    expires_at=token.expires_at,
                    consumed_at=token.consumed_at,
                    device_id=token.device_id,
                )
            )

    def get_by_hash(self, token_hash: str) -> PairingToken | None:
        with self._sessions() as session:
            row = session.scalars(
                select(PairingTokenRow).where(PairingTokenRow.token_hash == token_hash)
            ).one_or_none()
            return None if row is None else self._to_domain(row)

    def consume(self, token_id: str, device_id: str, consumed_at: datetime) -> bool:
        """Claim an unconsumed token atomically so a token can never be reused."""
        with self._sessions.begin() as session:
            claimed = session.execute(
                update(PairingTokenRow)
                .where(PairingTokenRow.id == token_id, PairingTokenRow.consumed_at.is_(None))
                .values(consumed_at=consumed_at, device_id=device_id)
                .returning(PairingTokenRow.id)
            ).scalar_one_or_none()
            return claimed is not None

    def delete_expired(self, before: datetime) -> int:
        with self._sessions.begin() as session:
            removed = session.execute(
                delete(PairingTokenRow)
                .where(PairingTokenRow.expires_at <= before)
                .returning(PairingTokenRow.id)
            ).scalars()
            return len(list(removed))

    @staticmethod
    def _to_domain(row: PairingTokenRow) -> PairingToken:
        return PairingToken(
            id=row.id,
            profile_id=row.profile_id,
            token_hash=row.token_hash,
            created_at=_utc(row.created_at),
            expires_at=_utc(row.expires_at),
            consumed_at=None if row.consumed_at is None else _utc(row.consumed_at),
            device_id=row.device_id,
        )


class SqlitePairedDeviceRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, device: PairedDevice) -> None:
        with self._sessions.begin() as session:
            session.add(
                PairedDeviceRow(
                    id=device.id,
                    profile_id=device.profile_id,
                    name=device.name,
                    platform=device.platform,
                    credential_hash=device.credential_hash,
                    created_at=device.created_at,
                    last_seen_at=device.last_seen_at,
                    revoked_at=device.revoked_at,
                )
            )

    def get(self, device_id: str) -> PairedDevice | None:
        with self._sessions() as session:
            row = session.get(PairedDeviceRow, device_id)
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[PairedDevice, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(PairedDeviceRow)
                .where(PairedDeviceRow.profile_id == profile_id)
                .order_by(PairedDeviceRow.created_at.desc(), PairedDeviceRow.id.desc())
            )
            return tuple(self._to_domain(row) for row in rows)

    def touch(self, device_id: str, last_seen_at: datetime) -> None:
        with self._sessions.begin() as session:
            updated_id = session.execute(
                update(PairedDeviceRow)
                .where(PairedDeviceRow.id == device_id)
                .values(last_seen_at=last_seen_at)
                .returning(PairedDeviceRow.id)
            ).scalar_one_or_none()
            if updated_id is None:
                raise KeyError(device_id)

    def revoke(self, device_id: str, revoked_at: datetime) -> bool:
        with self._sessions.begin() as session:
            revoked_id = session.execute(
                update(PairedDeviceRow)
                .where(PairedDeviceRow.id == device_id, PairedDeviceRow.revoked_at.is_(None))
                .values(revoked_at=revoked_at)
                .returning(PairedDeviceRow.id)
            ).scalar_one_or_none()
            return revoked_id is not None

    @staticmethod
    def _to_domain(row: PairedDeviceRow) -> PairedDevice:
        return PairedDevice(
            id=row.id,
            profile_id=row.profile_id,
            name=row.name,
            platform=row.platform,
            credential_hash=row.credential_hash,
            created_at=_utc(row.created_at),
            last_seen_at=None if row.last_seen_at is None else _utc(row.last_seen_at),
            revoked_at=None if row.revoked_at is None else _utc(row.revoked_at),
        )


class SqliteServiceIdentityRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, identity: ServiceIdentity) -> None:
        with self._sessions.begin() as session:
            session.add(
                ServiceIdentityRow(
                    id=identity.id,
                    profile_id=identity.profile_id,
                    name=identity.name,
                    description=identity.description,
                    created_at=identity.created_at,
                    revoked_at=identity.revoked_at,
                )
            )
            session.add_all(
                ServiceIdentityScopeRow(service_identity_id=identity.id, scope=scope)
                for scope in identity.scopes
            )

    def get(self, identity_id: str) -> ServiceIdentity | None:
        with self._sessions() as session:
            row = session.get(ServiceIdentityRow, identity_id)
            return None if row is None else self._to_domain(session, row)

    def list_for_profile(self, profile_id: str) -> tuple[ServiceIdentity, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ServiceIdentityRow)
                .where(ServiceIdentityRow.profile_id == profile_id)
                .order_by(ServiceIdentityRow.created_at.desc(), ServiceIdentityRow.id.desc())
            )
            return tuple(self._to_domain(session, row) for row in rows)

    def replace_scopes(self, identity_id: str, scopes: tuple[str, ...]) -> bool:
        with self._sessions.begin() as session:
            if session.get(ServiceIdentityRow, identity_id) is None:
                return False
            session.execute(
                delete(ServiceIdentityScopeRow).where(
                    ServiceIdentityScopeRow.service_identity_id == identity_id
                )
            )
            session.add_all(
                ServiceIdentityScopeRow(service_identity_id=identity_id, scope=scope)
                for scope in scopes
            )
            return True

    def revoke(self, identity_id: str, revoked_at: datetime) -> bool:
        with self._sessions.begin() as session:
            revoked_id = session.execute(
                update(ServiceIdentityRow)
                .where(
                    ServiceIdentityRow.id == identity_id,
                    ServiceIdentityRow.revoked_at.is_(None),
                )
                .values(revoked_at=revoked_at)
                .returning(ServiceIdentityRow.id)
            ).scalar_one_or_none()
            return revoked_id is not None

    @staticmethod
    def _to_domain(session: Session, row: ServiceIdentityRow) -> ServiceIdentity:
        scopes = session.scalars(
            select(ServiceIdentityScopeRow.scope)
            .where(ServiceIdentityScopeRow.service_identity_id == row.id)
            .order_by(ServiceIdentityScopeRow.scope)
        )
        return ServiceIdentity(
            id=row.id,
            profile_id=row.profile_id,
            name=row.name,
            description=row.description,
            scopes=tuple(scopes),
            created_at=_utc(row.created_at),
            revoked_at=None if row.revoked_at is None else _utc(row.revoked_at),
        )


class SqliteApiCredentialRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, credential: ApiCredential) -> None:
        with self._sessions.begin() as session:
            session.add(
                ApiCredentialRow(
                    id=credential.id,
                    service_identity_id=credential.service_identity_id,
                    secret_hash=credential.secret_hash,
                    created_at=credential.created_at,
                    last_used_at=credential.last_used_at,
                    revoked_at=credential.revoked_at,
                )
            )

    def get(self, credential_id: str) -> ApiCredential | None:
        with self._sessions() as session:
            row = session.get(ApiCredentialRow, credential_id)
            return None if row is None else self._to_domain(row)

    def list_for_identity(self, identity_id: str) -> tuple[ApiCredential, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ApiCredentialRow)
                .where(ApiCredentialRow.service_identity_id == identity_id)
                .order_by(ApiCredentialRow.created_at.desc(), ApiCredentialRow.id.desc())
            )
            return tuple(self._to_domain(row) for row in rows)

    def touch(self, credential_id: str, last_used_at: datetime) -> None:
        with self._sessions.begin() as session:
            updated_id = session.execute(
                update(ApiCredentialRow)
                .where(ApiCredentialRow.id == credential_id)
                .values(last_used_at=last_used_at)
                .returning(ApiCredentialRow.id)
            ).scalar_one_or_none()
            if updated_id is None:
                raise KeyError(credential_id)

    def revoke(self, credential_id: str, revoked_at: datetime) -> bool:
        with self._sessions.begin() as session:
            revoked_id = session.execute(
                update(ApiCredentialRow)
                .where(
                    ApiCredentialRow.id == credential_id,
                    ApiCredentialRow.revoked_at.is_(None),
                )
                .values(revoked_at=revoked_at)
                .returning(ApiCredentialRow.id)
            ).scalar_one_or_none()
            return revoked_id is not None

    @staticmethod
    def _to_domain(row: ApiCredentialRow) -> ApiCredential:
        return ApiCredential(
            id=row.id,
            service_identity_id=row.service_identity_id,
            secret_hash=row.secret_hash,
            created_at=_utc(row.created_at),
            last_used_at=None if row.last_used_at is None else _utc(row.last_used_at),
            revoked_at=None if row.revoked_at is None else _utc(row.revoked_at),
        )


class SqliteDelegationPolicyRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def upsert(self, policy: DelegationPolicy) -> DelegationPolicy:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(DelegationPolicyRow).where(
                    DelegationPolicyRow.profile_id == policy.profile_id,
                    DelegationPolicyRow.service_identity_id == policy.service_identity_id,
                    DelegationPolicyRow.action_type == policy.action_type,
                )
            )
            if row is None:
                row = DelegationPolicyRow(
                    id=policy.id,
                    profile_id=policy.profile_id,
                    service_identity_id=policy.service_identity_id,
                    action_type=policy.action_type,
                    impact=policy.impact.value,
                    minimum_confidence=policy.minimum_confidence,
                    allow_automatic=policy.allow_automatic,
                    created_at=policy.created_at,
                    updated_at=policy.updated_at,
                )
                session.add(row)
            else:
                row.impact = policy.impact.value
                row.minimum_confidence = policy.minimum_confidence
                row.allow_automatic = policy.allow_automatic
                row.updated_at = policy.updated_at
            session.flush()
            return self._to_domain(row)

    def get(self, policy_id: str) -> DelegationPolicy | None:
        with self._sessions() as session:
            row = session.get(DelegationPolicyRow, policy_id)
            return None if row is None else self._to_domain(row)

    def get_for_action(
        self, profile_id: str, service_identity_id: str, action_type: str
    ) -> DelegationPolicy | None:
        with self._sessions() as session:
            row = session.scalar(
                select(DelegationPolicyRow).where(
                    DelegationPolicyRow.profile_id == profile_id,
                    DelegationPolicyRow.service_identity_id == service_identity_id,
                    DelegationPolicyRow.action_type == action_type,
                )
            )
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[DelegationPolicy, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DelegationPolicyRow)
                .where(DelegationPolicyRow.profile_id == profile_id)
                .order_by(DelegationPolicyRow.created_at.desc(), DelegationPolicyRow.id.desc())
            )
            return tuple(self._to_domain(row) for row in rows)

    def remove(self, profile_id: str, policy_id: str) -> bool:
        with self._sessions.begin() as session:
            removed_id = session.execute(
                delete(DelegationPolicyRow)
                .where(
                    DelegationPolicyRow.id == policy_id,
                    DelegationPolicyRow.profile_id == profile_id,
                )
                .returning(DelegationPolicyRow.id)
            ).scalar_one_or_none()
            return removed_id is not None

    @staticmethod
    def _to_domain(row: DelegationPolicyRow) -> DelegationPolicy:
        return DelegationPolicy(
            id=row.id,
            profile_id=row.profile_id,
            service_identity_id=row.service_identity_id,
            action_type=row.action_type,
            impact=DecisionImpact(row.impact),
            minimum_confidence=row.minimum_confidence,
            allow_automatic=row.allow_automatic,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )


class SqliteDelegationRequestRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, request: DelegationRequest) -> None:
        with self._sessions.begin() as session:
            session.add(
                DelegationRequestRow(
                    id=request.id,
                    profile_id=request.profile_id,
                    service_identity_id=request.service_identity_id,
                    policy_id=request.policy_id,
                    decision_id=request.decision_id,
                    prediction_id=request.prediction_id,
                    external_request_id=request.external_request_id,
                    action_type=request.action_type,
                    action_label=request.action_label,
                    impact=request.impact.value,
                    predicted_option_id=request.predicted_option_id,
                    prediction_confidence=request.prediction_confidence,
                    status=request.status.value,
                    reason_code=request.reason_code,
                    requested_at=request.requested_at,
                    expires_at=request.expires_at,
                    reviewed_at=request.reviewed_at,
                    completed_at=request.completed_at,
                    expired_at=request.expired_at,
                )
            )

    def get(self, request_id: str) -> DelegationRequest | None:
        with self._sessions() as session:
            row = session.get(DelegationRequestRow, request_id)
            return None if row is None else self._to_domain(row)

    def get_by_external_request(
        self, service_identity_id: str, external_request_id: str
    ) -> DelegationRequest | None:
        with self._sessions() as session:
            row = session.scalar(
                select(DelegationRequestRow).where(
                    DelegationRequestRow.service_identity_id == service_identity_id,
                    DelegationRequestRow.external_request_id == external_request_id,
                )
            )
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[DelegationRequest, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DelegationRequestRow)
                .where(DelegationRequestRow.profile_id == profile_id)
                .order_by(
                    DelegationRequestRow.requested_at.desc(),
                    DelegationRequestRow.id.desc(),
                )
            )
            return tuple(self._to_domain(row) for row in rows)

    def transition(
        self,
        request_id: str,
        expected_status: DelegationStatus,
        status: DelegationStatus,
        reason_code: str,
        changed_at: datetime,
    ) -> bool:
        values: dict[str, object] = {
            "status": status.value,
            "reason_code": reason_code,
        }
        if status in (DelegationStatus.APPROVED, DelegationStatus.REJECTED):
            values["reviewed_at"] = changed_at
        if status is DelegationStatus.COMPLETED:
            values["completed_at"] = changed_at
        if status is DelegationStatus.EXPIRED:
            values["expired_at"] = changed_at
        with self._sessions.begin() as session:
            changed = session.execute(
                update(DelegationRequestRow)
                .where(
                    DelegationRequestRow.id == request_id,
                    DelegationRequestRow.status == expected_status.value,
                )
                .values(**values)
                .returning(DelegationRequestRow.id)
            ).scalar_one_or_none()
            return changed is not None

    @staticmethod
    def _to_domain(row: DelegationRequestRow) -> DelegationRequest:
        return DelegationRequest(
            id=row.id,
            profile_id=row.profile_id,
            service_identity_id=row.service_identity_id,
            policy_id=row.policy_id,
            decision_id=row.decision_id,
            prediction_id=row.prediction_id,
            external_request_id=row.external_request_id,
            action_type=row.action_type,
            action_label=row.action_label,
            impact=DecisionImpact(row.impact),
            predicted_option_id=row.predicted_option_id,
            prediction_confidence=row.prediction_confidence,
            status=DelegationStatus(row.status),
            reason_code=row.reason_code,
            requested_at=_utc(row.requested_at),
            expires_at=_utc(row.expires_at),
            reviewed_at=None if row.reviewed_at is None else _utc(row.reviewed_at),
            completed_at=None if row.completed_at is None else _utc(row.completed_at),
            expired_at=None if row.expired_at is None else _utc(row.expired_at),
        )


class SqliteConnectorRegistrationRepository:
    """Persist connector consent, cursors, idempotency keys, and source provenance."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, registration: ConnectorRegistration) -> None:
        with self._sessions.begin() as session:
            session.add(
                SourceRow(
                    id=registration.source_id,
                    profile_id=registration.profile_id,
                    source_type=f"connector:{registration.connector_id}",
                    name=registration.name,
                    created_at=registration.created_at,
                )
            )
            session.flush()
            session.add(
                ConnectorRegistrationRow(
                    id=registration.id,
                    profile_id=registration.profile_id,
                    connector_id=registration.connector_id,
                    name=registration.name,
                    source_id=registration.source_id,
                    enabled=registration.enabled,
                    granted_permissions_json=_json_dump(
                        [item.value for item in registration.granted_permissions]
                    ),
                    configuration_json=_json_dump(registration.configuration),
                    cursor_json=(
                        None if registration.cursor is None else _json_dump(registration.cursor)
                    ),
                    sync_status=registration.sync_status.value,
                    last_sync_at=registration.last_sync_at,
                    last_error_code=registration.last_error_code,
                    created_at=registration.created_at,
                    updated_at=registration.updated_at,
                )
            )

    def get(self, profile_id: str, connector_id: str) -> ConnectorRegistration | None:
        with self._sessions() as session:
            row = session.scalar(
                select(ConnectorRegistrationRow).where(
                    ConnectorRegistrationRow.profile_id == profile_id,
                    ConnectorRegistrationRow.connector_id == connector_id,
                )
            )
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[ConnectorRegistration, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ConnectorRegistrationRow)
                .where(ConnectorRegistrationRow.profile_id == profile_id)
                .order_by(ConnectorRegistrationRow.created_at, ConnectorRegistrationRow.id)
            )
            return tuple(self._to_domain(row) for row in rows)

    def set_enabled(
        self, profile_id: str, connector_id: str, enabled: bool, updated_at: datetime
    ) -> bool:
        with self._sessions.begin() as session:
            changed = session.execute(
                update(ConnectorRegistrationRow)
                .where(
                    ConnectorRegistrationRow.profile_id == profile_id,
                    ConnectorRegistrationRow.connector_id == connector_id,
                )
                .values(enabled=enabled, updated_at=updated_at)
                .returning(ConnectorRegistrationRow.id)
            ).scalar_one_or_none()
            return changed is not None

    def mark_running(self, registration_id: str, updated_at: datetime) -> bool:
        with self._sessions.begin() as session:
            changed = session.execute(
                update(ConnectorRegistrationRow)
                .where(
                    ConnectorRegistrationRow.id == registration_id,
                    ConnectorRegistrationRow.enabled.is_(True),
                )
                .values(
                    sync_status=ConnectorSyncStatus.RUNNING.value,
                    last_error_code=None,
                    updated_at=updated_at,
                )
                .returning(ConnectorRegistrationRow.id)
            ).scalar_one_or_none()
            return changed is not None

    def apply_sync(
        self,
        registration_id: str,
        events: tuple[PersistedConnectorEvent, ...],
        cursor: dict[str, object] | None,
        completed_at: datetime,
    ) -> StoredSyncResult:
        external_ids = tuple(item.external_id for item in events)
        if len(set(external_ids)) != len(external_ids):
            raise ValueError("A connector sync returned duplicate external IDs.")
        with self._sessions.begin() as session:
            registration = session.get(ConnectorRegistrationRow, registration_id)
            if registration is None:
                raise KeyError(registration_id)
            if not registration.enabled:
                raise ValueError("The connector is disabled.")
            existing = set(
                session.scalars(
                    select(ConnectorItemRow.external_id).where(
                        ConnectorItemRow.registration_id == registration_id,
                        ConnectorItemRow.external_id.in_(external_ids),
                    )
                )
            )
            accepted = tuple(item for item in events if item.external_id not in existing)
            session.add_all(
                RawEventRow(
                    id=item.raw_event_id,
                    profile_id=registration.profile_id,
                    source_id=registration.source_id,
                    event_type=item.event_type,
                    content_json=_json_dump(item.content),
                    created_at=item.created_at,
                    ingested_at=item.ingested_at,
                    sensitivity=item.sensitivity,
                )
                for item in accepted
            )
            session.flush()
            session.add_all(
                ConnectorItemRow(
                    registration_id=registration_id,
                    external_id=item.external_id,
                    raw_event_id=item.raw_event_id,
                )
                for item in accepted
            )
            registration.cursor_json = None if cursor is None else _json_dump(cursor)
            registration.sync_status = ConnectorSyncStatus.SUCCEEDED.value
            registration.last_sync_at = completed_at
            registration.last_error_code = None
            registration.updated_at = completed_at
            return StoredSyncResult(
                accepted_count=len(accepted),
                duplicate_count=len(events) - len(accepted),
            )

    def mark_failed(self, registration_id: str, error_code: str, failed_at: datetime) -> None:
        with self._sessions.begin() as session:
            changed = session.execute(
                update(ConnectorRegistrationRow)
                .where(ConnectorRegistrationRow.id == registration_id)
                .values(
                    sync_status=ConnectorSyncStatus.FAILED.value,
                    last_error_code=error_code,
                    updated_at=failed_at,
                )
                .returning(ConnectorRegistrationRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise KeyError(registration_id)

    def remove(self, profile_id: str, connector_id: str) -> ConnectorRemoval | None:
        with self._sessions.begin() as session:
            registration = session.scalar(
                select(ConnectorRegistrationRow).where(
                    ConnectorRegistrationRow.profile_id == profile_id,
                    ConnectorRegistrationRow.connector_id == connector_id,
                )
            )
            if registration is None:
                return None
            event_ids = select(RawEventRow.id).where(
                RawEventRow.source_id == registration.source_id
            )
            raw_event_count = cast(
                int,
                session.scalar(
                    select(func.count())
                    .select_from(RawEventRow)
                    .where(RawEventRow.source_id == registration.source_id)
                ),
            )
            evidence_count = cast(
                int,
                session.scalar(
                    select(func.count())
                    .select_from(EvidenceRow)
                    .where(EvidenceRow.source_event_id.in_(event_ids))
                ),
            )
            result = ConnectorRemoval(
                connector_id=connector_id,
                source_id=registration.source_id,
                raw_event_count=raw_event_count,
                evidence_count=evidence_count,
            )
            session.execute(delete(EvidenceRow).where(EvidenceRow.source_event_id.in_(event_ids)))
            session.execute(
                delete(ConnectorItemRow).where(ConnectorItemRow.registration_id == registration.id)
            )
            session.execute(delete(RawEventRow).where(RawEventRow.source_id == result.source_id))
            session.delete(registration)
            source = session.get(SourceRow, result.source_id)
            if source is not None:
                session.delete(source)
            if evidence_count:
                prune_unsupported_keys(session, profile_id)
                bump_evidence_revision(session, profile_id)
            return result

    @staticmethod
    def _to_domain(row: ConnectorRegistrationRow) -> ConnectorRegistration:
        permissions = tuple(
            sorted(
                (ConnectorPermission(item) for item in json.loads(row.granted_permissions_json)),
                key=str,
            )
        )
        configuration = cast(dict[str, object], json.loads(row.configuration_json))
        cursor = (
            None
            if row.cursor_json is None
            else cast(dict[str, object], json.loads(row.cursor_json))
        )
        return ConnectorRegistration(
            id=row.id,
            profile_id=row.profile_id,
            connector_id=row.connector_id,
            name=row.name,
            source_id=row.source_id,
            enabled=row.enabled,
            granted_permissions=permissions,
            configuration=configuration,
            cursor=cursor,
            sync_status=ConnectorSyncStatus(row.sync_status),
            last_sync_at=None if row.last_sync_at is None else _utc(row.last_sync_at),
            last_error_code=row.last_error_code,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )


class SqliteSystemMetadataRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(self, key: str) -> str | None:
        with self._sessions() as session:
            row = session.get(SystemMetadataRow, key)
            return None if row is None else row.value

    def set(self, key: str, value: str, updated_at: datetime) -> None:
        with self._sessions.begin() as session:
            row = session.get(SystemMetadataRow, key)
            if row is None:
                session.add(SystemMetadataRow(key=key, value=value, updated_at=updated_at))
            else:
                row.value = value
                row.updated_at = updated_at

    def get_or_create(self, key: str, value: str, updated_at: datetime) -> str:
        with self._sessions.begin() as session:
            session.execute(
                insert(SystemMetadataRow)
                .values(key=key, value=value, updated_at=updated_at)
                .on_conflict_do_nothing(index_elements=[SystemMetadataRow.key])
            )
            stored = session.get(SystemMetadataRow, key)
            if stored is None:
                raise RuntimeError("System metadata could not be initialized.")
            return stored.value


class Repositories:
    """Convenient adapter collection for daemon composition."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.profiles = SqliteProfileRepository(sessions)
        self.sources = SqliteSourceRepository(sessions)
        self.raw_events = SqliteRawEventRepository(sessions)
        self.conversations = SqliteConversationRepository(sessions)
        self.messages = SqliteMessageRepository(sessions)
        self.decisions = SqliteDecisionRepository(sessions)
        self.outcomes = SqliteOutcomeRepository(sessions)
        self.active_questions = SqliteActiveQuestionRepository(sessions)
        self.evidence = SqliteEvidenceRepository(sessions)
        self.key_aliases = SqliteTargetKeyAliasRepository(sessions)
        self.key_catalog = SqliteTargetKeyCatalogRepository(sessions)
        self.key_embeddings = SqliteTargetKeyEmbeddingRepository(sessions)
        self.personal_models = SqlitePersonalModelRepository(sessions)
        self.audit_events = SqliteAuditEventRepository(sessions)
        self.jobs = SqliteJobRepository(sessions)
        self.pairing_tokens = SqlitePairingTokenRepository(sessions)
        self.paired_devices = SqlitePairedDeviceRepository(sessions)
        self.service_identities = SqliteServiceIdentityRepository(sessions)
        self.api_credentials = SqliteApiCredentialRepository(sessions)
        self.delegation_policies = SqliteDelegationPolicyRepository(sessions)
        self.delegation_requests = SqliteDelegationRequestRepository(sessions)
        self.connector_registrations = SqliteConnectorRegistrationRepository(sessions)
        self.system_metadata = SqliteSystemMetadataRepository(sessions)
