"""Test deterministic Predict Me scoring without providers or persistence."""

from datetime import UTC, datetime

import pytest
from soulmate_core.decisions import DecisionPredictor, resolution_evidence
from soulmate_core.domain import (
    DecisionEvent,
    DecisionOption,
    DecisionResolution,
    DecisionStatus,
    DerivedModel,
    Preference,
    UserModelSnapshot,
)


def _fixture() -> tuple[DecisionEvent, tuple[DecisionOption, ...], UserModelSnapshot, datetime]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    decision = DecisionEvent(
        "decision_test",
        "profile_test",
        "career",
        "Which role would I choose?",
        {},
        DecisionStatus.OPEN,
        now,
    )
    options = (
        DecisionOption(
            "option_office", decision.id, "Office", "Office role", {"work.remote": -1.0}, 1.0
        ),
        DecisionOption(
            "option_remote", decision.id, "Remote", "Remote role", {"work.remote": 1.0}, 1.0
        ),
    )
    preference = Preference(
        "work.remote", 0.9, 0.1, 0.9, {"domain": "career"}, ("evidence_remote",), now, 3
    )
    snapshot = UserModelSnapshot(
        "profile_test", 3, "personal-model-v1", 1, DerivedModel((preference,), (), (), ()), now
    )
    return decision, options, snapshot, now


def test_predictor_ranks_preferences_and_records_snapshot_and_evidence() -> None:
    decision, options, snapshot, now = _fixture()
    prediction = DecisionPredictor().predict(
        prediction_id="prediction_test",
        decision=decision,
        options=options,
        snapshot=snapshot,
        history=(),
        created_at=now,
    )

    assert prediction.ranking[0].option_id == "option_remote"
    assert sum(item.probability for item in prediction.ranking) == pytest.approx(1.0)
    assert prediction.important_factors == ("work.remote",)
    assert prediction.supporting_evidence_ids == ("evidence_remote",)
    assert prediction.model_snapshot_version == 3


def test_resolution_creates_relative_actual_choice_evidence() -> None:
    decision, options, _, now = _fixture()
    resolution = DecisionResolution(
        "resolution_test", decision.id, "option_office", "event_resolution", now
    )

    evidence = resolution_evidence(
        resolution=resolution,
        decision=decision,
        options=options,
        profile_id="profile_test",
        created_at=now,
    )

    assert len(evidence) == 1
    assert evidence[0].target_key == "work.remote"
    assert evidence[0].value == -1.0
    assert evidence[0].source_type == "actual_choice"
