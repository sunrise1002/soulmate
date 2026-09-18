"""Deterministic selection of known target keys to share with extraction providers."""

import json
import re
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from soulmate_core.domain import Constraint, DerivedModel, Fact, Goal, Preference

KEY_TYPES = ("facts", "preferences", "goals", "constraints")
_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_RECENT_SCORE = 4.0
_LEXICAL_SCORE = 2.0
_DOMAIN_SCORE = 1.0

type _Record = Fact | Preference | Goal | Constraint


@dataclass(frozen=True, slots=True)
class KeySelectionPolicy:
    """Budget and scoring weights; small models are shared whole to avoid misses.

    ``semantic_weight`` scales a cosine similarity into the same scale as the
    lexical and domain signals, so a cross-language match can outrank a key that
    merely shares a word. ``semantic_floor`` discards weak similarities, because
    every key has some similarity to every message.
    """

    send_all_threshold: int = 100
    limit: int = 50
    namespace_limit: int = 100
    semantic_weight: float = 3.0
    semantic_floor: float = 0.3

    def __post_init__(self) -> None:
        if min(self.send_all_threshold, self.limit, self.namespace_limit) < 0:
            raise ValueError("Key selection budgets must not be negative.")
        if self.semantic_weight < 0:
            raise ValueError("The semantic weight must not be negative.")
        if not 0.0 <= self.semantic_floor <= 1.0:
            raise ValueError("The semantic floor must be between zero and one.")


def _words(value: object) -> set[str]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {word for word in _WORD_PATTERN.findall(text.casefold()) if len(word) > 1}


def _records(model: DerivedModel, key_type: str) -> Sequence[_Record]:
    records: dict[str, Sequence[_Record]] = {
        "facts": model.facts,
        "preferences": model.preferences,
        "goals": model.goals,
        "constraints": model.constraints,
    }
    return records[key_type]


def _namespaces(keys: Collection[str], limit: int) -> list[str]:
    counts = Counter(key.rsplit(".", 1)[0] for key in keys if "." in key)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return sorted(namespace for namespace, _ in ranked[:limit])


def select_known_keys(
    model: DerivedModel,
    *,
    query: str,
    recent_keys: Collection[str] = (),
    domain: str | None = None,
    key_types: Sequence[str] = KEY_TYPES,
    semantic_scores: Mapping[str, float] | None = None,
    policy: KeySelectionPolicy | None = None,
) -> dict[str, list[str]]:
    """Return namespaces plus the known keys most likely to matter for ``query``.

    Keys score by recent use, word overlap with the query or categorical value,
    domain match, and the supplied semantic similarity between the query and the
    key; ties prefer confident, recently updated keys. ``semantic_scores`` maps a
    key name to a cosine similarity and is empty whenever no embedding model is
    available, which leaves the lexical behavior of step A unchanged. Keys that are
    missed here can still be created under a listed namespace.
    """
    unknown = set(key_types) - set(KEY_TYPES)
    if unknown:
        raise ValueError(f"Unknown key types: {', '.join(sorted(unknown))}.")
    active = policy or KeySelectionPolicy()
    similarities = semantic_scores or {}
    candidates = [
        (key_type, record) for key_type in key_types for record in _records(model, key_type)
    ]
    all_keys = {(key_type, record.key) for key_type, record in candidates}
    selected = all_keys
    if len(all_keys) > active.send_all_threshold:
        query_words = _words(query)
        normalized_domain = None if domain is None else domain.casefold()
        best: dict[tuple[str, str], tuple[float, float, float]] = {}
        for key_type, record in candidates:
            record_words = _words(record.key)
            if not isinstance(record, Preference):
                record_words |= _words(record.value)
            record_domain = record.context.get("domain")
            similarity = similarities.get(record.key, 0.0)
            score = (
                (_RECENT_SCORE if record.key in recent_keys else 0.0)
                + (_LEXICAL_SCORE if query_words & record_words else 0.0)
                + (
                    _DOMAIN_SCORE
                    if normalized_domain is not None
                    and str(record_domain).casefold() == normalized_domain
                    else 0.0
                )
                + (
                    active.semantic_weight * similarity
                    if similarity >= active.semantic_floor
                    else 0.0
                )
            )
            rank = (score, record.confidence, record.updated_at.timestamp())
            identity = (key_type, record.key)
            best[identity] = max(rank, best.get(identity, rank))
        ordered = sorted(
            best.items(),
            key=lambda item: (-item[1][0], -item[1][1], -item[1][2], item[0]),
        )
        selected = {identity for identity, _ in ordered[: active.limit]}
    result = {"namespaces": _namespaces({key for _, key in all_keys}, active.namespace_limit)}
    for key_type in key_types:
        result[key_type] = sorted(key for item_type, key in selected if item_type == key_type)
    return result
