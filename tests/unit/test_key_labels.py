"""Owner-written key labels: what is accepted, what is refused, what is kept."""

from datetime import UTC, datetime

import pytest
from soulmate_core.domain import (
    Evidence,
    EvidenceTargetType,
    TargetKeyLabel,
    TargetKeyLabelSource,
)
from soulmate_daemon.extraction import ALIAS_MAX_COUNT, LABEL_MAX_LENGTH
from soulmate_daemon.key_labels import KeyLabelError, KeyLabelService, clean_aliases

PROFILE = "profile_default"
KEY = "ui.theme.dark"
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
PREFERENCE = EvidenceTargetType.PREFERENCE
FACT = EvidenceTargetType.FACT


class FakeEvidence:
    """Evidence reads only; naming a key must never write or delete evidence."""

    def __init__(self, keys: tuple[tuple[EvidenceTargetType, str], ...]) -> None:
        self._keys = keys

    def list_for_profile(self, profile_id: str) -> tuple[Evidence, ...]:
        return tuple(
            Evidence(
                id=f"evidence_{index}",
                profile_id=profile_id,
                target_type=target_type,
                target_key=key,
                value=0.8,
                strength=1.0,
                confidence=1.0,
                context={},
                source_type="explicit_statement",
                source_event_id="event_1",
                extractor_version="synthetic-v1",
                created_at=NOW,
            )
            for index, (target_type, key) in enumerate(self._keys)
        )

    def add(self, evidence: Evidence) -> None:
        raise AssertionError(f"Unexpected evidence write {evidence.id}.")

    def get(self, evidence_id: str) -> Evidence | None:
        return next(
            (item for item in self.list_for_profile(PROFILE) if item.id == evidence_id), None
        )

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


class FakeCatalog:
    """An in-memory catalog that protects owner labels the way SQLite does."""

    def __init__(self) -> None:
        self.entries: dict[tuple[str, str, str], TargetKeyLabel] = {}

    def upsert(self, entry: TargetKeyLabel) -> TargetKeyLabel:
        identity = (entry.profile_id, entry.target_type.value, entry.key)
        stored = self.entries.get(identity)
        if (
            stored is not None
            and stored.source is TargetKeyLabelSource.OWNER
            and entry.source is not TargetKeyLabelSource.OWNER
        ):
            return stored
        self.entries[identity] = entry
        return entry

    def get(
        self, profile_id: str, target_type: EvidenceTargetType, key: str
    ) -> TargetKeyLabel | None:
        return self.entries.get((profile_id, target_type.value, key))

    def list_for_profile(self, profile_id: str) -> tuple[TargetKeyLabel, ...]:
        return tuple(entry for entry in self.entries.values() if entry.profile_id == profile_id)

    def remove(self, profile_id: str, target_type: EvidenceTargetType, key: str) -> bool:
        return self.entries.pop((profile_id, target_type.value, key), None) is not None


def _service(
    keys: tuple[tuple[EvidenceTargetType, str], ...] = ((PREFERENCE, KEY),),
) -> tuple[KeyLabelService, FakeCatalog]:
    catalog = FakeCatalog()
    return KeyLabelService(FakeEvidence(keys), catalog), catalog


def _extracted(label: str = "giao diện tối") -> TargetKeyLabel:
    return TargetKeyLabel(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=KEY,
        label=label,
        aliases=(),
        source=TargetKeyLabelSource.EXTRACTED,
        created_at=NOW,
        updated_at=NOW,
    )


def test_an_owner_label_is_stored_for_a_key_the_model_uses() -> None:
    # Given: a key that evidence already uses
    service, catalog = _service()

    # When: the owner names it in their own language
    stored = service.set_label(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=KEY,
        label="giao diện tối",
        aliases=("nền tối",),
        now=NOW,
    )

    # Then: the label is owner-sourced, so extraction may not replace it
    assert stored.label == "giao diện tối"
    assert stored.aliases == ("nền tối",)
    assert stored.source is TargetKeyLabelSource.OWNER
    assert catalog.get(PROFILE, PREFERENCE, KEY) == stored


def test_an_owner_label_replaces_an_extracted_one_and_keeps_its_first_seen_time() -> None:
    # Given: a label extraction proposed earlier
    service, catalog = _service()
    catalog.upsert(_extracted())

    # When: the owner rewrites it later
    stored = service.set_label(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=KEY,
        label="chế độ tối",
        aliases=(),
        now=LATER,
    )

    # Then: the wording is the owner's, while the key keeps its original history
    assert stored.label == "chế độ tối"
    assert stored.created_at == NOW
    assert stored.updated_at == LATER
    assert stored.source is TargetKeyLabelSource.OWNER


def test_an_extracted_label_never_overwrites_an_owner_label() -> None:
    # Given: a label the owner wrote
    service, catalog = _service()
    service.set_label(
        profile_id=PROFILE, target_type=PREFERENCE, key=KEY, label="chế độ tối", aliases=(), now=NOW
    )

    # When: extraction proposes a different wording afterwards
    catalog.upsert(_extracted("dark mode"))

    # Then: the owner's wording survives
    assert catalog.entries[(PROFILE, PREFERENCE.value, KEY)].label == "chế độ tối"


