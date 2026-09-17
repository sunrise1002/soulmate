"""Pure resolution of raw target keys onto owner-approved canonical keys."""

from collections.abc import Iterable
from dataclasses import dataclass

from soulmate_core.domain.models import (
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasStatus,
)

type _Identity = tuple[str, EvidenceTargetType, str]


@dataclass(frozen=True, slots=True)
class ResolvedKey:
    """Canonical key a raw key aggregates into, and the sign applied to its value."""

    key: str
    polarity: int


def _follow(direct: dict[_Identity, ResolvedKey], identity: _Identity) -> ResolvedKey:
    profile_id, target_type, key = identity
    current = key
    polarity = 1
    seen = {key}
    while (step := direct.get((profile_id, target_type, current))) is not None:
        if step.key in seen:
            raise ValueError(f"Target key aliases form a cycle starting at {key!r}.")
        seen.add(step.key)
        polarity *= step.polarity
        current = step.key
    return ResolvedKey(current, polarity)


class KeyAliasMap:
    """Immutable lookup that follows active alias chains without any I/O.

    Suggested and rejected aliases are ignored, so disabling or rejecting an alias
    restores the original grouping on the next rebuild.
    """

    def __init__(self, aliases: Iterable[TargetKeyAlias] = ()) -> None:
        direct: dict[_Identity, ResolvedKey] = {}
        for alias in aliases:
            if alias.status is not TargetKeyAliasStatus.ACTIVE:
                continue
            identity = (alias.profile_id, alias.target_type, alias.alias_key)
            resolved = ResolvedKey(alias.canonical_key, alias.polarity)
            if direct.get(identity, resolved) != resolved:
                raise ValueError(f"Conflicting active aliases for key {alias.alias_key!r}.")
            direct[identity] = resolved
        self._resolved = {identity: _follow(direct, identity) for identity in direct}

    def __len__(self) -> int:
        return len(self._resolved)

    def resolve(self, profile_id: str, target_type: EvidenceTargetType, key: str) -> ResolvedKey:
        """Return the canonical key for ``key``, or ``key`` itself when unaliased."""
        return self._resolved.get((profile_id, target_type, key), ResolvedKey(key, 1))
