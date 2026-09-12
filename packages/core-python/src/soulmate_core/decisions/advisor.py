"""Deterministic wellbeing-aware recommendations kept separate from prediction."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from soulmate_core.decisions.predictor import ResolvedDecision
from soulmate_core.domain import (
    AdviceRankingItem,
    Constraint,
    DecisionAdvice,
    DecisionEvent,
    DecisionOption,
    DecisionOutcome,
    DecisionPrediction,
    Goal,
    UserModelSnapshot,
)

ADVICE_ALGORITHM_VERSION = "decision-advisor-v1:behavior-v1:wellbeing-v1:goals-v1"


@dataclass(frozen=True, slots=True)
class OutcomeHistory:
    resolved: ResolvedDecision
    outcome: DecisionOutcome


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = left.keys() & right.keys()
    if not keys:
        return 0.0
    dot = sum(left[key] * right[key] for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _direction(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else -1.0
    if isinstance(value, (int, float)):
        return max(-1.0, min(1.0, float(value)))
    return 1.0


def _wellbeing(
    option: DecisionOption,
    decision: DecisionEvent,
    history: Sequence[OutcomeHistory],
) -> tuple[float | None, tuple[str, ...]]:
    weighted_signal = 0.0
    total_weight = 0.0
    support: list[str] = []
    for item in history:
        chosen = next(
            candidate
            for candidate in item.resolved.options
            if candidate.id == item.resolved.resolution.chosen_option_id
        )
        similarity = _cosine(option.features, chosen.features)
        if similarity == 0.0:
            continue
        domain_weight = (
            1.0 if decision.domain.casefold() == item.resolved.decision.domain.casefold() else 0.5
        )
        weight = abs(similarity) * domain_weight
        satisfaction_signal = 2.0 * item.outcome.satisfaction - 1.0
        regret_adjustment = -0.35 if item.outcome.regret else 0.0
        outcome_signal = max(-1.0, min(1.0, satisfaction_signal + regret_adjustment))
        weighted_signal += weight * similarity * outcome_signal
        total_weight += weight
        support.append(item.outcome.id)
    if total_weight == 0.0:
        return None, ()
    return 0.5 + 0.5 * weighted_signal / total_weight, tuple(dict.fromkeys(support))


def _goal_alignment(option: DecisionOption, snapshot: UserModelSnapshot) -> float | None:
    values: list[tuple[float, float]] = []
    records: list[Goal | Constraint] = [*snapshot.model.goals, *snapshot.model.constraints]
    for record in records:
        if record.key in option.features:
            compatibility = 0.5 + 0.5 * option.features[record.key] * _direction(record.value)
            values.append((compatibility, record.confidence))
    total = sum(weight for _, weight in values)
    return None if total == 0.0 else sum(value * weight for value, weight in values) / total


class DecisionAdvisor:
    """Combine observed behavior, reported outcomes, goals, and constraints."""

    def advise(
        self,
        *,
        advice_id: str,
        decision: DecisionEvent,
        options: Sequence[DecisionOption],
        prediction: DecisionPrediction,
        snapshot: UserModelSnapshot,
        outcome_history: Sequence[OutcomeHistory],
        created_at: datetime,
    ) -> DecisionAdvice:
        if decision.profile_id != snapshot.profile_id or prediction.decision_id != decision.id:
            raise ValueError("Advice inputs must belong to the same profile decision.")
        probabilities = {item.option_id: item.probability for item in prediction.ranking}
        if len(options) < 2 or set(probabilities) != {item.id for item in options}:
            raise ValueError("Advice requires the prediction ranking for every decision option.")

        rankings: list[AdviceRankingItem] = []
        support_by_option: dict[str, tuple[str, ...]] = {}
        for option in options:
            wellbeing, support = _wellbeing(option, decision, outcome_history)
            goal_alignment = _goal_alignment(option, snapshot)
            components = [(probabilities[option.id], 0.35)]
            if wellbeing is not None:
                components.append((wellbeing, 0.45))
            if goal_alignment is not None:
                components.append((goal_alignment, 0.2))
            weight = sum(item_weight for _, item_weight in components)
            score = sum(value * item_weight for value, item_weight in components) / weight
            rankings.append(
                AdviceRankingItem(
                    option_id=option.id,
                    recommendation_score=score,
                    behavioral_probability=probabilities[option.id],
                    wellbeing_score=wellbeing,
                    goal_alignment=goal_alignment,
                )
            )
            support_by_option[option.id] = support
        ordered = tuple(
            sorted(rankings, key=lambda item: (-item.recommendation_score, item.option_id))
        )
        predicted = prediction.ranking[0].option_id
        recommended = ordered[0].option_id
        supporting_outcomes = support_by_option[recommended]
        rationale = [f"Behavioral prediction currently favors option {predicted}."]
        if ordered[0].wellbeing_score is not None:
            rationale.append("Reported outcomes from similar choices informed this recommendation.")
        if ordered[0].goal_alignment is not None:
            rationale.append("Known goals and constraints informed this recommendation.")
        if predicted != recommended:
            rationale.append(
                f"Outcome and goal evidence shifts the recommendation to option {recommended}."
            )
        else:
            rationale.append("The recommendation agrees with the current behavioral prediction.")
        margin = ordered[0].recommendation_score - ordered[1].recommendation_score
        evidence_quality = min(1.0, len(supporting_outcomes) / 3.0)
        confidence = min(
            1.0,
            0.4 * prediction.confidence + 0.35 * evidence_quality + 0.25 * min(1.0, margin * 2),
        )
        return DecisionAdvice(
            id=advice_id,
            decision_id=decision.id,
            profile_id=decision.profile_id,
            behavioral_prediction_id=prediction.id,
            ranking=ordered,
            confidence=confidence,
            rationale=tuple(rationale),
            supporting_outcome_ids=supporting_outcomes,
            model_snapshot_version=snapshot.version,
            algorithm_version=ADVICE_ALGORITHM_VERSION,
            created_at=created_at,
        )
