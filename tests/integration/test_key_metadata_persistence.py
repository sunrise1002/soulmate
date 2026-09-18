"""Stored key labels and key vectors on a real migrated database."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from soulmate_core.domain import (
    EvidenceTargetType,
    TargetKeyEmbedding,
    TargetKeyLabel,
    TargetKeyLabelSource,
)
from soulmate_storage_sqlite import Repositories

from .key_alias_support import NOW, PROFILE, add_evidence, add_profile, open_storage

pytestmark = pytest.mark.integration

PREFERENCE = EvidenceTargetType.PREFERENCE
FACT = EvidenceTargetType.FACT
LATER = datetime(2026, 9, 19, tzinfo=UTC)


def _label(
    key: str = "ui.theme.dark",
    *,
    label: str | None = "giao diện tối",
    aliases: tuple[str, ...] = ("nền tối",),
    source: TargetKeyLabelSource = TargetKeyLabelSource.EXTRACTED,
    target_type: EvidenceTargetType = PREFERENCE,
    created_at: datetime = NOW,
) -> TargetKeyLabel:
    return TargetKeyLabel(
        profile_id=PROFILE,
        target_type=target_type,
        key=key,
        label=label,
        aliases=aliases,
        source=source,
        created_at=created_at,
        updated_at=created_at,
    )


def _embedding(
    key: str = "ui.theme.dark",
    *,
    vector: tuple[float, ...] = (0.5, -0.25, 0.125),
    model_id: str = "fake-concept-v1",
    text_hash: str = "hash-1",
) -> TargetKeyEmbedding:
    return TargetKeyEmbedding(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=key,
        model_id=model_id,
        text_hash=text_hash,
        vector=vector,
        created_at=NOW,
    )


def _storage(tmp_path: Path) -> Repositories:
    _, repositories = open_storage(tmp_path / "keys.sqlite3")
    add_profile(repositories)
    return repositories


def test_a_label_survives_a_restart_with_its_wording_intact(tmp_path: Path) -> None:
    # Given: a label stored with Vietnamese wording
    database, repositories = open_storage(tmp_path / "keys.sqlite3")
    add_profile(repositories)
    repositories.key_catalog.upsert(_label())
    assert database.engine is not None
    database.engine.dispose()

    # When: the database is reopened
    _, reopened = open_storage(tmp_path / "keys.sqlite3")
    stored = reopened.key_catalog.get(PROFILE, PREFERENCE, "ui.theme.dark")

    # Then: the label, its aliases, and its source are unchanged
    assert stored is not None
    assert (stored.label, stored.aliases) == ("giao diện tối", ("nền tối",))
    assert stored.source is TargetKeyLabelSource.EXTRACTED
    assert stored.created_at == NOW


def test_extraction_never_overwrites_an_owner_label(tmp_path: Path) -> None:
    # Given: a label the owner edited
    repositories = _storage(tmp_path)
    repositories.key_catalog.upsert(_label(source=TargetKeyLabelSource.OWNER))

    # When: a later extraction proposes different wording
    returned = repositories.key_catalog.upsert(
        _label(label="dark theme", aliases=(), created_at=LATER)
    )

    # Then: the owner wording stands
    assert (returned.label, returned.aliases) == ("giao diện tối", ("nền tối",))
    assert returned.source is TargetKeyLabelSource.OWNER


def test_an_owner_edit_replaces_an_extracted_label_and_keeps_its_creation_time(
    tmp_path: Path,
) -> None:
    # Given: an extracted label
    repositories = _storage(tmp_path)
    repositories.key_catalog.upsert(_label())

    # When: the owner renames the key
    returned = repositories.key_catalog.upsert(
        _label(label="chế độ đêm", aliases=(), source=TargetKeyLabelSource.OWNER, created_at=LATER)
    )

    # Then: the owner wording wins while the first creation time is preserved
    assert (returned.label, returned.aliases, returned.created_at) == ("chế độ đêm", (), NOW)
    assert returned.updated_at == LATER


def test_labels_are_listed_per_profile_and_removed_individually(tmp_path: Path) -> None:
    # Given: labels of two target types and one of another profile
    repositories = _storage(tmp_path)
    add_profile(repositories, "profile_other")
    repositories.key_catalog.upsert(_label())
    repositories.key_catalog.upsert(_label("work.location", target_type=FACT))
    repositories.key_catalog.upsert(replace(_label("other.key"), profile_id="profile_other"))

    # When: the profile is listed and one label is removed
    listed = repositories.key_catalog.list_for_profile(PROFILE)
    removed = repositories.key_catalog.remove(PROFILE, FACT, "work.location")

    # Then: only this profile's labels were listed and the removal is reported
    assert [item.key for item in listed] == ["work.location", "ui.theme.dark"]
    assert removed is True
    assert repositories.key_catalog.get(PROFILE, FACT, "work.location") is None


def test_removing_an_unknown_label_reports_no_change(tmp_path: Path) -> None:
    # Given: an empty catalog
    repositories = _storage(tmp_path)

    # When: an unknown key is removed
    # Then: the caller learns nothing was stored
    assert repositories.key_catalog.remove(PROFILE, PREFERENCE, "ui.theme.dark") is False
    assert repositories.key_catalog.get(PROFILE, PREFERENCE, "ui.theme.dark") is None


def test_a_label_must_carry_wording() -> None:
    # Given: neither a label nor aliases
    # When: the record is built
    # Then: it is rejected before reaching the database
    with pytest.raises(ValueError, match="must carry a label or aliases"):
        _label(label=None, aliases=())


@pytest.mark.parametrize(
    ("label", "aliases", "message"),
    [
        ("   ", ("nền tối",), "absent or non-empty"),
        ("giao diện tối", (" ",), "must not be empty"),
        ("giao diện tối", ("nền tối", "nền tối"), "must be unique"),
    ],
)
def test_invalid_label_wording_is_rejected(
    label: str, aliases: tuple[str, ...], message: str
) -> None:
    # Given: blank, empty, or duplicated wording
    # When: the record is built
    # Then: each case is rejected with its own message
    with pytest.raises(ValueError, match=message):
        _label(label=label, aliases=aliases)


def test_vectors_round_trip_through_storage(tmp_path: Path) -> None:
    # Given: a vector with negative and fractional components
    repositories = _storage(tmp_path)

    # When: it is written and read back
    written = repositories.key_embeddings.replace_many([_embedding()])
    stored = repositories.key_embeddings.list_for_model(PROFILE, "fake-concept-v1")

    # Then: the vector, its dimension, and its text hash survive exactly
    assert written == 1
    assert len(stored) == 1
    assert stored[0].vector == (0.5, -0.25, 0.125)
    assert (stored[0].dim, stored[0].text_hash) == (3, "hash-1")


def test_writing_a_key_again_replaces_its_vector(tmp_path: Path) -> None:
    # Given: a stored vector
    repositories = _storage(tmp_path)
    repositories.key_embeddings.replace_many([_embedding()])

    # When: the same key and model are written with new values
    repositories.key_embeddings.replace_many([_embedding(vector=(1.0, 0.0), text_hash="hash-2")])
    stored = repositories.key_embeddings.list_for_model(PROFILE, "fake-concept-v1")

    # Then: one row remains, holding the new vector
    assert len(stored) == 1
    assert (stored[0].vector, stored[0].text_hash) == ((1.0, 0.0), "hash-2")


def test_writing_no_vector_touches_nothing(tmp_path: Path) -> None:
    # Given: an empty write
    repositories = _storage(tmp_path)

    # When: the empty collection is written
    # Then: the repository reports no rows and stores none
    assert repositories.key_embeddings.replace_many([]) == 0
    assert repositories.key_embeddings.list_for_model(PROFILE, "fake-concept-v1") == ()


def test_vectors_are_listed_per_model_only(tmp_path: Path) -> None:
    # Given: vectors of two models
    repositories = _storage(tmp_path)
    repositories.key_embeddings.replace_many(
        [_embedding(), _embedding(model_id="retired-model", vector=(1.0,))]
    )

    # When: one model is listed
    current = repositories.key_embeddings.list_for_model(PROFILE, "fake-concept-v1")

    # Then: the other model's vector is not returned
    assert [item.model_id for item in current] == ["fake-concept-v1"]


def test_changing_the_model_drops_the_vectors_of_every_other_model(tmp_path: Path) -> None:
    # Given: vectors of a retired model and the current model
    repositories = _storage(tmp_path)
    repositories.key_embeddings.replace_many(
        [_embedding(), _embedding(model_id="retired-model", vector=(1.0,))]
    )

    # When: the other models are removed
    removed = repositories.key_embeddings.remove_other_models(PROFILE, "fake-concept-v1")

    # Then: only the current model survives
    assert removed == 1
    assert repositories.key_embeddings.list_for_model(PROFILE, "retired-model") == ()
    assert len(repositories.key_embeddings.list_for_model(PROFILE, "fake-concept-v1")) == 1


def test_an_empty_vector_is_rejected() -> None:
    # Given: a vector with no components
    # When: the record is built
    # Then: it is rejected before reaching the database
    with pytest.raises(ValueError, match="vector must not be empty"):
        _embedding(vector=())


@pytest.mark.parametrize("field", ["key", "model_id", "text_hash"])
def test_an_embedding_without_identity_is_rejected(field: str) -> None:
    # Given: a missing identity field
    # When: the record is built
    # Then: the record refuses to exist
    with pytest.raises(ValueError, match="identity fields must not be empty"):
        _embedding(**{field: ""})  # type: ignore[arg-type]


def test_deleting_the_last_evidence_of_a_key_prunes_its_label_and_vector(
    tmp_path: Path,
) -> None:
    # Given: a key with evidence, a label, and a vector
    repositories = _storage(tmp_path)
    add_evidence(repositories, "evidence_dark", "ui.theme.dark")
    repositories.key_catalog.upsert(_label())
    repositories.key_embeddings.replace_many([_embedding()])

    # When: the only evidence of that key is deleted
    assert repositories.evidence.remove("evidence_dark") is True

    # Then: neither the owner wording nor the derived vector lingers
    assert repositories.key_catalog.get(PROFILE, PREFERENCE, "ui.theme.dark") is None
    assert repositories.key_embeddings.list_for_model(PROFILE, "fake-concept-v1") == ()
