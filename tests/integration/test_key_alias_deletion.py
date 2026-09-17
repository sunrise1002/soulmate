"""Verify key metadata cleanup on evidence deletion and archive coverage."""

import sqlite3
from pathlib import Path

import pytest
from soulmate_core.domain import EvidenceTargetType, Source, TargetKeyAliasStatus
from soulmate_core.importing import ImportFormat
from soulmate_daemon.config import Settings
from soulmate_daemon.imports import ChatImportService
from soulmate_daemon.portability import ArchiveService, PortabilityError, restore_archive
from soulmate_daemon.system import DEFAULT_PROFILE_ID, ensure_installation
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import text

from .key_alias_support import (
    NOW,
    PROFILE,
    add_evidence,
    add_key_metadata,
    add_profile,
    alias,
    metadata_keys,
    open_storage,
)

pytestmark = pytest.mark.integration
PREFERENCE = EvidenceTargetType.PREFERENCE
SUGGESTED = TargetKeyAliasStatus.SUGGESTED
PASSPHRASE = "correct horse battery"  # noqa: S105 -- synthetic fixture secret.


def _alias_keys(repositories: Repositories, profile_id: str = PROFILE) -> set[str]:
    return {item.alias_key for item in repositories.key_aliases.list_for_profile(profile_id)}


def test_deleting_the_last_evidence_of_a_key_removes_its_aliases_and_metadata(
    tmp_path: Path,
) -> None:
    # Given: two evidence rows for an aliased key and metadata for both keys
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    add_evidence(repositories, "evidence_1", "ui.theme.dark_mode")
    add_evidence(repositories, "evidence_2", "ui.theme.dark_mode")
    add_evidence(repositories, "evidence_other", "work.remote")
    repositories.key_aliases.upsert(alias("ui.theme.dark_mode", "ui.theme.dark"))
    for key in ("ui.theme.dark_mode", "ui.theme.dark", "work.remote"):
        add_key_metadata(database, key)

    # When: one of two supporting evidence rows is deleted
    assert repositories.evidence.remove("evidence_1") is True
    # Then: the alias and the canonical key metadata stay supported
    assert _alias_keys(repositories) == {"ui.theme.dark_mode"}
    assert metadata_keys(database, "target_key_catalog") == {
        "ui.theme.dark_mode",
        "ui.theme.dark",
        "work.remote",
    }

    # When: the last supporting evidence row is deleted
    revision = repositories.evidence.current_revision(PROFILE)
    assert repositories.evidence.remove("evidence_2") is True
    # Then: the alias and both key names disappear, unrelated keys stay
    assert _alias_keys(repositories) == set()
    for table in ("target_key_catalog", "target_key_embeddings"):
        assert metadata_keys(database, table) == {"work.remote"}
    assert repositories.evidence.current_revision(PROFILE) == revision + 1
    database.close()


def test_alias_chains_survive_while_evidence_flows_through_them(tmp_path: Path) -> None:
    # Given: a -> b -> c with evidence only on a, and a dangling d -> e
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    add_evidence(repositories, "evidence_a", "a.key")
    add_evidence(repositories, "evidence_unrelated", "z.key")
    for alias_key, canonical_key in (("a.key", "b.key"), ("b.key", "c.key"), ("d.key", "e.key")):
        repositories.key_aliases.upsert(alias(alias_key, canonical_key))

    # When: unrelated evidence is deleted
    repositories.evidence.remove("evidence_unrelated")
    # Then: the supported chain stays and the dangling alias is removed
    assert _alias_keys(repositories) == {"a.key", "b.key"}

    # When: the evidence feeding the chain is deleted
    repositories.evidence.remove("evidence_a")
    # Then: the whole chain is removed
    assert _alias_keys(repositories) == set()
    database.close()


def test_inactive_aliases_need_both_keys_supported(tmp_path: Path) -> None:
    # Given: a suggestion and a rejection between evidence-backed keys
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    for key in ("ui.theme.light", "ui.theme.dark", "ui.font.small", "ui.font.tiny"):
        add_evidence(repositories, f"evidence_{key}", key)
    repositories.key_aliases.upsert(alias("ui.theme.light", "ui.theme.dark", status=SUGGESTED))
    repositories.key_aliases.upsert(
        alias("ui.font.small", "ui.theme.dark", status=TargetKeyAliasStatus.REJECTED)
    )
    repositories.key_aliases.upsert(alias("ui.font.tiny", "ui.font.small"))

    # When: the canonical key of the inactive aliases loses its evidence
    repositories.evidence.remove("evidence_ui.theme.dark")

    # Then: the inactive aliases are removed although their alias keys keep evidence
    assert repositories.key_aliases.list_for_profile(PROFILE) == (
        alias("ui.font.tiny", "ui.font.small"),
    )
    database.close()


