"""Deterministic evidence aggregation for the Phase 2 Personal Model."""

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from soulmate_core.domain.models import (
    Constraint,
    DerivedModel,
    Evidence,
    EvidenceTargetType,
    Fact,
    Goal,
    Preference,
)

ALGORITHM_VERSION = "personal-model-v1:evidence-weights-v1"

DEFAULT_SOURCE_WEIGHTS: Mapping[str, float] = {
    "casual_inference": 0.25,
    "explicit_statement": 0.6,
    "hypothetical_scenario": 0.5,
    "pairwise_calibration": 0.75,
    "actual_choice": 0.9,
    "repeated_actual_choices": 1.0,
    "user_correction": 1.0,
    "outcome_feedback": 1.0,
    "regret_feedback": 1.0,
}


@dataclass(frozen=True, slots=True)
class EvidenceWeightingStrategy:
    """Versioned source reliability configuration for deterministic rebuilds."""

    version: str
    source_weights: Mapping[str, float]
    default_source_weight: float = 0.5

    def __post_init__(self) -> None:
        weights = (*self.source_weights.values(), self.default_source_weight)
        if not self.version:
            raise ValueError("Evidence weighting strategy version must not be empty.")
        if any(not 0.0 <= weight <= 1.0 for weight in weights):
            raise ValueError("Evidence source weights must be between 0 and 1.")

    def weight(self, evidence: Evidence) -> float:
        source_weight = self.source_weights.get(evidence.source_type, self.default_source_weight)
        return source_weight * evidence.strength * evidence.confidence


DEFAULT_WEIGHTING_STRATEGY = EvidenceWeightingStrategy(
    version="evidence-weights-v1", source_weights=DEFAULT_SOURCE_WEIGHTS
)


def _context_key(context: Mapping[str, object]) -> str:
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _group(
    evidence: Sequence[Evidence],
) -> dict[tuple[EvidenceTargetType, str, str], list[Evidence]]:
    grouped: dict[tuple[EvidenceTargetType, str, str], list[Evidence]] = defaultdict(list)
    for item in evidence:
        grouped[(item.target_type, item.target_key, _context_key(item.context))].append(item)
    return grouped


def _ordered(items: Sequence[Evidence]) -> list[Evidence]:
    return sorted(items, key=lambda item: (item.created_at, item.id))


def _confidence(total_weight: float) -> float:
    return total_weight / (total_weight + 1.0)


def _preference(
    key: str,
    items: Sequence[Evidence],
    strategy: EvidenceWeightingStrategy,
) -> Preference:
    ordered = _ordered(items)
    updated_at = ordered[-1].created_at
    weights = [strategy.weight(item) for item in ordered]
    total = sum(weights)
    value = (
        0.0
        if total == 0.0
        else sum(
            cast(float, item.value) * weight for item, weight in zip(ordered, weights, strict=True)
        )
        / total
    )
    agreement = (
        1.0
        if total == 0.0
        else 1.0
        - sum(
            weight * abs(cast(float, item.value) - value) / 2.0
            for item, weight in zip(ordered, weights, strict=True)
        )
        / total
    )
    confidence = _confidence(total) * agreement
    return Preference(
        key=key,
        value=value,
        uncertainty=1.0 - confidence,
        confidence=confidence,
        context=dict(ordered[0].context),
        supporting_evidence_ids=tuple(item.id for item in ordered),
        updated_at=updated_at,
        model_version=0,
    )


def _categorical[DerivedRecord: (Fact, Goal, Constraint)](
    record_type: type[DerivedRecord],
    key: str,
    items: Sequence[Evidence],
    strategy: EvidenceWeightingStrategy,
) -> DerivedRecord:
    ordered = _ordered(items)
    selected = max(ordered, key=lambda item: (strategy.weight(item), item.created_at, item.id))
    return record_type(
        key=key,
        value=selected.value,
        confidence=_confidence(sum(strategy.weight(item) for item in ordered)),
        context=dict(selected.context),
        supporting_evidence_ids=tuple(item.id for item in ordered),
        updated_at=ordered[-1].created_at,
        model_version=0,
    )


def aggregate_evidence(
    evidence: Sequence[Evidence],
    strategy: EvidenceWeightingStrategy = DEFAULT_WEIGHTING_STRATEGY,
) -> DerivedModel:
    """Aggregate fixed evidence into stable, sorted model content without an LLM."""

    preferences: list[Preference] = []
    facts: list[Fact] = []
    goals: list[Goal] = []
    constraints: list[Constraint] = []
    for (target_type, key, _), items in sorted(_group(evidence).items(), key=lambda item: item[0]):
        if target_type is EvidenceTargetType.PREFERENCE:
            preferences.append(_preference(key, items, strategy))
        elif target_type is EvidenceTargetType.FACT:
            facts.append(_categorical(Fact, key, items, strategy))
        elif target_type is EvidenceTargetType.GOAL:
            goals.append(_categorical(Goal, key, items, strategy))
        else:
            constraints.append(_categorical(Constraint, key, items, strategy))
    return DerivedModel(tuple(preferences), tuple(facts), tuple(goals), tuple(constraints))
