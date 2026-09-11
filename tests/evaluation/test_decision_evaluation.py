"""Test reproducible Phase 5 decision evaluation."""

import json
from pathlib import Path

import pytest
from soulmate_core.evaluation import (
    PredictionObservation,
    evaluate_dataset,
    evaluate_predictions,
    load_dataset,
)


@pytest.mark.evaluation
def test_metrics_include_accuracy_scoring_rules_and_calibration() -> None:
    observations = (
        PredictionObservation("a", {"a": 0.8, "b": 0.2}),
        PredictionObservation("b", {"a": 0.6, "b": 0.4}),
    )

    metrics = evaluate_predictions(observations, bin_count=5)

    assert metrics.sample_count == 2
    assert metrics.accuracy == 0.5
    assert metrics.top_2_accuracy == 1.0
    assert metrics.log_loss == pytest.approx(0.5697171416)
    assert metrics.brier_score == pytest.approx(0.4)
    assert metrics.calibration_error == pytest.approx(0.4)


@pytest.mark.evaluation
def test_packaged_dataset_produces_reproducible_baseline_comparison() -> None:
    dataset = load_dataset()

    first = evaluate_dataset(dataset)
    second = evaluate_dataset(dataset)

    assert first == second
    assert first.dataset_version == "synthetic-owner-v1"
    assert set(first.metrics) == {
        "random",
        "llm_only",
        "memory_only",
        "personal_model",
        "decision_model",
    }
    assert first.metrics["decision_model"].accuracy > first.metrics["personal_model"].accuracy
    assert first.metrics["decision_model"].log_loss < first.metrics["random"].log_loss


@pytest.mark.evaluation
def test_dataset_validation_rejects_choice_outside_options(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps(
            {
                "dataset_version": "invalid-v1",
                "preferences": [],
                "decisions": [
                    {
                        "id": "d1",
                        "domain": "test",
                        "options": [
                            {"id": "a", "features": {"quality": 1.0}},
                            {"id": "b", "features": {"quality": -1.0}},
                        ],
                        "chosen_option_id": "missing",
                        "llm_only_probabilities": {"a": 0.5, "b": 0.5},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="chosen option"):
        load_dataset(path)
