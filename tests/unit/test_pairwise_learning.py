"""Test online pairwise and contextual preference behavior."""

from datetime import UTC, datetime, timedelta

from soulmate_core.decisions import DecisionPredictor, ResolvedDecision
from soulmate_core.domain import (
    DecisionEvent,
    DecisionOption,
    DecisionResolution,
    DecisionStatus,
    DerivedModel,
    Preference,
    UserModelSnapshot,
)
from soulmate_core.learning import OnlinePairwiseLearner, PairwiseComparison


def test_pairwise_updates_learn_global_domain_and_context_weights() -> None:
    learner = OnlinePairwiseLearner()
    comparison = PairwiseComparison(
        "travel",
        {"urgency": "high"},
        {"speed": 1.0, "cost": 0.5},
        {"speed": -1.0, "cost": -0.5},
    )

    model = learner.fit((comparison, comparison, comparison))

    urgent = model.effective_weights("travel", {"urgency": "high"})
    leisurely = model.effective_weights("travel", {"urgency": "low"})
    assert urgent["speed"] > leisurely["speed"] > 0.0
    assert model.utility({"speed": 1.0}, "travel", {"urgency": "high"}) > 0.0
    assert {item.scope for item in model.weights} == {"global", "domain", "context"}


def test_predictor_combines_global_domain_and_exact_context_preferences() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    decision = DecisionEvent(
        "decision_context",
        "profile_test",
        "travel",
        "Fast or slow?",
        {"urgency": "high"},
        DecisionStatus.OPEN,
        now,
    )
    options = (
        DecisionOption("option_slow", decision.id, "Slow", "Slow", {"speed": -1.0}, 1.0),
        DecisionOption("option_fast", decision.id, "Fast", "Fast", {"speed": 1.0}, 1.0),
    )
    preferences = (
        Preference("speed", -0.8, 0.1, 0.9, {}, ("global",), now, 1),
        Preference("speed", 0.2, 0.1, 0.9, {"domain": "travel"}, ("domain",), now, 1),
        Preference(
            "speed",
            1.0,
            0.0,
            1.0,
            {"domain": "travel", "urgency": "high"},
            ("context",),
            now,
            1,
        ),
    )
    snapshot = UserModelSnapshot(
        "profile_test", 1, "personal-model-v1", 3, DerivedModel(preferences, (), (), ()), now
    )

    prediction = DecisionPredictor().predict(
        prediction_id="prediction_context",
        decision=decision,
        options=options,
        snapshot=snapshot,
        history=(),
        created_at=now,
    )

    assert prediction.ranking[0].option_id == "option_fast"
    assert prediction.supporting_evidence_ids == ("context", "domain", "global")
    assert "contextual-v1" in prediction.algorithm_version


def test_predictor_uses_pairwise_history_when_snapshot_has_no_preferences() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    historical = DecisionEvent(
        "decision_old", "profile_test", "tools", "Old choice", {}, DecisionStatus.RESOLVED, now
    )
    old_options = (
        DecisionOption("old_slow", historical.id, "Slow", "Slow", {"speed": -1.0}, 1.0),
        DecisionOption("old_fast", historical.id, "Fast", "Fast", {"speed": 1.0}, 1.0),
    )
    resolution = DecisionResolution("resolution_old", historical.id, "old_fast", "event_old", now)
    current = DecisionEvent(
        "decision_new",
        "profile_test",
        "tools",
        "New choice",
        {},
        DecisionStatus.OPEN,
        now + timedelta(days=1),
    )
    current_options = (
        DecisionOption("new_slow", current.id, "Slow", "Slow", {"speed": -1.0}, 1.0),
        DecisionOption("new_fast", current.id, "Fast", "Fast", {"speed": 1.0}, 1.0),
    )
    snapshot = UserModelSnapshot(
        "profile_test", 1, "personal-model-v1", 0, DerivedModel((), (), (), ()), now
    )

    prediction = DecisionPredictor().predict(
        prediction_id="prediction_new",
        decision=current,
        options=current_options,
        snapshot=snapshot,
        history=(ResolvedDecision(historical, old_options, resolution),),
        created_at=now + timedelta(days=1),
    )

    assert prediction.ranking[0].option_id == "new_fast"
    assert prediction.important_factors == ("speed",)
    assert prediction.supporting_evidence_ids == ()
