"""Deterministic selection of known target keys to share with extraction providers."""

import json
import re
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from soulmate_core.domain import Constraint, DerivedModel, Fact, Goal, Preference

KEY_TYPES = ("facts", "preferences", "goals", "constraints")
_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_RECENT_SCORE = 4
_LEXICAL_SCORE = 2
_DOMAIN_SCORE = 1

type _Record = Fact | Preference | Goal | Constraint


@dataclass(frozen=True, slots=True)
class KeySelectionPolicy:
    """Budget for known keys; small models are shared whole to avoid missed matches."""

    send_all_threshold: int = 100
    limit: int = 50
    namespace_limit: int = 100

    def __post_init__(self) -> None:
        if min(self.send_all_threshold, self.limit, self.namespace_limit) < 0:
            raise ValueError("Key selection budgets must not be negative.")


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
    policy: KeySelectionPolicy | None = None,
) -> dict[str, list[str]]:
    """Return namespaces plus the known keys most likely to matter for ``query``.

    Keys score by recent use, word overlap with the query or categorical value, and
    domain match; ties prefer confident, recently updated keys. Keys that are missed
    here can still be created under a listed namespace.
    """
    unknown = set(key_types) - set(KEY_TYPES)
    if unknown:
        raise ValueError(f"Unknown key types: {', '.join(sorted(unknown))}.")
    active = policy or KeySelectionPolicy()
    candidates = [
        (key_type, record) for key_type in key_types for record in _records(model, key_type)
    ]
    all_keys = {(key_type, record.key) for key_type, record in candidates}
    selected = all_keys
    if len(all_keys) > active.send_all_threshold:
        query_words = _words(query)
        normalized_domain = None if domain is None else domain.casefold()
        best: dict[tuple[str, str], tuple[int, float, float]] = {}
        for key_type, record in candidates:
            record_words = _words(record.key)
            if not isinstance(record, Preference):
                record_words |= _words(record.value)
            record_domain = record.context.get("domain")
            score = (
                (_RECENT_SCORE if record.key in recent_keys else 0)
                + (_LEXICAL_SCORE if query_words & record_words else 0)
                + (
                    _DOMAIN_SCORE
                    if normalized_domain is not None
                    and str(record_domain).casefold() == normalized_domain
                    else 0
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
