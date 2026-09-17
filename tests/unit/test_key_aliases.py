"""Test canonical target key aliases and their pure resolution map."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from soulmate_core.domain import (
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_core.keys import KeyAliasMap

PROFILE = "profile_test"


def _alias(
    alias_key: str,
    canonical_key: str,
    *,
    target_type: EvidenceTargetType = EvidenceTargetType.PREFERENCE,
    polarity: int = 1,
    method: TargetKeyAliasMethod = TargetKeyAliasMethod.NORMALIZED,
    status: TargetKeyAliasStatus = TargetKeyAliasStatus.ACTIVE,
    similarity: float | None = None,
    profile_id: str = PROFILE,
) -> TargetKeyAlias:
    return TargetKeyAlias(
        profile_id=profile_id,
        target_type=target_type,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=polarity,
        method=method,
        status=status,
        algorithm_version="key-normalizer-v1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        similarity=similarity,
    )


def test_unaliased_keys_resolve_to_themselves() -> None:
    aliases = KeyAliasMap()

    resolved = aliases.resolve(PROFILE, EvidenceTargetType.PREFERENCE, "ui.theme.dark")

    assert len(aliases) == 0
    assert (resolved.key, resolved.polarity) == ("ui.theme.dark", 1)


def test_active_alias_maps_a_key_to_its_canonical_key() -> None:
    aliases = KeyAliasMap([_alias("ui.theme.dark_mode", "ui.theme.dark")])

    resolved = aliases.resolve(PROFILE, EvidenceTargetType.PREFERENCE, "ui.theme.dark_mode")

    assert (resolved.key, resolved.polarity) == ("ui.theme.dark", 1)


def test_opposite_key_resolves_to_the_canonical_axis_with_inverted_polarity() -> None:
    aliases = KeyAliasMap([_alias("ui.theme.light", "ui.theme.dark", polarity=-1)])

    resolved = aliases.resolve(PROFILE, EvidenceTargetType.PREFERENCE, "ui.theme.light")

    assert (resolved.key, resolved.polarity) == ("ui.theme.dark", -1)


def test_alias_chains_are_followed_and_polarities_multiply() -> None:
    aliases = KeyAliasMap(
        [
            _alias("ui.theme.bright", "ui.theme.light", polarity=-1),
            _alias("ui.theme.light", "ui.theme.dark", polarity=-1),
        ]
    )

    resolved = aliases.resolve(PROFILE, EvidenceTargetType.PREFERENCE, "ui.theme.bright")

    assert (resolved.key, resolved.polarity) == ("ui.theme.dark", 1)


@pytest.mark.parametrize("status", [TargetKeyAliasStatus.SUGGESTED, TargetKeyAliasStatus.REJECTED])
def test_aliases_awaiting_or_refused_owner_review_never_merge(
    status: TargetKeyAliasStatus,
) -> None:
    aliases = KeyAliasMap(
        [
            _alias(
                "ui.theme.light",
                "ui.theme.dark",
                polarity=-1,
                method=TargetKeyAliasMethod.SEMANTIC,
                similarity=0.93,
                status=status,
            )
        ]
    )

    resolved = aliases.resolve(PROFILE, EvidenceTargetType.PREFERENCE, "ui.theme.light")

    assert len(aliases) == 0
    assert (resolved.key, resolved.polarity) == ("ui.theme.light", 1)


def test_aliases_never_cross_profiles_or_target_types() -> None:
    aliases = KeyAliasMap([_alias("ui.theme.dark_mode", "ui.theme.dark", profile_id="profile_a")])

    other_profile = aliases.resolve(
        "profile_b", EvidenceTargetType.PREFERENCE, "ui.theme.dark_mode"
    )
    other_type = aliases.resolve("profile_a", EvidenceTargetType.FACT, "ui.theme.dark_mode")

    assert other_profile.key == "ui.theme.dark_mode"
    assert other_type.key == "ui.theme.dark_mode"


def test_repeating_the_same_alias_is_accepted() -> None:
    alias = _alias("ui.theme.dark_mode", "ui.theme.dark")

    aliases = KeyAliasMap([alias, replace(alias, method=TargetKeyAliasMethod.OWNER)])

    resolved = aliases.resolve(PROFILE, EvidenceTargetType.PREFERENCE, "ui.theme.dark_mode")

    assert resolved.key == "ui.theme.dark"


def test_two_active_targets_for_one_key_are_rejected() -> None:
    aliases = [
        _alias("ui.theme.dark_mode", "ui.theme.dark"),
        _alias("ui.theme.dark_mode", "ui.appearance.dark"),
    ]

    with pytest.raises(ValueError, match="Conflicting active aliases"):
        KeyAliasMap(aliases)


def test_contradictory_polarity_for_one_key_is_rejected() -> None:
    aliases = [
        _alias("ui.theme.light", "ui.theme.dark", polarity=-1),
        _alias("ui.theme.light", "ui.theme.dark"),
    ]

    with pytest.raises(ValueError, match="Conflicting active aliases"):
        KeyAliasMap(aliases)


@pytest.mark.parametrize("length", [2, 3])
def test_alias_cycles_are_rejected_instead_of_looping(length: int) -> None:
    keys = [f"ui.theme.key_{index}" for index in range(length)]
    aliases = [_alias(key, keys[(index + 1) % length]) for index, key in enumerate(keys)]

    with pytest.raises(ValueError, match="form a cycle"):
        KeyAliasMap(aliases)


def test_alias_to_itself_is_rejected_by_the_domain() -> None:
    with pytest.raises(ValueError, match="must not point at itself"):
        _alias("ui.theme.dark", "ui.theme.dark")


@pytest.mark.parametrize(("alias_key", "canonical_key"), [("", "ui.theme.dark"), ("ui.a", "")])
def test_empty_alias_keys_are_rejected(alias_key: str, canonical_key: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _alias(alias_key, canonical_key)


@pytest.mark.parametrize("polarity", [0, 2, -2])
def test_polarity_outside_the_signed_axis_is_rejected(polarity: int) -> None:
    with pytest.raises(ValueError, match="polarity must be 1 or -1"):
        _alias("ui.theme.light", "ui.theme.dark", polarity=polarity)


@pytest.mark.parametrize(
    "target_type",
    [EvidenceTargetType.FACT, EvidenceTargetType.GOAL, EvidenceTargetType.CONSTRAINT],
)
def test_only_preferences_can_invert_polarity(target_type: EvidenceTargetType) -> None:
    with pytest.raises(ValueError, match="Only preference aliases can invert polarity"):
        _alias("owner.region.north", "owner.region.south", target_type=target_type, polarity=-1)


@pytest.mark.parametrize("similarity", [-0.01, 1.01])
def test_similarity_outside_the_unit_range_is_rejected(similarity: float) -> None:
    with pytest.raises(ValueError, match="similarity must be between 0 and 1"):
        _alias(
            "ui.theme.dark_mode",
            "ui.theme.dark",
            method=TargetKeyAliasMethod.SEMANTIC,
            similarity=similarity,
        )


def test_semantic_alias_without_a_similarity_is_rejected() -> None:
    with pytest.raises(ValueError, match="must record a similarity"):
        _alias("ui.theme.dark_mode", "ui.theme.dark", method=TargetKeyAliasMethod.SEMANTIC)


def test_empty_algorithm_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="algorithm version must not be empty"):
        replace(_alias("ui.theme.dark_mode", "ui.theme.dark"), algorithm_version="")


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timestamps must be timezone-aware"):
        replace(
            _alias("ui.theme.dark_mode", "ui.theme.dark"),
            updated_at=datetime(2026, 1, 1),
        )