def test_pruning_is_scoped_to_the_deleting_profile(tmp_path: Path) -> None:
    # Given: two profiles with the same unsupported alias and metadata
    database, repositories = open_storage(tmp_path / "soulmate.db")
    add_profile(repositories)
    add_profile(repositories, "profile_other")
    add_evidence(repositories, "evidence_own", "own.key")
    for profile_id in (PROFILE, "profile_other"):
        repositories.key_aliases.upsert(alias("gone.key", "x.key", profile_id=profile_id))
        add_key_metadata(database, "gone.key", profile_id)

    # When: evidence of the first profile is deleted
    repositories.evidence.remove("evidence_own")

    # Then: only the first profile's rows are pruned
    assert _alias_keys(repositories) == set()
    assert _alias_keys(repositories, "profile_other") == {"gone.key"}
    assert metadata_keys(database, "target_key_embeddings") == {"gone.key"}
    database.close()


def test_import_removal_prunes_key_metadata(tmp_path: Path) -> None:
    # Given: an imported message whose evidence carries an aliased key
    database, repositories = open_storage(tmp_path / "soulmate.db")
    ensure_installation(repositories.system_metadata, repositories.profiles)
    imported = ChatImportService(repositories.sources).import_content(
        DEFAULT_PROFILE_ID,
        "Synthetic transcript.md",
        "User: I like dark themes.\nAssistant: Noted.",
        ImportFormat.MARKDOWN,
        NOW,
    )
    assert database.engine is not None
    with database.engine.connect() as connection:
        event_id = connection.execute(
            text("SELECT id FROM raw_events WHERE source_id = :source_id LIMIT 1"),
            {"source_id": imported.source.id},
        ).scalar_one()
    add_evidence(
        repositories,
        "evidence_imported",
        "ui.theme.dark_mode",
        profile_id=DEFAULT_PROFILE_ID,
        source_event_id=event_id,
    )
    repositories.key_aliases.upsert(
        alias("ui.theme.dark_mode", "ui.theme.dark", profile_id=DEFAULT_PROFILE_ID)
    )
    add_key_metadata(database, "ui.theme.dark", DEFAULT_PROFILE_ID)

    # When: the import is removed
    assert repositories.sources.remove_import(DEFAULT_PROFILE_ID, imported.source.id) is not None

    # Then: the alias and key metadata go with the evidence
    assert _alias_keys(repositories, DEFAULT_PROFILE_ID) == set()
    assert metadata_keys(database, "target_key_catalog") == set()
    database.close()


def _seeded_source(tmp_path: Path) -> tuple[Settings, Database]:
    settings = Settings(data_dir=tmp_path / "source")
    database, repositories = open_storage(settings.database_path)
    ensure_installation(repositories.system_metadata, repositories.profiles)
    add_evidence(repositories, "evidence_dark", "ui.theme.dark_mode", profile_id=DEFAULT_PROFILE_ID)
    repositories.key_aliases.upsert(
        alias("ui.theme.dark_mode", "ui.theme.dark", profile_id=DEFAULT_PROFILE_ID)
    )
    add_key_metadata(database, "ui.theme.dark", DEFAULT_PROFILE_ID)
    return settings, database


def _restored_table_keys(settings: Settings) -> dict[str, set[str]]:
    with sqlite3.connect(settings.database_path) as connection:
        return {
            "aliases": {
                row[0] for row in connection.execute("SELECT alias_key FROM target_key_aliases")
            },
            "catalog": {row[0] for row in connection.execute("SELECT key FROM target_key_catalog")},
            "embeddings": {
                row[0] for row in connection.execute("SELECT key FROM target_key_embeddings")
            },
        }


def test_local_backup_restores_aliases_catalog_and_embeddings(tmp_path: Path) -> None:
    # Given: a source installation with all key tables populated
    settings, database = _seeded_source(tmp_path)
    archive = tmp_path / "backup.dtwb"
    # When: a local backup is restored on a fresh installation
    ArchiveService(settings, database).create(archive, created_at=NOW)
    database.close()
    target = Settings(data_dir=tmp_path / "target")
    restored = restore_archive(target, archive)
    # Then: every key table is restored at the head schema
    assert restored.schema_revision_after == "0011_key_consistency"
    assert _restored_table_keys(target) == {
        "aliases": {"ui.theme.dark_mode"},
        "catalog": {"ui.theme.dark"},
        "embeddings": {"ui.theme.dark"},
    }


