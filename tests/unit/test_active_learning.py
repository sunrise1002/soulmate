"""Test deterministic uncertainty selection and pairwise evidence creation."""

from dataclasses import replace
from datetime import UTC, datetime

from soulmate_core.domain import (
    ActiveQuestionStatus,
    DerivedModel,
    Preference,
    QuestionAnswer,
    UserModelSnapshot,
)
from soulmate_core.learning import answer_evidence, generate_active_questions, rank_uncertainties


def _snapshot() -> UserModelSnapshot:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return UserModelSnapshot(
        "profile_test",
        4,
        "personal-model-v1",
        2,
        DerivedModel(
            (
                Preference("work.speed", 0.2, 0.8, 0.2, {}, ("evidence_speed",), now, 4),
                Preference("work.quality", 0.4, 0.6, 0.4, {}, ("evidence_quality",), now, 4),
            ),
            (),
            (),
            (),
        ),
        now,
    )


def test_uncertainty_ranking_generates_high_information_tradeoff() -> None:
    snapshot = _snapshot()

    signals = rank_uncertainties(snapshot.model.preferences)
    questions = generate_active_questions(
        snapshot=snapshot,
        existing=(),
        question_ids=("question_test",),
        created_at=snapshot.created_at,
    )

    assert signals[0].preference_key == "work.speed"
    assert questions[0].preference_keys == ("work.speed", "work.quality")
    assert questions[0].option_a_features == {"work.speed": 1.0, "work.quality": -1.0}
    assert questions[0].model_snapshot_version == 4


def test_answer_creates_pairwise_evidence_and_answered_pair_is_not_repeated() -> None:
    snapshot = _snapshot()
    question = generate_active_questions(
        snapshot=snapshot,
        existing=(),
        question_ids=("question_test",),
        created_at=snapshot.created_at,
    )[0]
    answer = QuestionAnswer("answer_test", question.id, "b", "event_answer", snapshot.created_at)

    learned = answer_evidence(question=question, answer=answer, profile_id="profile_test")
    answered = replace(question, status=ActiveQuestionStatus.ANSWERED)
    repeated = generate_active_questions(
        snapshot=snapshot,
        existing=(answered,),
        question_ids=("question_next",),
        created_at=snapshot.created_at,
    )

    assert [(item.target_key, item.value) for item in learned] == [
        ("work.quality", 1.0),
        ("work.speed", -1.0),
    ]
    assert all(item.source_type == "pairwise_calibration" for item in learned)
    assert repeated[0].preference_keys != question.preference_keys


def test_questions_preserve_context_and_never_pair_incompatible_contexts() -> None:
    snapshot = _snapshot()
    career_speed, career_quality = snapshot.model.preferences
    contextual = replace(
        snapshot,
        model=DerivedModel(
            (
                replace(career_speed, context={"domain": "career"}),
                replace(career_quality, context={"domain": "career"}),
                replace(career_speed, key="travel.speed", context={"domain": "travel"}),
            ),
            (),
            (),
            (),
        ),
    )

    targeted = generate_active_questions(
        snapshot=contextual,
        existing=(),
        question_ids=("question_travel",),
        created_at=snapshot.created_at,
        target_key="travel.speed",
    )
    missing = generate_active_questions(
        snapshot=contextual,
        existing=(),
        question_ids=("question_missing",),
        created_at=snapshot.created_at,
        target_key="unknown.preference",
    )

    assert targeted[0].preference_keys == ("travel.speed",)
    assert targeted[0].context == {"domain": "travel"}
    assert missing == ()
