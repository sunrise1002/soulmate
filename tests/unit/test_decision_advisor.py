"""Test that normative advice remains distinct from behavioral prediction."""

from datetime import UTC, datetime

from soulmate_core.decisions import DecisionAdvisor, OutcomeHistory, ResolvedDecision
from soulmate_core.domain import (
    DecisionEvent,
    DecisionOption,
    DecisionOutcome,
    DecisionPrediction,
    DecisionResolution,
    DecisionStatus,
    DerivedModel,
    OptionProbability,
    UserModelSnapshot,
)


def test_low_satisfaction_and_regret_can_change_recommendation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = DecisionEvent("current", "profile", "career", "Choose?", {}, DecisionStatus.OPEN, now)
    options = (
        DecisionOption("familiar", current.id, "Familiar", "Known path", {"novelty": -1.0}, 1),
        DecisionOption("new", current.id, "New", "New path", {"novelty": 1.0}, 1),
    )
    prediction = DecisionPrediction(
        "prediction",
        current.id,
        "profile",
        (OptionProbability("familiar", 0.8, 1), OptionProbability("new", 0.2, 0)),
        0.8,
        ("novelty",),
        (),
        (),
        (),
        1,
        "predict-v1",
        now,
    )
    historical = DecisionEvent(
        "historical", "profile", "career", "Earlier choice?", {}, DecisionStatus.RESOLVED, now
    )
    historical_options = (
        DecisionOption(
            "historical_familiar", historical.id, "Familiar", "Known", {"novelty": -1.0}, 1
        ),
        DecisionOption("historical_new", historical.id, "New", "New", {"novelty": 1.0}, 1),
    )
    resolution = DecisionResolution(
        "resolution", historical.id, "historical_familiar", "event_resolution", now
    )
    outcome = DecisionOutcome(
        "outcome", historical.id, "profile", 0.0, True, "Synthetic regret", "event_outcome", now
    )
    snapshot = UserModelSnapshot("profile", 1, "model-v1", 0, DerivedModel((), (), (), ()), now)

    advice = DecisionAdvisor().advise(
        advice_id="advice",
        decision=current,
        options=options,
        prediction=prediction,
        snapshot=snapshot,
        outcome_history=(
            OutcomeHistory(ResolvedDecision(historical, historical_options, resolution), outcome),
        ),
        created_at=now,
    )

    assert prediction.ranking[0].option_id == "familiar"
    assert advice.ranking[0].option_id == "new"
    assert advice.supporting_outcome_ids == ("outcome",)
    assert any("shifts the recommendation" in item for item in advice.rationale)


def test_advice_without_wellbeing_data_falls_back_to_behavioral_prediction() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    decision = DecisionEvent(
        "decision", "profile", "general", "Choose?", {}, DecisionStatus.OPEN, now
    )
    options = (
        DecisionOption("a", decision.id, "A", "A", {"feature": 1.0}, 1),
        DecisionOption("b", decision.id, "B", "B", {"feature": -1.0}, 1),
    )
    prediction = DecisionPrediction(
        "prediction",
        decision.id,
        "profile",
        (OptionProbability("a", 0.7, 1), OptionProbability("b", 0.3, 0)),
        0.6,
        (),
        (),
        (),
        (),
        1,
        "predict-v1",
        now,
    )
    snapshot = UserModelSnapshot("profile", 1, "model-v1", 0, DerivedModel((), (), (), ()), now)

    advice = DecisionAdvisor().advise(
        advice_id="advice",
        decision=decision,
        options=options,
        prediction=prediction,
        snapshot=snapshot,
        outcome_history=(),
        created_at=now,
    )

    assert advice.ranking[0].option_id == "a"
    assert advice.ranking[0].wellbeing_score is None
    assert advice.ranking[0].goal_alignment is None
