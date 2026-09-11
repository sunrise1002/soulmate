"""Provider-independent contextual choice prediction algorithms."""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from soulmate_core.domain import (
    DecisionEvent,
    DecisionOption,
    DecisionPrediction,
    DecisionResolution,
    Evidence,
    EvidenceTargetType,
    OptionProbability,
    Preference,
    UserModelSnapshot,
)
from soulmate_core.learning import (
    CONTEXT_SCOPE_WEIGHTS,
    PAIRWISE_ALGORITHM_VERSION,
    OnlinePairwiseLearner,
    PairwiseComparison,
)

DECISION_ALGORITHM_VERSION = (
    f"decision-predictor-v2:contextual-v1:{PAIRWISE_ALGORITHM_VERSION}:confidence-v2"
)
_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ResolvedDecision:
    decision: DecisionEvent
    options: tuple[DecisionOption, ...]
    resolution: DecisionResolution


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(value.casefold().replace("_", " ").replace(".", " ")))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)


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


def _decision_similarity(
    current: DecisionEvent,
    current_options: Sequence[DecisionOption],
    historical: ResolvedDecision,
) -> float:
    domain = 1.0 if current.domain.casefold() == historical.decision.domain.casefold() else 0.0
    question = _jaccard(_tokens(current.question), _tokens(historical.decision.question))
    current_keys = set().union(*(option.features.keys() for option in current_options))
    historical_keys = set().union(*(option.features.keys() for option in historical.options))
    features = _jaccard(current_keys, historical_keys)
    return 0.5 * domain + 0.2 * question + 0.3 * features


@dataclass(frozen=True, slots=True)
class _MatchedPreference:
    value: float
    confidence: float
    uncertainty: float
    supporting_evidence_ids: tuple[str, ...]


def _context_scope(preference: Preference, decision: DecisionEvent) -> str | None:
    context = preference.context
    domain = context.get("domain")
    if domain is not None and str(domain).casefold() != decision.domain.casefold():
        return None
    specific = {key: value for key, value in context.items() if key != "domain"}
    if any(decision.context.get(key) != value for key, value in specific.items()):
        return None
    if specific:
        return "context"
    return "domain" if domain is not None else "global"


def _match_preference(
    feature: str, preferences: Sequence[Preference], decision: DecisionEvent
) -> _MatchedPreference | None:
    feature_tokens = _tokens(feature)
    candidates = [
        (item, scope)
        for item in preferences
        if (item.key == feature or _tokens(item.key) == feature_tokens)
        and (scope := _context_scope(item, decision)) is not None
    ]
    if not candidates:
        return None
    best_by_scope: dict[str, Preference] = {}
    for item, scope in candidates:
        current = best_by_scope.get(scope)
        if current is None or (item.confidence, item.updated_at, item.key) > (
            current.confidence,
            current.updated_at,
            current.key,
        ):
            best_by_scope[scope] = item
    total_weight = sum(CONTEXT_SCOPE_WEIGHTS[scope] for scope in best_by_scope)
    weighted = {scope: CONTEXT_SCOPE_WEIGHTS[scope] / total_weight for scope in best_by_scope}
    return _MatchedPreference(
        value=sum(weighted[scope] * item.value for scope, item in best_by_scope.items()),
        confidence=sum(weighted[scope] * item.confidence for scope, item in best_by_scope.items()),
        uncertainty=sum(
            weighted[scope] * item.uncertainty for scope, item in best_by_scope.items()
        ),
        supporting_evidence_ids=tuple(
            dict.fromkeys(
                evidence_id
                for scope in ("context", "domain", "global")
                if (selected := best_by_scope.get(scope)) is not None
                for evidence_id in selected.supporting_evidence_ids
            )
        ),
    )


def _softmax(utilities: Sequence[float]) -> tuple[float, ...]:
    maximum = max(utilities)
    exponentials = [math.exp(value - maximum) for value in utilities]
    total = sum(exponentials)
    return tuple(value / total for value in exponentials)


