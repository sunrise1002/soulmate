"""Test the daemon alias workflow against in-memory fakes."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from soulmate_core.domain import (
    Evidence,
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_core.keys import KeyAliasMap
from soulmate_daemon.config import ConfigurationError, load_settings
from soulmate_daemon.key_aliases import (
    OWNER_ALIAS_VERSION,
    KeyAliasError,
    KeyAliasReviewAction,
    KeyAliasService,
    register_normalized_aliases,
)

PROFILE = "profile_test"
NOW = datetime(2026, 9, 17, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
PREFERENCE = EvidenceTargetType.PREFERENCE
FACT = EvidenceTargetType.FACT


def _evidence(index: int, key: str, target_type: EvidenceTargetType = PREFERENCE) -> Evidence:
    return Evidence(
        id=f"evidence_{index}",
        profile_id=PROFILE,
        target_type=target_type,
        target_key=key,
        value=0.5 if target_type is PREFERENCE else "value",
        strength=1.0,
        confidence=1.0,
        context={},
        source_type="explicit_statement",
        source_event_id=f"event_{index}",
        extractor_version="synthetic-v1",
        created_at=NOW,
    )


def _alias(
    alias_key: str,
    canonical_key: str,
    *,
    target_type: EvidenceTargetType = PREFERENCE,
    status: TargetKeyAliasStatus = TargetKeyAliasStatus.ACTIVE,
    polarity: int = 1,
) -> TargetKeyAlias:
    return TargetKeyAlias(
        profile_id=PROFILE,
        target_type=target_type,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=polarity,
        method=TargetKeyAliasMethod.NORMALIZED,
        status=status,
        algorithm_version="key-normalizer-v1",
        created_at=NOW,
        updated_at=NOW,
    )


class FakeEvidence:
    """Evidence reads only; the alias workflow must never write evidence."""

    def __init__(self, *items: Evidence, failure: Exception | None = None) -> None:
        self.items = items
        self.failure = failure
        self.reads = 0

    def list_for_profile(self, profile_id: str) -> tuple[Evidence, ...]:
        self.reads += 1
        if self.failure is not None:
            raise self.failure
        return tuple(item for item in self.items if item.profile_id == profile_id)

    def add(self, evidence: Evidence) -> None:
        raise AssertionError(f"Unexpected evidence write {evidence.id}.")

    def get(self, evidence_id: str) -> Evidence | None:
        return next((item for item in self.items if item.id == evidence_id), None)

    def list_for_profile_with_revision(self, profile_id: str) -> tuple[tuple[Evidence, ...], int]:
        return self.list_for_profile(profile_id), 0

    def list_for_target(self, profile_id: str, target_key: str) -> tuple[Evidence, ...]:
        return tuple(
            item for item in self.list_for_profile(profile_id) if item.target_key == target_key
        )

    def remove(self, evidence_id: str) -> bool:
        raise AssertionError(f"Unexpected evidence removal {evidence_id}.")

    def current_revision(self, profile_id: str) -> int:
        return len(self.list_for_profile(profile_id))


class FakeAliases:
    """Mirror the SQLite repository contract, including cycle rejection."""

    def __init__(self, *aliases: TargetKeyAlias, reject_upserts: bool = False) -> None:
        self.rows = {(item.target_type, item.alias_key): item for item in aliases}
        self.reject_upserts = reject_upserts
        self.writes = 0

    def upsert(self, alias: TargetKeyAlias) -> TargetKeyAlias:
        if self.reject_upserts:
            raise ValueError("Target key aliases form a cycle starting at 'x'.")
        if alias.status is TargetKeyAliasStatus.ACTIVE:
            others = [
                item
                for key, item in self.rows.items()
                if key != (alias.target_type, alias.alias_key)
            ]
            KeyAliasMap([*others, alias])
        self.rows[(alias.target_type, alias.alias_key)] = alias
        self.writes += 1
        return alias

    def get(
        self, profile_id: str, target_type: EvidenceTargetType, alias_key: str
    ) -> TargetKeyAlias | None:
        alias = self.rows.get((target_type, alias_key))
        return alias if alias is not None and alias.profile_id == profile_id else None

    def list_for_profile(
        self, profile_id: str, status: TargetKeyAliasStatus | None = None
    ) -> tuple[TargetKeyAlias, ...]:
        return tuple(
            item
            for item in self.rows.values()
            if item.profile_id == profile_id and (status is None or item.status is status)
        )

    def remove(self, profile_id: str, target_type: EvidenceTargetType, alias_key: str) -> bool:
        if self.get(profile_id, target_type, alias_key) is None:
            return False
        self.writes += 1
        del self.rows[(target_type, alias_key)]
        return True


def test_register_stores_automatic_aliases_for_normalized_duplicates() -> None:
    # Given: two used variants of one key
    evidence = FakeEvidence(_evidence(1, "ui.theme.dark_mode"), _evidence(2, "ui.theme.dark"))
    aliases = FakeAliases()

    # When: reviewed evidence is registered
    stored = register_normalized_aliases(evidence, aliases, PROFILE, NOW)

    # Then: the variant is stored as an active automatic alias
    assert [(item.alias_key, item.canonical_key) for item in stored] == [
        ("ui.theme.dark_mode", "ui.theme.dark")
    ]
    assert aliases.writes == 1


def test_register_is_idempotent() -> None:
    # Given: an alias created by an earlier registration
    evidence = FakeEvidence(_evidence(1, "ui.theme.dark_mode"), _evidence(2, "ui.theme.dark"))
    aliases = FakeAliases()
    register_normalized_aliases(evidence, aliases, PROFILE, NOW)

    # When: registration runs again
    stored = register_normalized_aliases(evidence, aliases, PROFILE, LATER)

    # Then: nothing new is written, so the revision is not advanced again
    assert stored == ()
    assert aliases.writes == 1


def test_register_does_nothing_when_aliases_are_disabled() -> None:
    # Given: aliases disabled in configuration
    evidence = FakeEvidence(_evidence(1, "ui.theme.dark_mode"), _evidence(2, "ui.theme.dark"))

    # When: registration runs without a repository
    stored = register_normalized_aliases(evidence, None, PROFILE, NOW)

    # Then: evidence is not even read
    assert stored == ()
    assert evidence.reads == 0


def test_register_skips_proposals_the_repository_rejects() -> None:
    # Given: a repository that rejects writes because of a concurrent cycle
    evidence = FakeEvidence(_evidence(1, "ui.theme.dark_mode"), _evidence(2, "ui.theme.dark"))
    aliases = FakeAliases(reject_upserts=True)

    # When: registration runs
    stored = register_normalized_aliases(evidence, aliases, PROFILE, NOW)

    # Then: the keys stay separate and learning continues
    assert stored == ()
    assert aliases.rows == {}


def test_register_propagates_storage_failures() -> None:
    # Given: evidence storage that is unavailable
    evidence = FakeEvidence(failure=RuntimeError("database is locked"))

    # When / Then: the failure reaches the durable job for retry
    with pytest.raises(RuntimeError, match="database is locked"):
        register_normalized_aliases(evidence, FakeAliases(), PROFILE, NOW)


def test_owner_alias_is_created_with_trimmed_keys() -> None:
    # Given: a used key
    service = KeyAliasService(FakeEvidence(_evidence(1, "work.office")), FakeAliases())

    # When: the owner merges it inverted into another key
    alias = service.create(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        alias_key=" work.office ",
        canonical_key=" work.remote ",
        polarity=-1,
        now=NOW,
    )

    # Then: an active owner alias is stored
    assert (alias.alias_key, alias.canonical_key, alias.polarity) == (
        "work.office",
        "work.remote",
        -1,
    )
    assert alias.method is TargetKeyAliasMethod.OWNER
    assert alias.status is TargetKeyAliasStatus.ACTIVE
    assert alias.algorithm_version == OWNER_ALIAS_VERSION


def test_owner_alias_replacing_an_existing_row_keeps_its_creation_time() -> None:
    # Given: an automatic alias created earlier
    aliases = FakeAliases(_alias("ui.theme.dark_mode", "ui.theme.dark"))
    service = KeyAliasService(FakeEvidence(_evidence(1, "ui.theme.dark_mode")), aliases)

    # When: the owner points it somewhere else
    alias = service.create(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        alias_key="ui.theme.dark_mode",
        canonical_key="appearance.dark",
        polarity=1,
        now=LATER,
    )

    # Then: the row is replaced but keeps its first creation time
    assert (alias.created_at, alias.updated_at) == (NOW, LATER)
    assert alias.canonical_key == "appearance.dark"


@pytest.mark.parametrize(
    ("alias_key", "target_type"),
    [("work.unknown", PREFERENCE), ("work.office", FACT)],
)
def test_owner_alias_requires_a_key_used_by_evidence_of_that_type(
    alias_key: str, target_type: EvidenceTargetType
) -> None:
    # Given: only a preference key is used
    service = KeyAliasService(FakeEvidence(_evidence(1, "work.office")), FakeAliases())

    # When / Then: unknown keys or other types are rejected as missing
    with pytest.raises(KeyError):
        service.create(
            profile_id=PROFILE,
            target_type=target_type,
            alias_key=alias_key,
            canonical_key="work.remote",
            polarity=1,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("target_type", "canonical_key", "polarity", "message"),
    [
        (PREFERENCE, "work.office", 1, "must not point at itself"),
        (FACT, "home.town", -1, "Only preference aliases can invert"),
        (PREFERENCE, "work.remote", 1, "cycle"),
    ],
)
def test_owner_alias_rule_violations_raise_alias_errors(
    target_type: EvidenceTargetType, canonical_key: str, polarity: int, message: str
) -> None:
    # Given: used keys and an existing alias work.remote -> work.office
    evidence = FakeEvidence(_evidence(1, "work.office"), _evidence(2, "work.office", FACT))
    aliases = FakeAliases(_alias("work.remote", "work.office"))
    service = KeyAliasService(evidence, aliases)

    # When / Then: self, inverted fact, and cyclic aliases are rejected
    with pytest.raises(KeyAliasError, match=message):
        service.create(
            profile_id=PROFILE,
            target_type=target_type,
            alias_key="work.office",
            canonical_key=canonical_key,
            polarity=polarity,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("status", "action", "expected_status", "expected_polarity"),
    [
        (TargetKeyAliasStatus.SUGGESTED, KeyAliasReviewAction.APPROVE, "active", 1),
        (TargetKeyAliasStatus.SUGGESTED, KeyAliasReviewAction.INVERT, "active", -1),
        (TargetKeyAliasStatus.SUGGESTED, KeyAliasReviewAction.REJECT, "rejected", 1),
        (TargetKeyAliasStatus.ACTIVE, KeyAliasReviewAction.REJECT, "rejected", 1),
        (TargetKeyAliasStatus.REJECTED, KeyAliasReviewAction.APPROVE, "active", 1),
    ],
)
def test_review_actions_change_status_and_polarity(
    status: TargetKeyAliasStatus,
    action: KeyAliasReviewAction,
    expected_status: str,
    expected_polarity: int,
) -> None:
    # Given: an alias in the given review state
    aliases = FakeAliases(_alias("ui.theme.light", "ui.theme.dark", status=status))
    service = KeyAliasService(FakeEvidence(), aliases)

    # When: the owner reviews it
    alias = service.review(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        alias_key="ui.theme.light",
        action=action,
        now=LATER,
    )

    # Then: the stored alias reflects the decision
    assert alias.status.value == expected_status
    assert alias.polarity == expected_polarity
    assert alias.updated_at == LATER
    assert aliases.rows[(PREFERENCE, "ui.theme.light")] == alias


def test_inverting_twice_restores_positive_polarity() -> None:
    # Given: an inverted active alias
    aliases = FakeAliases(_alias("ui.theme.light", "ui.theme.dark", polarity=-1))
    service = KeyAliasService(FakeEvidence(), aliases)

    # When: the owner inverts it again
    alias = service.review(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        alias_key="ui.theme.light",
        action=KeyAliasReviewAction.INVERT,
        now=LATER,
    )

    # Then: polarity is positive again
    assert alias.polarity == 1


def test_review_of_a_missing_alias_raises_key_error() -> None:
    # Given: no alias
    service = KeyAliasService(FakeEvidence(), FakeAliases())

    # When / Then: the review is rejected as missing
    with pytest.raises(KeyError):
        service.review(
            profile_id=PROFILE,
            target_type=PREFERENCE,
            alias_key="ui.theme.light",
            action=KeyAliasReviewAction.APPROVE,
            now=NOW,
        )


def test_inverting_a_fact_alias_is_rejected_without_writing() -> None:
    # Given: an alias between fact keys
    aliases = FakeAliases(_alias("Home.City", "home.city", target_type=FACT))
    service = KeyAliasService(FakeEvidence(), aliases)

    # When / Then: inversion is refused before storage
    with pytest.raises(KeyAliasError, match="Only preference aliases can invert"):
        service.review(
            profile_id=PROFILE,
            target_type=FACT,
            alias_key="Home.City",
            action=KeyAliasReviewAction.INVERT,
            now=NOW,
        )
    assert aliases.writes == 0


def test_approving_an_alias_that_closes_a_cycle_raises_alias_error() -> None:
    # Given: an active alias and a rejected alias pointing back
    aliases = FakeAliases(
        _alias("work.remote", "work.office"),
        _alias("work.office", "work.remote", status=TargetKeyAliasStatus.REJECTED),
    )
    service = KeyAliasService(FakeEvidence(), aliases)

    # When / Then: activating the rejected alias is refused
    with pytest.raises(KeyAliasError, match="cycle"):
        service.review(
            profile_id=PROFILE,
            target_type=PREFERENCE,
            alias_key="work.office",
            action=KeyAliasReviewAction.APPROVE,
            now=NOW,
        )


def test_remove_deletes_an_alias_and_reports_missing_ones() -> None:
    # Given: one stored alias
    aliases = FakeAliases(_alias("ui.theme.dark_mode", "ui.theme.dark"))
    service = KeyAliasService(FakeEvidence(), aliases)

    # When: the owner removes the alias
    service.remove(PROFILE, PREFERENCE, "ui.theme.dark_mode")

    # Then: it is gone, and removing it again reports it missing
    assert service.list_for_profile(PROFILE) == ()
    with pytest.raises(KeyError):
        service.remove(PROFILE, PREFERENCE, "ui.theme.dark_mode")


def test_key_aliases_are_enabled_by_default_and_configurable(tmp_path: Path) -> None:
    # Given: default settings, a TOML file, and an environment override
    config = tmp_path / "explicit" / "config.toml"
    config.parent.mkdir()
    config.write_text("[key_aliases]\nenabled = false\n", encoding="utf-8")

    # When: settings are loaded
    default = load_settings(environ={})
    from_toml = load_settings(config, environ={})
    from_env = load_settings(config, environ={"SOULMATE_KEY_ALIASES__ENABLED": "true"})

    # Then: the flag follows the documented precedence
    assert default.key_aliases.enabled is True
    assert from_toml.key_aliases.enabled is False
    assert from_env.key_aliases.enabled is True


@pytest.mark.parametrize(
    "content", ['[key_aliases]\nenabled = "maybe"\n', "[key_aliases]\nx = 1\n"]
)
def test_invalid_key_alias_settings_are_rejected(tmp_path: Path, content: str) -> None:
    # Given: an invalid value or a misspelled setting
    config = tmp_path / "config.toml"
    config.write_text(content, encoding="utf-8")

    # When / Then: loading fails and names the section
    with pytest.raises(ConfigurationError, match="key_aliases"):
        load_settings(config, environ={})
