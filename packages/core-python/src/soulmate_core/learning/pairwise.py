"""Deterministic online pairwise preference learning."""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

PAIRWISE_ALGORITHM_VERSION = "bradley-terry-online-v1"
CONTEXT_SCOPE_WEIGHTS: Mapping[str, float] = {
    "global": 0.2,
    "domain": 0.3,
    "context": 0.5,
}


def canonical_context(domain: str, context: Mapping[str, object]) -> str:
    """Return a stable key for an exact decision context."""

    value = {**context, "domain": domain}
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class PairwiseComparison:
    """A chosen feature vector compared with one rejected alternative."""

    domain: str
    context: Mapping[str, object]
    chosen_features: Mapping[str, float]
    alternative_features: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class LearnedWeight:
    scope: str
    scope_key: str
    feature: str
    value: float
    observations: int


@dataclass(frozen=True, slots=True)
class PairwisePreferenceModel:
    """Immutable learned weights usable without an LLM or persistence adapter."""

    weights: tuple[LearnedWeight, ...]
    algorithm_version: str = PAIRWISE_ALGORITHM_VERSION

    def utility(
        self,
        features: Mapping[str, float],
        domain: str,
        context: Mapping[str, object],
    ) -> float:
        return sum(
            weight * features.get(feature, 0.0)
            for feature, weight in self.effective_weights(domain, context).items()
        )

    def effective_weights(self, domain: str, context: Mapping[str, object]) -> dict[str, float]:
        """Combine applicable global, domain, and exact-context weights."""

        context_key = canonical_context(domain, context)
        applicable = {
            "global": "*",
            "domain": domain.casefold(),
            "context": context_key,
        }
        result: dict[str, float] = {}
        for item in self.weights:
            if applicable[item.scope] != item.scope_key:
                continue
            result[item.feature] = result.get(item.feature, 0.0) + (
                CONTEXT_SCOPE_WEIGHTS[item.scope] * item.value
            )
        return result


class OnlinePairwiseLearner:
    """Learn Bradley-Terry-style weights with reproducible online SGD updates."""

    def __init__(self, *, learning_rate: float = 0.35, regularization: float = 0.01) -> None:
        if learning_rate <= 0.0 or regularization < 0.0:
            raise ValueError("Learning rate must be positive and regularization non-negative.")
        self._learning_rate = learning_rate
        self._regularization = regularization
        self._weights: dict[tuple[str, str, str], float] = {}
        self._observations: dict[tuple[str, str, str], int] = {}

    def update(self, comparison: PairwiseComparison) -> None:
        """Apply one chosen-over-alternative update in global and matching contexts."""

        features = sorted(
            comparison.chosen_features.keys() | comparison.alternative_features.keys()
        )
        deltas = {
            feature: comparison.chosen_features.get(feature, 0.0)
            - comparison.alternative_features.get(feature, 0.0)
            for feature in features
        }
        scopes = [
            ("global", "*"),
            ("domain", comparison.domain.casefold()),
        ]
        if comparison.context:
            scopes.append(("context", canonical_context(comparison.domain, comparison.context)))
        margin = sum(
            CONTEXT_SCOPE_WEIGHTS[scope]
            * self._weights.get((scope, scope_key, feature), 0.0)
            * delta
            for scope, scope_key in scopes
            for feature, delta in deltas.items()
        )
        probability = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, margin))))
        error = 1.0 - probability
        for scope, scope_key in scopes:
            scope_weight = CONTEXT_SCOPE_WEIGHTS[scope]
            for feature, delta in deltas.items():
                if abs(delta) < 1e-12:
                    continue
                key = (scope, scope_key, feature)
                current = self._weights.get(key, 0.0)
                gradient = scope_weight * error * delta - self._regularization * current
                self._weights[key] = max(-4.0, min(4.0, current + self._learning_rate * gradient))
                self._observations[key] = self._observations.get(key, 0) + 1

    def fit(self, comparisons: Sequence[PairwiseComparison]) -> PairwisePreferenceModel:
        for comparison in comparisons:
            self.update(comparison)
        return self.model()

    def model(self) -> PairwisePreferenceModel:
        return PairwisePreferenceModel(
            tuple(
                LearnedWeight(*key, value, self._observations[key])
                for key, value in sorted(self._weights.items())
            )
        )