class DecisionPredictor:
    """Score structured options against a fixed Personal Model snapshot."""

    def predict(
        self,
        *,
        prediction_id: str,
        decision: DecisionEvent,
        options: Sequence[DecisionOption],
        snapshot: UserModelSnapshot,
        history: Sequence[ResolvedDecision],
        created_at: datetime,
    ) -> DecisionPrediction:
        if decision.profile_id != snapshot.profile_id:
            raise ValueError("Decision and model snapshot must belong to the same profile.")
        if len(options) < 2 or any(option.decision_id != decision.id for option in options):
            raise ValueError("Prediction requires at least two options for the decision.")

        matched: dict[str, _MatchedPreference] = {}
        for feature in sorted(set().union(*(option.features.keys() for option in options))):
            preference = _match_preference(feature, snapshot.model.preferences, decision)
            if preference is not None:
                matched[feature] = preference

        similar = sorted(
            (
                (_decision_similarity(decision, options, item), item)
                for item in history
                if item.decision.id != decision.id
            ),
            key=lambda item: (-item[0], item[1].decision.id),
        )
        similar = [item for item in similar if item[0] > 0.0][:5]
        comparisons: list[PairwiseComparison] = []
        for item in sorted(
            history, key=lambda value: (value.decision.created_at, value.decision.id)
        ):
            chosen = next(
                candidate
                for candidate in item.options
                if candidate.id == item.resolution.chosen_option_id
            )
            comparisons.extend(
                PairwiseComparison(
                    domain=item.decision.domain,
                    context=item.decision.context,
                    chosen_features=chosen.features,
                    alternative_features=alternative.features,
                )
                for alternative in item.options
                if alternative.id != chosen.id
            )
        pairwise = OnlinePairwiseLearner().fit(comparisons)
        learned_weights = pairwise.effective_weights(decision.domain, decision.context)
        utilities: list[float] = []
        contribution_features = matched.keys() | learned_weights.keys()
        contributions: dict[str, list[float]] = {key: [] for key in contribution_features}
        for option in options:
            utility = 0.0
            for feature in contribution_features:
                preference = matched.get(feature)
                model_weight = (
                    preference.value * preference.confidence if preference is not None else 0.0
                )
                contribution = option.features.get(feature, 0.0) * (
                    model_weight + learned_weights.get(feature, 0.0)
                )
                utility += contribution
                contributions[feature].append(contribution)
            if similar:
                prior_total = 0.0
                similarity_total = 0.0
                for decision_similarity, item in similar:
                    chosen = next(
                        candidate
                        for candidate in item.options
                        if candidate.id == item.resolution.chosen_option_id
                    )
                    prior_total += decision_similarity * _cosine(option.features, chosen.features)
                    similarity_total += decision_similarity
                utility += 0.25 * prior_total / similarity_total
            utilities.append(utility)

        probabilities = _softmax(utilities)
        ranking = tuple(
            sorted(
                (
                    OptionProbability(option.id, probability, utility)
                    for option, probability, utility in zip(
                        options, probabilities, utilities, strict=True
                    )
                ),
                key=lambda item: (-item.probability, item.option_id),
            )
        )
        factor_impact = {
            feature: max(values) - min(values) for feature, values in contributions.items()
        }
        important = tuple(
            key
            for key, impact in sorted(factor_impact.items(), key=lambda item: (-item[1], item[0]))
            if impact > 0.0
        )[:5]
        all_features = sorted(set().union(*(option.features.keys() for option in options)))
        uncertain = tuple(
            feature
            for feature in all_features
            if (feature not in matched and feature not in learned_weights)
            or (feature in matched and matched[feature].uncertainty >= 0.5)
        )[:5]
        support = tuple(
            dict.fromkeys(
                evidence_id
                for feature in important
                if feature in matched
                for evidence_id in matched[feature].supporting_evidence_ids
            )
        )
        ordered_probabilities = sorted(probabilities, reverse=True)
        top_probability = ordered_probabilities[0]
        coverage = len(matched) / len(all_features) if all_features else 0.0
        preference_quality = (
            sum(item.confidence for item in matched.values()) / len(matched) if matched else 0.0
        )
        consistency = (
            1.0 - sum(item.uncertainty for item in matched.values()) / len(matched)
            if matched
            else 0.0
        )
        extraction_quality = sum(option.feature_confidence for option in options) / len(options)
        history_quality = similar[0][0] if similar else 0.0
        pairwise_coverage = (
            len(learned_weights.keys() & set(all_features)) / len(all_features)
            if all_features
            else 0.0
        )
        quality = (
            0.25 * coverage
            + 0.2 * pairwise_coverage
            + 0.2 * preference_quality
            + 0.15 * consistency
            + 0.15 * extraction_quality
            + 0.05 * history_quality
        )
        chance = 1.0 / len(options)
        confidence = chance + (top_probability - chance) * min(1.0, max(0.0, quality))
        return DecisionPrediction(
            id=prediction_id,
            decision_id=decision.id,
            profile_id=decision.profile_id,
            ranking=ranking,
            confidence=confidence,
            important_factors=important,
            uncertain_factors=uncertain,
            supporting_evidence_ids=support,
            similar_decision_ids=tuple(item.decision.id for _, item in similar),
            model_snapshot_version=snapshot.version,
            algorithm_version=DECISION_ALGORITHM_VERSION,
            created_at=created_at,
        )


def resolution_evidence(
    *,
    resolution: DecisionResolution,
    decision: DecisionEvent,
    options: Sequence[DecisionOption],
    profile_id: str,
    created_at: datetime,
) -> tuple[Evidence, ...]:
    """Convert a resolved choice into relative, provenance-bearing preference evidence."""

    if len(options) < 2 or any(item.decision_id != decision.id for item in options):
        raise ValueError("Resolution learning requires at least two options for the decision.")
    chosen = next((item for item in options if item.id == resolution.chosen_option_id), None)
    if chosen is None or decision.profile_id != profile_id:
        raise ValueError("Resolution must select an option from the profile's decision.")
    alternatives = [item for item in options if item.id != chosen.id]
    result: list[Evidence] = []
    features = sorted(set().union(*(option.features.keys() for option in options)))
    for index, feature in enumerate(features):
        alternative_mean = sum(item.features.get(feature, 0.0) for item in alternatives) / len(
            alternatives
        )
        value = max(-1.0, min(1.0, chosen.features.get(feature, 0.0) - alternative_mean))
        if abs(value) < 1e-12:
            continue
        result.append(
            Evidence(
                id=f"{resolution.id}_evidence_{index}",
                profile_id=profile_id,
                target_type=EvidenceTargetType.PREFERENCE,
                target_key=feature,
                value=value,
                strength=0.9,
                confidence=min(item.feature_confidence for item in options),
                context={"domain": decision.domain},
                source_type="actual_choice",
                source_event_id=resolution.source_event_id,
                extractor_version="decision-resolution-v1",
                created_at=created_at,
            )
        )
    return tuple(result)