def test_aliases_are_trimmed_deduplicated_and_capped() -> None:
    # Given: a noisy alias list above the shared limit
    service, _ = _service()
    noisy = ("  nền tối  ", "nền tối", "", "   ", "dark", "tối", "đen", "u ám", "mờ")

    # When: the owner submits it
    stored = service.set_label(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=KEY,
        label="giao diện tối",
        aliases=noisy,
        now=NOW,
    )

    # Then: extraction's own cleaning rules apply to owner input too
    assert stored.aliases == ("nền tối", "dark", "tối", "đen", "u ám")
    assert len(stored.aliases) == ALIAS_MAX_COUNT


def test_an_alias_equal_to_the_label_is_dropped() -> None:
    # Given: an alias repeating the label
    service, _ = _service()

    # When: the label is stored
    stored = service.set_label(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=KEY,
        label="giao diện tối",
        aliases=("giao diện tối", "nền tối"),
        now=NOW,
    )

    # Then: the embedded text gains nothing from a repetition
    assert stored.aliases == ("nền tối",)


def test_an_over_long_label_is_truncated_to_the_shared_limit() -> None:
    # Given: a label one character above the maximum
    service, _ = _service()

    # When: the owner saves it
    stored = service.set_label(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=KEY,
        label="t" * (LABEL_MAX_LENGTH + 1),
        aliases=(),
        now=NOW,
    )

    # Then: the stored wording fits the column extraction also writes to
    assert stored.label is not None
    assert len(stored.label) == LABEL_MAX_LENGTH


def test_a_label_can_be_only_aliases() -> None:
    # Given: an owner who only adds synonyms
    service, _ = _service()

    # When: no label is given
    stored = service.set_label(
        profile_id=PROFILE, target_type=PREFERENCE, key=KEY, label=None, aliases=("tối",), now=NOW
    )

    # Then: the aliases alone still improve the embedded key text
    assert stored.label is None
    assert stored.aliases == ("tối",)


def test_a_label_for_a_key_without_evidence_is_refused() -> None:
    # Given: a key the model does not hold
    service, catalog = _service()

    # When: the owner tries to name it
    with pytest.raises(KeyError):
        service.set_label(
            profile_id=PROFILE,
            target_type=PREFERENCE,
            key="ui.theme.unused",
            label="không dùng",
            aliases=(),
            now=NOW,
        )

    # Then: no orphan row is created that pruning would have to clean up
    assert catalog.entries == {}


def test_a_label_for_another_target_type_of_the_same_key_is_refused() -> None:
    # Given: the key is used as a preference only
    service, _ = _service()

    # When: the owner names the fact of the same name
    with pytest.raises(KeyError):
        service.set_label(
            profile_id=PROFILE,
            target_type=FACT,
            key=KEY,
            label="giao diện tối",
            aliases=(),
            now=NOW,
        )


def test_a_label_with_no_name_and_no_aliases_is_refused() -> None:
    # Given: an empty submission
    service, _ = _service()

    # When: the owner saves it
    with pytest.raises(KeyLabelError) as failure:
        service.set_label(
            profile_id=PROFILE, target_type=PREFERENCE, key=KEY, label=None, aliases=(), now=NOW
        )

    # Then: the owner is told what is missing instead of storing an empty row
    assert str(failure.value) == "A key label needs a name or at least one alias."


def test_whitespace_alone_counts_as_no_label() -> None:
    # Given: a label and aliases that are only spaces
    service, _ = _service()

    # When: they are stored
    with pytest.raises(KeyLabelError):
        service.set_label(
            profile_id=PROFILE,
            target_type=PREFERENCE,
            key=KEY,
            label="   ",
            aliases=("  ", ""),
            now=NOW,
        )


def test_removing_a_label_that_does_not_exist_is_refused() -> None:
    # Given: a key with no stored label
    service, _ = _service()

    # When: the owner removes it
    with pytest.raises(KeyError):
        service.remove(PROFILE, PREFERENCE, KEY)


def test_removing_a_label_lets_extraction_propose_one_again() -> None:
    # Given: an owner label
    service, catalog = _service()
    service.set_label(
        profile_id=PROFILE, target_type=PREFERENCE, key=KEY, label="chế độ tối", aliases=(), now=NOW
    )

    # When: the owner removes it
    service.remove(PROFILE, PREFERENCE, KEY)

    # Then: nothing protects the key any more
    assert catalog.get(PROFILE, PREFERENCE, KEY) is None
    assert catalog.upsert(_extracted()).source is TargetKeyLabelSource.EXTRACTED


def test_listing_returns_every_label_of_the_profile() -> None:
    # Given: labels from both sources
    service, catalog = _service()
    catalog.upsert(_extracted())

    # When: the owner opens the label list
    labels = service.list_for_profile(PROFILE)

    # Then: extracted labels are visible so the owner can correct them
    assert [item.key for item in labels] == [KEY]


def test_cleaning_empty_aliases_returns_nothing() -> None:
    # Given: no alias at all, the empty boundary
    # When/Then: the shared cleaner returns an empty tuple rather than a blank entry
    assert clean_aliases((), None) == ()
    assert clean_aliases(("", "  "), None) == ()
