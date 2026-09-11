"""Offline evaluation datasets, baselines, and sequential learning runner."""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import cast

from soulmate_core.decisions import DECISION_ALGORITHM_VERSION, DecisionPredictor, ResolvedDecision
from soulmate_core.domain import (
    DecisionEvent,
    DecisionOption,
    DecisionResolution,
    DecisionStatus,
    DerivedModel,
    Preference,
    UserModelSnapshot,
)
from soulmate_core.evaluation.metrics import (
    EvaluationMetrics,
    PredictionObservation,
    evaluate_predictions,
)
from soulmate_core.learning import (
    PAIRWISE_ALGORITHM_VERSION,
)

EVALUATION_ALGORITHM_VERSION = "evaluation-v1"
DEFAULT_DATASET_RESOURCE = "data/synthetic-decisions-v1.json"


@dataclass(frozen=True, slots=True)
class EvaluationPreference:
    key: str
    value: float
    confidence: float
    context: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class EvaluationOption:
    id: str
    features: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class EvaluationDecision:
    id: str
    domain: str
    context: Mapping[str, object]
    options: tuple[EvaluationOption, ...]
    chosen_option_id: str
    llm_only_probabilities: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    version: str
    preferences: tuple[EvaluationPreference, ...]
    decisions: tuple[EvaluationDecision, ...]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset_version: str
    evaluation_version: str
    decision_algorithm_version: str
    pairwise_algorithm_version: str
    metrics: Mapping[str, EvaluationMetrics]

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))


def default_dataset_path() -> Path:
    """Return the packaged synthetic dataset path in a source or wheel install."""

    resource = files("soulmate_core.evaluation").joinpath(DEFAULT_DATASET_RESOURCE)
    return Path(str(resource))


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object with string keys.")
    return cast(dict[str, object], value)


