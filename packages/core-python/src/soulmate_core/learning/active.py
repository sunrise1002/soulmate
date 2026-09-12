"""Deterministic uncertainty ranking and active-learning questions."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from soulmate_core.domain import (
    ActiveQuestion,
    ActiveQuestionStatus,
    Evidence,
    EvidenceTargetType,
    Preference,
    QuestionAnswer,
    UserModelSnapshot,
)

ACTIVE_LEARNING_ALGORITHM_VERSION = "active-learning-v1:uncertainty-v1:information-gain-v1"


@dataclass(frozen=True, slots=True)
class UncertaintySignal:
    preference_key: str
    context: dict[str, object]
    uncertainty: float
    confidence: float
    information_value: float


def rank_uncertainties(preferences: Sequence[Preference]) -> tuple[UncertaintySignal, ...]:
    """Rank preferences by uncertainty and the value of obtaining stronger evidence."""

    signals = (
        UncertaintySignal(
            preference_key=item.key,
            context=item.context,
            uncertainty=item.uncertainty,
            confidence=item.confidence,
            information_value=min(1.0, item.uncertainty * (1.25 - 0.25 * item.confidence)),
        )
        for item in preferences
    )
    return tuple(
        sorted(
            signals,
            key=lambda item: (-item.information_value, item.preference_key, repr(item.context)),
        )
    )


def _label(key: str) -> str:
    return key.replace(".", " ").replace("_", " ")


def _context_key(context: dict[str, object]) -> str:
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def generate_active_questions(
    *,
    snapshot: UserModelSnapshot,
    existing: Sequence[ActiveQuestion],
    question_ids: Sequence[str],
    created_at: datetime,
    target_key: str | None = None,
) -> tuple[ActiveQuestion, ...]:
    """Create ranked pairwise questions without an LLM or external dependency."""

    signals = rank_uncertainties(snapshot.model.preferences)
    if target_key is not None:
        targeted = tuple(item for item in signals if item.preference_key == target_key)
        if not targeted:
            return ()
        signals = targeted + tuple(item for item in signals if item.preference_key != target_key)
    existing_pairs = {
        (tuple(sorted(item.preference_keys)), _context_key(item.context)) for item in existing
    }
    candidates: list[tuple[UncertaintySignal, UncertaintySignal | None]] = []
    for index, first in enumerate(signals):
        for other in signals[index + 1 :]:
            if first.context != other.context:
                continue
            if target_key is not None and target_key not in {
                first.preference_key,
                other.preference_key,
            }:
                continue
            pair = (
                tuple(sorted((first.preference_key, other.preference_key))),
                _context_key(first.context),
            )
            if pair not in existing_pairs:
                candidates.append((first, other))
    if not candidates and signals:
        first = signals[0]
        if ((first.preference_key,), _context_key(first.context)) not in existing_pairs:
            candidates.append((first, None))
    candidates.sort(
        key=lambda pair: (
            -(
                pair[0].information_value
                if pair[1] is None
                else (pair[0].information_value + pair[1].information_value) / 2.0
            ),
            pair[0].preference_key,
            "" if pair[1] is None else pair[1].preference_key,
        )
    )
    result: list[ActiveQuestion] = []
    for question_id, (first, second_signal) in zip(question_ids, candidates, strict=False):
        keys: tuple[str, ...]
        if second_signal is None:
            keys = (first.preference_key,)
            option_a_features = {first.preference_key: 1.0}
            option_b_features = {first.preference_key: -1.0}
            option_a_label = f"Prioritize {_label(first.preference_key)}"
            option_b_label = f"Accept less {_label(first.preference_key)} for other benefits"
            score = first.information_value
        else:
            keys = (first.preference_key, second_signal.preference_key)
            option_a_features = {first.preference_key: 1.0, second_signal.preference_key: -1.0}
            option_b_features = {first.preference_key: -1.0, second_signal.preference_key: 1.0}
            option_a_label = f"Prioritize {_label(first.preference_key)}"
            option_b_label = f"Prioritize {_label(second_signal.preference_key)}"
            score = (first.information_value + second_signal.information_value) / 2.0
        result.append(
            ActiveQuestion(
                id=question_id,
                profile_id=snapshot.profile_id,
                prompt="Which trade-off better reflects what you would choose?",
                preference_keys=keys,
                context=first.context,
                option_a_label=option_a_label,
                option_a_features=option_a_features,
                option_b_label=option_b_label,
                option_b_features=option_b_features,
                information_gain_score=score,
                model_snapshot_version=snapshot.version,
                algorithm_version=ACTIVE_LEARNING_ALGORITHM_VERSION,
                status=ActiveQuestionStatus.PENDING,
                created_at=created_at,
            )
        )
    return tuple(result)


def answer_evidence(
    *,
    question: ActiveQuestion,
    answer: QuestionAnswer,
    profile_id: str,
) -> tuple[Evidence, ...]:
    """Convert a pairwise answer into provenance-bearing preference evidence."""

    if question.profile_id != profile_id or answer.question_id != question.id:
        raise ValueError("Question answer must belong to the profile question.")
    features = question.option_a_features if answer.choice == "a" else question.option_b_features
    return tuple(
        Evidence(
            id=f"evidence_{answer.id}_{index}",
            profile_id=profile_id,
            target_type=EvidenceTargetType.PREFERENCE,
            target_key=key,
            value=value,
            strength=0.8,
            confidence=0.9,
            context=question.context,
            source_type="pairwise_calibration",
            source_event_id=answer.source_event_id,
            extractor_version=ACTIVE_LEARNING_ALGORITHM_VERSION,
            created_at=answer.created_at,
        )
        for index, (key, value) in enumerate(sorted(features.items()))
    )