def test_encrypted_export_keeps_owner_decisions_but_drops_embeddings(tmp_path: Path) -> None:
    # Given: a source installation with all key tables populated
    settings, database = _seeded_source(tmp_path)
    archive = tmp_path / "portable.dtw"
    # When: an encrypted portable export is restored
    ArchiveService(settings, database).create(archive, passphrase=PASSPHRASE, created_at=NOW)
    database.close()
    target = Settings(data_dir=tmp_path / "target")
    restore_archive(target, archive, PASSPHRASE)
    # Then: aliases and labels survive while derived vectors are left to be rebuilt
    assert _restored_table_keys(target) == {
        "aliases": {"ui.theme.dark_mode"},
        "catalog": {"ui.theme.dark"},
        "embeddings": set(),
    }
    live = Database(settings.database_path)
    live.connect()
    assert metadata_keys(live, "target_key_embeddings") == {"ui.theme.dark"}
    live.close()


def test_phase_12_archive_restores_into_the_key_schema(tmp_path: Path) -> None:
    # Given: a backup taken before the key tables existed
    settings = Settings(data_dir=tmp_path / "old")
    database, repositories = open_storage(settings.database_path, "0010_phase_12")
    ensure_installation(repositories.system_metadata, repositories.profiles)
    add_evidence(repositories, "evidence_old", "ui.theme.dark", profile_id=DEFAULT_PROFILE_ID)
    archive = tmp_path / "old.dtwb"
    ArchiveService(settings, database).create(archive, created_at=NOW)
    database.close()
    # When: the old archive is restored
    target = Settings(data_dir=tmp_path / "target")
    restored = restore_archive(target, archive)
    # Then: the schema is upgraded and the key tables start empty
    assert (restored.schema_revision_before, restored.schema_revision_after) == (
        "0010_phase_12",
        "0011_key_consistency",
    )
    assert _restored_table_keys(target) == {"aliases": set(), "catalog": set(), "embeddings": set()}


@pytest.mark.parametrize("table", ["target_key_aliases", "target_key_catalog"])
def test_restore_rejects_targets_holding_owner_key_decisions(tmp_path: Path, table: str) -> None:
    # Given: an archive and a target whose only owner data is key metadata
    source = Settings(data_dir=tmp_path / "source")
    database, _ = open_storage(source.database_path)
    archive = tmp_path / "backup.dtwb"
    ArchiveService(source, database).create(archive, created_at=NOW)
    database.close()
    target = Settings(data_dir=tmp_path / "target")
    target_database, target_repositories = open_storage(target.database_path)
    ensure_installation(target_repositories.system_metadata, target_repositories.profiles)
    if table == "target_key_aliases":
        target_repositories.key_aliases.upsert(
            alias("a.key", "b.key", profile_id=DEFAULT_PROFILE_ID)
        )
    else:
        add_key_metadata(target_database, "a.key", DEFAULT_PROFILE_ID)
    target_database.close()
    # When / Then: restore refuses to overwrite it
    with pytest.raises(PortabilityError, match="fresh installation"):
        restore_archive(target, archive)


def test_restore_treats_derived_embeddings_as_fresh(tmp_path: Path) -> None:
    # Given: a target holding only derived embeddings (no owner data)
    source = Settings(data_dir=tmp_path / "source")
    database, repositories = open_storage(source.database_path)
    ensure_installation(repositories.system_metadata, repositories.profiles)
    repositories.sources.add(Source("source_manual", DEFAULT_PROFILE_ID, "manual", "Fixture", NOW))
    archive = tmp_path / "backup.dtwb"
    ArchiveService(source, database).create(archive, created_at=NOW)
    database.close()
    target = Settings(data_dir=tmp_path / "target")
    target_database, target_repositories = open_storage(target.database_path)
    ensure_installation(target_repositories.system_metadata, target_repositories.profiles)
    assert target_database.engine is not None
    with target_database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO target_key_embeddings (profile_id, target_type, key, model_id, "
                "text_hash, dim, vector, created_at) VALUES "
                "(:profile_id, 'preference', 'a.key', 'fake', 'hash', 1, :vector, :now)"
            ),
            {"profile_id": DEFAULT_PROFILE_ID, "vector": b"\x00" * 4, "now": NOW},
        )
    target_database.close()
    # When: the archive is restored
    restored = restore_archive(target, archive)
    # Then: the restore proceeds
    assert restored.schema_revision_after == "0011_key_consistency"
