"""Application workflow for uncertainty-driven pairwise questions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from soulmate_core.domain import (
    ActiveQuestion,
    ActiveQuestionRepository,
    ActiveQuestionStatus,
    Evidence,
    EvidenceRepository,
    PersonalModelRepository,
    QuestionAnswer,
    RawEvent,
    RawEventRepository,
    TargetKeyAliasRepository,
)
from soulmate_core.learning import answer_evidence, generate_active_questions
from soulmate_core.preferences import ModelRebuilder


@dataclass(frozen=True, slots=True)
class ActiveAnswerResult:
    answer: QuestionAnswer
    evidence: tuple[Evidence, ...]
    snapshot_version: int


class ActiveLearningService:
    def __init__(
        self,
        *,
        questions: ActiveQuestionRepository,
        raw_events: RawEventRepository,
        evidence: EvidenceRepository,
        models: PersonalModelRepository,
        aliases: TargetKeyAliasRepository | None,
    ) -> None:
        self._questions = questions
        self._raw_events = raw_events
        self._evidence = evidence
        self._rebuilder = ModelRebuilder(evidence, models, aliases)

    def generate(
        self, profile_id: str, limit: int, target_key: str | None = None
    ) -> tuple[ActiveQuestion, ...]:
        now = datetime.now(UTC)
        snapshot = self._rebuilder.current(profile_id, now)
        generated = generate_active_questions(
            snapshot=snapshot,
            existing=self._questions.list_for_profile(profile_id),
            question_ids=tuple(f"question_{uuid4().hex}" for _ in range(limit)),
            created_at=now,
            target_key=target_key,
        )
        for question in generated:
            self._questions.add(question)
        return generated

    def answer(self, profile_id: str, question_id: str, choice: str) -> ActiveAnswerResult:
        question = self._questions.get(question_id)
        if question is None or question.profile_id != profile_id:
            raise KeyError(question_id)
        if question.status is ActiveQuestionStatus.ANSWERED:
            raise ValueError("Active question has already been answered.")
        now = datetime.now(UTC)
        answer_id = f"answer_{uuid4().hex}"
        event = RawEvent(
            id=f"event_{uuid4().hex}",
            profile_id=profile_id,
            source_id=None,
            event_type="active_question_answer",
            content={"question_id": question_id, "choice": choice},
            created_at=now,
            ingested_at=now,
        )
        answer = QuestionAnswer(answer_id, question_id, choice, event.id, now)
        learned = answer_evidence(question=question, answer=answer, profile_id=profile_id)
        self._raw_events.add(event)
        self._questions.add_answer(answer)
        for item in learned:
            self._evidence.add(item)
        snapshot = self._rebuilder.rebuild(profile_id, now)
        return ActiveAnswerResult(answer, learned, snapshot.version)
