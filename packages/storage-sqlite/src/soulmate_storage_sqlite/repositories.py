"""SQLAlchemy implementations of Soulmate repository ports."""

import json
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from soulmate_core.domain.models import (
    ActiveQuestion,
    ActiveQuestionStatus,
    AdviceRankingItem,
    AuditEvent,
    Constraint,
    Conversation,
    DecisionAdvice,
    DecisionEvent,
    DecisionOption,
    DecisionOutcome,
    DecisionPrediction,
    DecisionResolution,
    DecisionStatus,
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
    Source,
    UserModelSnapshot,
)
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from soulmate_storage_sqlite.schema import (
    ActiveQuestionRow,
    AuditEventRow,
    ConstraintRow,
    ConversationRow,
    DecisionAdviceRow,
    DecisionEventRow,
    DecisionOptionRow,
    DecisionOutcomeRow,
    DecisionPredictionRow,
    DecisionResolutionRow,
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
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                )
            )

    def get(self, conversation_id: str) -> Conversation | None:
        with self._sessions() as session:
            row = session.get(ConversationRow, conversation_id)
            if row is None:
                return None
            return Conversation(row.id, row.profile_id, _utc(row.created_at), _utc(row.updated_at))

    def list_for_profile(self, profile_id: str) -> tuple[Conversation, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ConversationRow)
                .where(ConversationRow.profile_id == profile_id)
                .order_by(ConversationRow.updated_at.desc(), ConversationRow.id.desc())
            )
            return tuple(
                Conversation(row.id, row.profile_id, _utc(row.created_at), _utc(row.updated_at))
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

    @staticmethod
    def _bump_revision(session: Session, profile_id: str) -> None:
        statement = insert(EvidenceRevisionRow).values(profile_id=profile_id, revision=1)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[EvidenceRevisionRow.profile_id],
                set_={"revision": EvidenceRevisionRow.revision + 1},
            )
        )

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
            self._bump_revision(session, evidence.profile_id)

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
            self._bump_revision(session, profile_id)
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

    def mark_failed(self, job_id: str, error: str, failed_at: datetime) -> None:
        with self._sessions.begin() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            row.status = (
                JobStatus.FAILED.value
                if row.attempts >= row.max_attempts
                else JobStatus.QUEUED.value
            )
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
        self.personal_models = SqlitePersonalModelRepository(sessions)
        self.audit_events = SqliteAuditEventRepository(sessions)
        self.jobs = SqliteJobRepository(sessions)
        self.pairing_tokens = SqlitePairingTokenRepository(sessions)
        self.paired_devices = SqlitePairedDeviceRepository(sessions)
        self.system_metadata = SqliteSystemMetadataRepository(sessions)
