"""Reproducible multiclass prediction metrics and confidence diagnostics."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PredictionObservation:
    actual_option_id: str
    probabilities: Mapping[str, float]
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.actual_option_id not in self.probabilities or not self.probabilities:
            raise ValueError("The actual option must have a predicted probability.")
        if any(not math.isfinite(value) or value < 0.0 for value in self.probabilities.values()):
            raise ValueError("Prediction probabilities must be finite and non-negative.")
        if not math.isclose(sum(self.probabilities.values()), 1.0, abs_tol=1e-9):
            raise ValueError("Prediction probabilities must sum to one.")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Prediction confidence must be between zero and one.")


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower_bound: float
    upper_bound: float
    count: int
    mean_confidence: float
    accuracy: float


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    sample_count: int
    accuracy: float
    top_2_accuracy: float
    log_loss: float
    brier_score: float
    calibration_error: float
    calibration_bins: tuple[CalibrationBin, ...]


def _ranking(probabilities: Mapping[str, float]) -> list[str]:
    return sorted(probabilities, key=lambda key: (-probabilities[key], key))


def evaluate_predictions(
    observations: Sequence[PredictionObservation], *, bin_count: int = 10
) -> EvaluationMetrics:
    """Calculate accuracy, proper scoring rules, and top-label calibration."""

    if not observations or bin_count < 1:
        raise ValueError("Evaluation needs observations and at least one calibration bin.")
    count = len(observations)
    correct = 0
    top_2_correct = 0
    log_loss = 0.0
    brier = 0.0
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bin_count)]
    for observation in observations:
        ranking = _ranking(observation.probabilities)
        is_correct = ranking[0] == observation.actual_option_id
        correct += int(is_correct)
        top_2_correct += int(observation.actual_option_id in ranking[:2])
        actual_probability = max(observation.probabilities[observation.actual_option_id], 1e-15)
        log_loss -= math.log(actual_probability)
        brier += sum(
            (probability - float(option_id == observation.actual_option_id)) ** 2
            for option_id, probability in observation.probabilities.items()
        )
        confidence = (
            observation.confidence
            if observation.confidence is not None
            else observation.probabilities[ranking[0]]
        )
        index = min(int(confidence * bin_count), bin_count - 1)
        buckets[index].append((confidence, is_correct))
    calibration_bins = tuple(
        CalibrationBin(
            lower_bound=index / bin_count,
            upper_bound=(index + 1) / bin_count,
            count=len(bucket),
            mean_confidence=sum(value for value, _ in bucket) / len(bucket),
            accuracy=sum(float(value) for _, value in bucket) / len(bucket),
        )
        for index, bucket in enumerate(buckets)
        if bucket
    )
    calibration_error = sum(
        item.count / count * abs(item.accuracy - item.mean_confidence) for item in calibration_bins
    )
    return EvaluationMetrics(
        sample_count=count,
        accuracy=correct / count,
        top_2_accuracy=top_2_correct / count,
        log_loss=log_loss / count,
        brier_score=brier / count,
        calibration_error=calibration_error,
        calibration_bins=calibration_bins,
    )
