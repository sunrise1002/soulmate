"""Test automatic aliases for keys whose normalized forms are equal."""

from datetime import UTC, datetime

from soulmate_core.domain import (
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_core.keys import (
    KEY_NORMALIZER_VERSION,
    normalized_or_none,
    propose_normalized_aliases,
)

PROFILE = "profile_test"
NOW = datetime(2026, 9, 17, tzinfo=UTC)
PREFERENCE = EvidenceTargetType.PREFERENCE
FACT = EvidenceTargetType.FACT


def _alias(
    alias_key: str,
    canonical_key: str,
    status: TargetKeyAliasStatus = TargetKeyAliasStatus.ACTIVE,
    profile_id: str = PROFILE,
) -> TargetKeyAlias:
    return TargetKeyAlias(
        profile_id=profile_id,
        target_type=PREFERENCE,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=1,
        method=TargetKeyAliasMethod.OWNER,
        status=status,
        algorithm_version="owner-alias-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _pairs(proposals: tuple[TargetKeyAlias, ...]) -> list[tuple[str, str]]:
    return [(item.alias_key, item.canonical_key) for item in proposals]


def test_variant_key_is_aliased_to_its_used_normalized_form() -> None:
    # Given: a variant key used before its normalized form
    keys = [(PREFERENCE, "ui.theme.dark_mode"), (PREFERENCE, "ui.theme.dark")]

    # When: automatic aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, (), NOW)

    # Then: the variant points at the normalized key as an active automatic alias
    assert _pairs(proposals) == [("ui.theme.dark_mode", "ui.theme.dark")]
    alias = proposals[0]
    assert alias.method is TargetKeyAliasMethod.NORMALIZED
    assert alias.status is TargetKeyAliasStatus.ACTIVE
    assert alias.polarity == 1
    assert alias.similarity is None
    assert alias.algorithm_version == KEY_NORMALIZER_VERSION
    assert (alias.created_at, alias.updated_at) == (NOW, NOW)


def test_first_used_key_is_canonical_when_the_normalized_form_is_unused() -> None:
    # Given: three variants whose normalized form ui.theme.dark is never used
    keys = [
        (PREFERENCE, "UI.Theme.Dark_Mode"),
        (PREFERENCE, "ui.theme.dark-mode"),
        (PREFERENCE, "ui.theme.dark_setting"),
    ]

    # When: automatic aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, (), NOW)

    # Then: later variants join the first used key
    assert _pairs(proposals) == [
        ("ui.theme.dark-mode", "UI.Theme.Dark_Mode"),
        ("ui.theme.dark_setting", "UI.Theme.Dark_Mode"),
    ]


def test_existing_active_target_stays_canonical_for_new_variants() -> None:
    # Given: the owner already merged the normalized key into a variant
    keys = [
        (PREFERENCE, "ui.theme.dark"),
        (PREFERENCE, "ui.theme.dark_mode"),
        (PREFERENCE, "ui.theme.dark_preference"),
    ]
    existing = (_alias("ui.theme.dark", "ui.theme.dark_mode"),)

    # When: a new variant appears
    proposals = propose_normalized_aliases(PROFILE, keys, existing, NOW)

    # Then: it follows the existing merge target instead of creating a cycle
    assert _pairs(proposals) == [("ui.theme.dark_preference", "ui.theme.dark_mode")]


def test_rejected_or_suggested_aliases_are_never_replaced() -> None:
    # Given: the owner rejected one automatic merge and one suggestion is pending
    keys = [
        (PREFERENCE, "ui.theme.dark"),
        (PREFERENCE, "ui.theme.dark_mode"),
        (PREFERENCE, "ui.theme.dark_level"),
    ]
    existing = (
        _alias("ui.theme.dark_mode", "ui.theme.dark", TargetKeyAliasStatus.REJECTED),
        _alias("ui.theme.dark_level", "ui.theme.dark", TargetKeyAliasStatus.SUGGESTED),
    )

    # When: aliases are proposed again
    proposals = propose_normalized_aliases(PROFILE, keys, existing, NOW)

    # Then: the owner decisions are kept and no alias is proposed
    assert proposals == ()


def test_rejected_normalized_form_does_not_redirect_the_group() -> None:
    # Given: the normalized key has only a rejected alias pointing inside the group
    keys = [(PREFERENCE, "ui.theme.dark"), (PREFERENCE, "ui.theme.dark_mode")]
    existing = (_alias("ui.theme.dark", "ui.theme.dark_mode", TargetKeyAliasStatus.REJECTED),)

    # When: aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, existing, NOW)

    # Then: the unaliased variant still joins the normalized key
    assert _pairs(proposals) == [("ui.theme.dark_mode", "ui.theme.dark")]


def test_normalized_form_with_an_outside_active_alias_stays_canonical() -> None:
    # Given: the normalized key is merged into a key outside the group
    keys = [(PREFERENCE, "ui.theme.dark"), (PREFERENCE, "ui.theme.dark_mode")]
    existing = (_alias("ui.theme.dark", "appearance.dark"),)

    # When: aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, existing, NOW)

    # Then: the variant joins the normalized key and follows its chain on aggregation
    assert _pairs(proposals) == [("ui.theme.dark_mode", "ui.theme.dark")]


def test_empty_input_proposes_nothing() -> None:
    # Given / When: no keys are used
    proposals = propose_normalized_aliases(PROFILE, [], (), NOW)

    # Then: no alias is proposed
    assert proposals == ()


def test_single_and_repeated_keys_propose_nothing() -> None:
    # Given: one key used several times
    keys = [(PREFERENCE, "work.remote")] * 3

    # When: aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, (), NOW)

    # Then: a key never aliases itself
    assert proposals == ()


def test_equal_keys_of_different_target_types_stay_separate() -> None:
    # Given: a preference and a fact with equal normalized keys
    keys = [(PREFERENCE, "ui.theme.dark"), (FACT, "ui.theme.dark_mode")]

    # When: aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, (), NOW)

    # Then: target types are never merged
    assert proposals == ()


def test_fact_variants_are_aliased_within_their_type() -> None:
    # Given: two fact keys with equal normalized forms
    keys = [(FACT, "home.city"), (FACT, "Home.City")]

    # When: aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, (), NOW)

    # Then: the fact alias keeps positive polarity
    assert _pairs(proposals) == [("Home.City", "home.city")]
    assert proposals[0].target_type is FACT


def test_keys_that_normalize_to_nothing_are_ignored() -> None:
    # Given: keys that are empty after normalization
    keys = [(PREFERENCE, "..."), (PREFERENCE, " . ")]

    # When: aliases are proposed
    proposals = propose_normalized_aliases(PROFILE, keys, (), NOW)

    # Then: they are neither grouped nor raise
    assert proposals == ()
    assert normalized_or_none("...") is None
    assert normalized_or_none("UI.Theme") == "ui.theme"


def test_aliases_of_other_profiles_are_ignored() -> None:
    # Given: another profile rejected the same merge
    keys = [(PREFERENCE, "ui.theme.dark"), (PREFERENCE, "ui.theme.dark_mode")]
    foreign = (
        _alias(
            "ui.theme.dark_mode",
            "ui.theme.dark",
            TargetKeyAliasStatus.REJECTED,
            profile_id="profile_other",
        ),
    )

    # When: aliases are proposed for this profile
    proposals = propose_normalized_aliases(PROFILE, keys, foreign, NOW)

    # Then: the other profile's decision does not apply
    assert _pairs(proposals) == [("ui.theme.dark_mode", "ui.theme.dark")]
    assert proposals[0].profile_id == PROFILE
