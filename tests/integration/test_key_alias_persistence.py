"""Verify migration 0011, the alias repository, and alias-aware model rebuilds."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from soulmate_core.domain import EvidenceTargetType, TargetKeyAliasStatus
from soulmate_core.preferences import ModelRebuilder
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from .key_alias_support import (
    NOW,
    PROFILE,
    add_evidence,
    add_profile,
    alias,
    open_storage,
    semantic,
)

pytestmark = pytest.mark.integration
PREFERENCE = EvidenceTargetType.PREFERENCE
NEW_TABLES = {"target_key_aliases", "target_key_catalog", "target_key_embeddings"}
INSERT_ALIAS = (
    "INSERT INTO target_key_aliases (profile_id, target_type, alias_key, canonical_key, "
    "polarity, method, similarity, status, algorithm_version, created_at, updated_at) VALUES "
    "(:profile_id, :target_type, :alias_key, :canonical_key, :polarity, :method, :similarity, "
    ":status, 'v1', :now, :now)"
)
VALID_ROW: dict[str, object] = {
    "profile_id": PROFILE,
    "target_type": "preference",
    "alias_key": "ui.theme.dark_mode",
    "canonical_key": "ui.theme.dark",
    "polarity": 1,
    "method": "normalized",
    "similarity": None,
    "status": "active",
    "now": NOW,
}


def test_phase_12_database_upgrades_to_key_tables_and_downgrades_cleanly(tmp_path: Path) -> None:
    # Given: a real 0010 database holding evidence
    database, repositories = open_storage(tmp_path / "soulmate.db", "0010_phase_12")
    add_profile(repositories)
    add_evidence(repositories, "evidence_kept", "ui.theme.dark_mode")
    assert database.engine is not None
    assert not NEW_TABLES & set(inspect(database.engine).get_table_names())

    # When: the database migrates to head
    database.migrate()
    # Then: the key tables exist and evidence is untouched
    assert set(inspect(database.engine).get_table_names()) >= NEW_TABLES
    assert database.current_revision() == "0011_key_consistency"
    assert repositories.evidence.get("evidence_kept") is not None
    repositories.key_aliases.upsert(alias("ui.theme.dark_mode", "ui.theme.dark"))

    # When: the migration is downgraded and applied again
    command.downgrade(database.migration_config, "0010_phase_12")
    # Then: only the key tables disappear, and a re-upgrade starts empty
    assert not NEW_TABLES & set(inspect(database.engine).get_table_names())
    assert repositories.evidence.get("evidence_kept") is not None
    database.migrate()
    assert repositories.key_aliases.list_for_profile(PROFILE) == ()
    database.close()


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ({"polarity": 0}, "ck_target_key_aliases_polarity"),
        ({"polarity": 2}, "ck_target_key_aliases_polarity"),
        ({"polarity": -1, "target_type": "fact"}, "ck_target_key_aliases_inversion"),
        ({"target_type": "habit"}, "ck_target_key_aliases_target_type"),
        ({"method": "guess"}, "ck_target_key_aliases_method"),
        ({"status": "pending"}, "ck_target_key_aliases_status"),
        ({"similarity": -0.01}, "ck_target_key_aliases_similarity"),
        ({"similarity": 1.01}, "ck_target_key_aliases_similarity"),
        ({"canonical_key": "ui.theme.dark_mode"}, "ck_target_key_aliases_distinct"),
        ({"profile_id": "profile_missing"}, "FOREIGN KEY"),
    ],
)
def test_alias_table_rejects_invalid_rows(
    tmp_path: Path, override: dict[str, object], constraint: str
) -> None:
    # Given: a migrated database with one profile
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    assert database.engine is not None
    # When: a row violating one database rule is inserted
    # Then: SQLite rejects it with the matching constraint
    with pytest.raises(IntegrityError, match=constraint), database.engine.begin() as connection:
        connection.execute(text(INSERT_ALIAS), {**VALID_ROW, **override})
    database.close()


def test_alias_table_accepts_boundary_similarities(tmp_path: Path) -> None:
    # Given: a migrated database
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    assert database.engine is not None
    # When: similarities at both limits are inserted
    with database.engine.begin() as connection:
        for index, similarity in enumerate((0.0, 1.0)):
            connection.execute(
                text(INSERT_ALIAS),
                {**VALID_ROW, "alias_key": f"key_{index}", "similarity": similarity},
            )
    # Then: both rows are stored
    assert len(repositories.key_aliases.list_for_profile(PROFILE)) == 2
    database.close()


def test_alias_round_trips_across_restart_and_keeps_its_creation_time(tmp_path: Path) -> None:
    # Given: a stored semantic suggestion
    path = tmp_path / "soulmate.db"
    database, repositories = open_storage(path)
    add_profile(repositories)
    suggested = semantic(
        alias("ui.theme.light", "ui.theme.dark", status=TargetKeyAliasStatus.SUGGESTED), 0.91
    )
    assert repositories.key_aliases.upsert(suggested) == suggested
    database.close()

    # When: the database restarts and the owner approves it inverted
    database, repositories = open_storage(path)
    approved = replace(
        suggested,
        polarity=-1,
        status=TargetKeyAliasStatus.ACTIVE,
        created_at=NOW + timedelta(days=1),
        updated_at=NOW + timedelta(days=1),
    )
    stored = repositories.key_aliases.upsert(approved)

    # Then: the update persists and the first creation time is preserved
    assert stored == replace(approved, created_at=NOW)
    assert repositories.key_aliases.get(PROFILE, PREFERENCE, "ui.theme.light") == stored
    database.close()


def test_alias_reads_are_scoped_and_filtered(tmp_path: Path) -> None:
    # Given: aliases for two profiles with different statuses
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    add_profile(repositories, "profile_other")
    rejected = alias("b.key", "b.canonical", status=TargetKeyAliasStatus.REJECTED)
    active = alias("a.key", "a.canonical")
    for item in (rejected, active, alias("a.key", "x.other", profile_id="profile_other")):
        repositories.key_aliases.upsert(item)

    # When / Then: listing is sorted, profile-scoped, and filterable by status
    assert repositories.key_aliases.list_for_profile(PROFILE) == (active, rejected)
    assert repositories.key_aliases.list_for_profile(PROFILE, TargetKeyAliasStatus.ACTIVE) == (
        active,
    )
    assert repositories.key_aliases.list_for_profile("profile_missing") == ()
    assert repositories.key_aliases.get(PROFILE, PREFERENCE, "missing.key") is None
    assert repositories.key_aliases.get(PROFILE, EvidenceTargetType.FACT, "a.key") is None
    database.close()


def test_missing_alias_removal_changes_nothing(tmp_path: Path) -> None:
    # Given: a profile without aliases
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    before = repositories.evidence.current_revision(PROFILE)
    # When: a missing alias is removed
    # Then: nothing is reported and the revision stays
    assert repositories.key_aliases.remove(PROFILE, PREFERENCE, "missing.key") is False
    assert repositories.evidence.current_revision(PROFILE) == before
    database.close()


@pytest.mark.parametrize(
    ("existing", "candidate"),
    [
        ((("a.key", "b.key"),), ("b.key", "a.key")),
        ((("a.key", "b.key"), ("b.key", "c.key")), ("c.key", "a.key")),
    ],
    ids=["direct", "transitive"],
)
def test_active_alias_closing_a_cycle_is_rejected(
    tmp_path: Path, existing: tuple[tuple[str, str], ...], candidate: tuple[str, str]
) -> None:
    # Given: an acyclic active alias chain
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    for alias_key, canonical_key in existing:
        repositories.key_aliases.upsert(alias(alias_key, canonical_key))
    revision = repositories.evidence.current_revision(PROFILE)

    # When: an active alias would close a cycle
    with pytest.raises(ValueError, match="cycle"):
        repositories.key_aliases.upsert(alias(*candidate))

    # Then: nothing is stored and the revision is unchanged
    assert repositories.key_aliases.get(PROFILE, PREFERENCE, candidate[0]) is None
    assert repositories.evidence.current_revision(PROFILE) == revision
    database.close()


def test_cycle_check_ignores_inactive_aliases_and_the_replaced_row(tmp_path: Path) -> None:
    # Given: an active alias a -> b
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    repositories.key_aliases.upsert(alias("a.key", "b.key"))
    suggested = alias("b.key", "a.key", status=TargetKeyAliasStatus.SUGGESTED)

    # When: a cyclic suggestion is stored and a -> b is re-pointed to c
    repositories.key_aliases.upsert(suggested)
    repositories.key_aliases.upsert(alias("a.key", "c.key"))
    # Then: both writes succeed because neither closes an active cycle
    assert repositories.key_aliases.get(PROFILE, PREFERENCE, "b.key") == suggested

    # When: the suggestion is activated while a -> c is active
    repositories.key_aliases.upsert(replace(suggested, status=TargetKeyAliasStatus.ACTIVE))
    # Then: it is accepted, but closing c -> b is rejected
    with pytest.raises(ValueError, match="cycle"):
        repositories.key_aliases.upsert(alias("c.key", "b.key"))
    database.close()


def test_corrupt_persisted_alias_fails_loudly_on_load(tmp_path: Path) -> None:
    # Given: a semantic row without a similarity written outside the repository
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    assert database.engine is not None
    with database.engine.begin() as connection:
        connection.execute(text(INSERT_ALIAS), {**VALID_ROW, "method": "semantic"})
    # When / Then: loading it raises the domain validation error
    with pytest.raises(ValueError, match="must record a similarity"):
        repositories.key_aliases.list_for_profile(PROFILE)
    database.close()


def test_alias_changes_invalidate_snapshots_and_undo_restores_grouping(tmp_path: Path) -> None:
    # Given: opposite keys learned separately and a current snapshot
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    add_evidence(repositories, "evidence_dark", "ui.theme.dark", 0.8)
    add_evidence(repositories, "evidence_light", "ui.theme.light", -0.6)
    rebuilder = ModelRebuilder(
        repositories.evidence, repositories.personal_models, repositories.key_aliases
    )
    first = rebuilder.current(PROFILE, NOW)
    assert [item.key for item in first.model.preferences] == ["ui.theme.dark", "ui.theme.light"]

    # When: the owner merges light into dark with inverted polarity
    repositories.key_aliases.upsert(alias("ui.theme.light", "ui.theme.dark", polarity=-1))
    merged = rebuilder.current(PROFILE, NOW)

    # Then: the stale snapshot is rebuilt with one reinforced entry
    assert merged.version == first.version + 1
    assert merged.evidence_revision == repositories.evidence.current_revision(PROFILE)
    assert [item.key for item in merged.model.preferences] == ["ui.theme.dark"]
    assert merged.model.preferences[0].supporting_evidence_ids == (
        "evidence_dark",
        "evidence_light",
    )
    assert merged.model.preferences[0].value > 0
    assert rebuilder.current_model(PROFILE) == merged.model

    # When: the alias is removed again
    assert repositories.key_aliases.remove(PROFILE, PREFERENCE, "ui.theme.light") is True
    restored = rebuilder.current(PROFILE, NOW)
    # Then: the next read rebuilds the original grouping
    assert restored.version == merged.version + 1
    assert [
        (item.key, item.value, item.supporting_evidence_ids) for item in restored.model.preferences
    ] == [(item.key, item.value, item.supporting_evidence_ids) for item in first.model.preferences]
    database.close()


def test_rebuilder_ignores_suggestions_and_works_without_alias_repository(tmp_path: Path) -> None:
    # Given: a suggested alias between two stored keys
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    add_evidence(repositories, "evidence_dark", "ui.theme.dark_mode")
    add_evidence(repositories, "evidence_canonical", "ui.theme.dark")
    repositories.key_aliases.upsert(
        alias("ui.theme.dark_mode", "ui.theme.dark", status=TargetKeyAliasStatus.SUGGESTED)
    )
    # When: the model is read with and without the alias repository
    with_aliases = ModelRebuilder(
        repositories.evidence, repositories.personal_models, repositories.key_aliases
    ).current_model(PROFILE)
    without_aliases = ModelRebuilder(
        repositories.evidence, repositories.personal_models
    ).current_model(PROFILE)
    # Then: suggestions never change grouping
    assert with_aliases == without_aliases
    assert len(with_aliases.preferences) == 2
    database.close()