def _number(value: object, field: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric.")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return result


def _probabilities(raw: object, option_ids: set[str], field: str) -> dict[str, float]:
    values = _mapping(raw, field)
    if set(values) != option_ids:
        raise ValueError(f"{field} must include every option exactly once.")
    result = {key: _number(value, field, minimum=0.0, maximum=1.0) for key, value in values.items()}
    if not math.isclose(sum(result.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"{field} probabilities must sum to one.")
    return result


def load_dataset(path: Path | None = None) -> EvaluationDataset:
    """Load and strictly validate a synthetic or pseudonymous JSON dataset."""

    resolved = path if path is not None else default_dataset_path()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Evaluation dataset could not be read as JSON.") from exc
    root = _mapping(raw, "dataset")
    version = root.get("dataset_version")
    if not isinstance(version, str) or not version:
        raise ValueError("dataset_version must be a non-empty string.")
    raw_preferences = root.get("preferences")
    raw_decisions = root.get("decisions")
    if (
        not isinstance(raw_preferences, list)
        or not isinstance(raw_decisions, list)
        or not raw_decisions
    ):
        raise ValueError("Dataset preferences and non-empty decisions must be arrays.")
    preferences = tuple(
        _load_preference(value, index) for index, value in enumerate(raw_preferences)
    )
    decisions: list[EvaluationDecision] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(raw_decisions):
        decision = _load_decision(value, index)
        if decision.id in seen_ids:
            raise ValueError("Decision IDs must be unique.")
        decisions.append(decision)
        seen_ids.add(decision.id)
    return EvaluationDataset(version, preferences, tuple(decisions))


def _load_preference(value: object, index: int) -> EvaluationPreference:
    item = _mapping(value, f"preferences[{index}]")
    key = item.get("key")
    if not isinstance(key, str) or not key:
        raise ValueError("Preference keys must be non-empty strings.")
    return EvaluationPreference(
        key,
        _number(item.get("value"), "preference.value", minimum=-1.0, maximum=1.0),
        _number(item.get("confidence"), "preference.confidence", minimum=0.0, maximum=1.0),
        _mapping(item.get("context", {}), "preference.context"),
    )


def _load_decision(value: object, index: int) -> EvaluationDecision:
    item = _mapping(value, f"decisions[{index}]")
    decision_id = item.get("id")
    domain = item.get("domain")
    chosen = item.get("chosen_option_id")
    raw_options = item.get("options")
    if not isinstance(decision_id, str) or not decision_id:
        raise ValueError("Decision IDs must be non-empty strings.")
    if not isinstance(domain, str) or not domain:
        raise ValueError("Decision domains must be non-empty strings.")
    if not isinstance(raw_options, list) or len(raw_options) < 2:
        raise ValueError("Each decision must contain at least two options.")
    options = tuple(
        _load_option(option, index, option_index) for option_index, option in enumerate(raw_options)
    )
    option_ids = {option.id for option in options}
    if len(option_ids) != len(options) or not isinstance(chosen, str) or chosen not in option_ids:
        raise ValueError("Option IDs must be unique and include the chosen option.")
    return EvaluationDecision(
        decision_id,
        domain,
        _mapping(item.get("context", {}), "decision.context"),
        options,
        chosen,
        _probabilities(item.get("llm_only_probabilities"), option_ids, "llm baseline"),
    )


def _load_option(value: object, decision_index: int, option_index: int) -> EvaluationOption:
    item = _mapping(value, f"decisions[{decision_index}].options[{option_index}]")
    option_id = item.get("id")
    if not isinstance(option_id, str) or not option_id:
        raise ValueError("Option IDs must be non-empty strings.")
    raw_features = _mapping(item.get("features"), "option.features")
    features = {
        key: _number(number, "option feature", minimum=-1.0, maximum=1.0)
        for key, number in raw_features.items()
    }
    if not features:
        raise ValueError("Option features must not be empty.")
    return EvaluationOption(option_id, features)


def _softmax(utilities: Sequence[float]) -> tuple[float, ...]:
    maximum = max(utilities)
    values = [math.exp(value - maximum) for value in utilities]
    total = sum(values)
    return tuple(value / total for value in values)


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = left.keys() & right.keys()
    dot = sum(left[key] * right[key] for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not keys or left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def evaluate_dataset(dataset: EvaluationDataset) -> EvaluationReport:
    """Evaluate frozen baselines and an online Decision Model in chronological order."""

    names = ("random", "llm_only", "memory_only", "personal_model", "decision_model")
    observations: dict[str, list[PredictionObservation]] = {name: [] for name in names}
    history: list[tuple[EvaluationDecision, EvaluationOption]] = []
    resolved_history: list[ResolvedDecision] = []
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    preferences = tuple(
        Preference(
            item.key,
            item.value,
            1.0 - item.confidence,
            item.confidence,
            dict(item.context),
            (f"fixture_preference_{index}",),
            created_at,
            1,
        )
        for index, item in enumerate(dataset.preferences)
    )
    snapshot = UserModelSnapshot(
        "evaluation_profile",
        1,
        "evaluation-personal-model-v1",
        len(preferences),
        DerivedModel(preferences, (), (), ()),
        created_at,
    )
    predictor = DecisionPredictor()
    for index, decision in enumerate(dataset.decisions):
        evaluated_at = created_at + timedelta(seconds=index)
        domain_decision, domain_options = _domain_records(decision, evaluated_at)
        random = {option.id: 1.0 / len(decision.options) for option in decision.options}
        memory_utilities = [
            _memory_utility(option, decision, history) for option in decision.options
        ]
        memory_probabilities = _softmax(memory_utilities)
        memory = {
            option.id: probability
            for option, probability in zip(decision.options, memory_probabilities, strict=True)
        }
        personal_prediction = predictor.predict(
            prediction_id=f"personal_{decision.id}",
            decision=domain_decision,
            options=domain_options,
            snapshot=snapshot,
            history=(),
            created_at=evaluated_at,
        )
        decision_prediction = predictor.predict(
            prediction_id=f"decision_{decision.id}",
            decision=domain_decision,
            options=domain_options,
            snapshot=snapshot,
            history=tuple(resolved_history),
            created_at=evaluated_at,
        )
        personal = {item.option_id: item.probability for item in personal_prediction.ranking}
        decision_model = {item.option_id: item.probability for item in decision_prediction.ranking}
        predictions = {
            "random": random,
            "llm_only": decision.llm_only_probabilities,
            "memory_only": memory,
            "personal_model": personal,
            "decision_model": decision_model,
        }
        reported_confidence = {
            "personal_model": personal_prediction.confidence,
            "decision_model": decision_prediction.confidence,
        }
        for name, probabilities in predictions.items():
            observations[name].append(
                PredictionObservation(
                    decision.chosen_option_id,
                    probabilities,
                    reported_confidence.get(name),
                )
            )
        chosen = next(
            option for option in decision.options if option.id == decision.chosen_option_id
        )
        resolved_decision = DecisionEvent(
            domain_decision.id,
            domain_decision.profile_id,
            domain_decision.domain,
            domain_decision.question,
            domain_decision.context,
            DecisionStatus.RESOLVED,
            domain_decision.created_at,
        )
        resolution = DecisionResolution(
            f"resolution_{decision.id}",
            decision.id,
            chosen.id,
            f"event_{decision.id}",
            evaluated_at,
        )
        resolved_history.append(ResolvedDecision(resolved_decision, domain_options, resolution))
        history.append((decision, chosen))
    return EvaluationReport(
        dataset.version,
        EVALUATION_ALGORITHM_VERSION,
        DECISION_ALGORITHM_VERSION,
        PAIRWISE_ALGORITHM_VERSION,
        {name: evaluate_predictions(items) for name, items in observations.items()},
    )


def _domain_records(
    decision: EvaluationDecision, created_at: datetime
) -> tuple[DecisionEvent, tuple[DecisionOption, ...]]:
    event = DecisionEvent(
        decision.id,
        "evaluation_profile",
        decision.domain,
        f"Synthetic evaluation decision {decision.id}",
        dict(decision.context),
        DecisionStatus.OPEN,
        created_at,
    )
    options = tuple(
        DecisionOption(
            item.id,
            decision.id,
            item.id,
            f"Synthetic option {item.id}",
            dict(item.features),
            1.0,
        )
        for item in decision.options
    )
    return event, options


def _memory_utility(
    option: EvaluationOption,
    decision: EvaluationDecision,
    history: Sequence[tuple[EvaluationDecision, EvaluationOption]],
) -> float:
    matches = [
        _cosine(option.features, chosen.features)
        for historical, chosen in history
        if historical.domain.casefold() == decision.domain.casefold()
    ]
    return sum(matches) / len(matches) if matches else 0.0
