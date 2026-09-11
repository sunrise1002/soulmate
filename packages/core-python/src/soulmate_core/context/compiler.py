"""Minimal deterministic Personal Model context retrieval for conversation."""

import json
import re
from dataclasses import dataclass

from soulmate_core.domain import Constraint, Fact, Goal, PersonalModelRepository

TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class PersonalContext:
    model_version: int | None
    preferences: tuple[dict[str, object], ...]
    facts: tuple[dict[str, object], ...]
    goals: tuple[dict[str, object], ...]
    constraints: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "model_version": self.model_version,
            "preferences": list(self.preferences),
            "facts": list(self.facts),
            "goals": list(self.goals),
            "constraints": list(self.constraints),
        }


def _tokens(value: object) -> set[str]:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {token.casefold() for token in TOKEN_PATTERN.findall(serialized) if len(token) > 1}


def _relevant(query_tokens: set[str], key: str, value: object, context: object) -> bool:
    return bool(query_tokens & _tokens({"key": key, "value": value, "context": context}))


class ContextCompiler:
    """Select model entries with lexical overlap instead of disclosing full state."""

    def __init__(self, models: PersonalModelRepository, *, limit_per_type: int = 5) -> None:
        if limit_per_type < 1:
            raise ValueError("Context limit must be positive.")
        self._models = models
        self._limit = limit_per_type

    def compile(self, profile_id: str, query: str) -> PersonalContext:
        snapshot = self._models.latest_snapshot(profile_id)
        if snapshot is None:
            return PersonalContext(None, (), (), (), ())
        query_tokens = _tokens(query)

        def categorical(
            records: tuple[Fact, ...] | tuple[Goal, ...] | tuple[Constraint, ...],
        ) -> tuple[dict[str, object], ...]:
            selected: list[dict[str, object]] = []
            for record in records:
                key = record.key
                value = record.value
                context = record.context
                if _relevant(query_tokens, key, value, context):
                    selected.append(
                        {
                            "key": key,
                            "value": value,
                            "confidence": record.confidence,
                            "context": context,
                        }
                    )
            return tuple(selected[: self._limit])

        preferences = tuple(
            {
                "key": item.key,
                "value": item.value,
                "confidence": item.confidence,
                "context": item.context,
            }
            for item in snapshot.model.preferences
            if _relevant(query_tokens, item.key, item.value, item.context)
        )[: self._limit]
        return PersonalContext(
            snapshot.version,
            preferences,
            categorical(snapshot.model.facts),
            categorical(snapshot.model.goals),
            categorical(snapshot.model.constraints),
        )
