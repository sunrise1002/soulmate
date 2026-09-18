"""Deterministic automatic aliases for keys whose normalized forms are equal."""

from collections.abc import Iterable, Sequence
from datetime import datetime

from soulmate_core.domain.models import (
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_core.keys.aliases import KeyAliasMap
from soulmate_core.keys.normalization import KEY_NORMALIZER_VERSION, normalize_key

type TypedKey = tuple[EvidenceTargetType, str]


def normalized_or_none(key: str) -> str | None:
    """Return ``normalize_key(key)``, or ``None`` when nothing would remain."""
    try:
        return normalize_key(key)
    except ValueError:
        return None


def _canonical(
    group: Sequence[str],
    normalized: str,
    target_type: EvidenceTargetType,
    profile_id: str,
    active: KeyAliasMap,
    aliased: set[TypedKey],
) -> str:
    members = set(group)
    for key in group:
        if (target_type, key) in aliased:
            resolved = active.resolve(profile_id, target_type, key).key
            if resolved != key and resolved in members:
                return resolved
    if normalized in members:
        return normalized
    return next(key for key in group if (target_type, key) not in aliased)


def propose_normalized_aliases(
    profile_id: str,
    keys: Iterable[TypedKey],
    aliases: Sequence[TargetKeyAlias],
    now: datetime,
) -> tuple[TargetKeyAlias, ...]:
    """Return new active aliases that join keys with equal normalized forms.

    ``keys`` should be ordered by first use. Within a group, the canonical key is
    the target an existing active alias already uses, else the normalized form
    when it is itself a used key, else the first used key. Keys that already have
    an alias row of any status are left alone, so owner rejections are sticky. The
    chosen canonical key never leads back into its group through active aliases,
    so a proposal cannot close a cycle; the repository still rejects cycles caused
    by concurrent changes.
    """
    groups: dict[TypedKey, list[str]] = {}
    for target_type, key in keys:
        normalized = normalized_or_none(key)
        if normalized is None:
            continue
        members = groups.setdefault((target_type, normalized), [])
        if key not in members:
            members.append(key)
    own = [alias for alias in aliases if alias.profile_id == profile_id]
    aliased = {(alias.target_type, alias.alias_key) for alias in own}
    active = KeyAliasMap(own)
    proposals: list[TargetKeyAlias] = []
    for (target_type, normalized), group in groups.items():
        if len(group) < 2 or all((target_type, key) in aliased for key in group):
            continue
        canonical = _canonical(group, normalized, target_type, profile_id, active, aliased)
        for key in group:
            if key == canonical or (target_type, key) in aliased:
                continue
            proposals.append(
                TargetKeyAlias(
                    profile_id=profile_id,
                    target_type=target_type,
                    alias_key=key,
                    canonical_key=canonical,
                    polarity=1,
                    method=TargetKeyAliasMethod.NORMALIZED,
                    status=TargetKeyAliasStatus.ACTIVE,
                    algorithm_version=KEY_NORMALIZER_VERSION,
                    created_at=now,
                    updated_at=now,
                )
            )
    return tuple(proposals)
