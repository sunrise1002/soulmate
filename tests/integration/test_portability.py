"""Verify Phase 10 imports, source deletion, archives, and model migration."""

import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from soulmate_core.domain import (
    Evidence,
    EvidenceTargetType,
    RawEvent,
    Source,
)
from soulmate_core.importing import ImportFormat
from soulmate_core.preferences import ModelRebuilder
from soulmate_daemon.config import Settings
from soulmate_daemon.imports import ChatImportService
from soulmate_daemon.portability import ArchiveService, PortabilityError, restore_archive
from soulmate_daemon.system import DEFAULT_PROFILE_ID, ensure_installation
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import text

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 12, tzinfo=UTC)


def _storage(path: Path, revision: str = "head") -> tuple[Database, Repositories]:
    database = Database(path)
    database.connect()
    command.upgrade(database.migration_config, revision)
    repositories = Repositories(database.sessions())
    ensure_installation(repositories.system_metadata, repositories.profiles)
    return database, repositories


def test_import_is_atomic_and_source_deletion_removes_derivatives(tmp_path: Path) -> None:
    database, repositories = _storage(tmp_path / "source" / "soulmate.db")
    result = ChatImportService(repositories.sources).import_content(
        DEFAULT_PROFILE_ID,
        "Synthetic transcript.md",
        "User: I prefer small teams.\nAssistant: Understood.",
        ImportFormat.MARKDOWN,
        NOW,
    )
    assert database.engine is not None
    with database.engine.connect() as connection:
        event_id, message_id = connection.execute(
            text(
                "SELECT raw_events.id, json_extract(raw_events.content_json, '$.message_id') "
                "FROM raw_events WHERE source_id = :source_id AND "
                "json_extract(raw_events.content_json, '$.role') = 'user'"
            ),
            {"source_id": result.source.id},
        ).one()
    repositories.evidence.add(
        Evidence(
            "evidence_imported",
            DEFAULT_PROFILE_ID,
            EvidenceTargetType.PREFERENCE,
            "work.team_size",
            0.8,
            0.9,
            0.9,
            {},
            "explicit_statement",
            event_id,
            "import-test-v1",
            NOW,
            source_message_id=message_id,
        )
    )
    before = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
        DEFAULT_PROFILE_ID, NOW
    )

    deletion = repositories.sources.remove_import(DEFAULT_PROFILE_ID, result.source.id)
    assert deletion is not None
    after = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
        DEFAULT_PROFILE_ID, NOW
    )

    assert result.conversation_count == 1
    assert result.message_count == 2
    assert deletion.raw_event_count == 2
    assert deletion.conversation_count == 1
    assert deletion.message_count == 2
    assert deletion.evidence_count == 1
    assert repositories.sources.get(result.source.id) is None
    assert repositories.raw_events.get(event_id) is None
    assert repositories.evidence.get("evidence_imported") is None
    assert after.version == before.version + 1
    assert after.model.preferences == ()
    database.close()


def test_backup_restores_data_but_not_credentials_or_installation_identity(
    tmp_path: Path,
) -> None:
    source_settings = Settings(data_dir=tmp_path / "machine-a")
    database, repositories = _storage(source_settings.database_path)
    original_installation = repositories.system_metadata.get("installation_id")
    source = Source("source_manual", DEFAULT_PROFILE_ID, "manual", "Synthetic", NOW)
    event = RawEvent(
        "event_manual",
        DEFAULT_PROFILE_ID,
        source.id,
        "synthetic",
        {"value": "private fixture"},
        NOW,
        NOW,
    )
    repositories.sources.add(source)
    repositories.raw_events.add(event)
    repositories.evidence.add(
        Evidence(
            "evidence_manual",
            DEFAULT_PROFILE_ID,
            EvidenceTargetType.PREFERENCE,
            "work.remote",
            0.7,
            1.0,
            1.0,
            {},
            "explicit_statement",
            event.id,
            "portability-test-v1",
            NOW,
        )
    )
    ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
        DEFAULT_PROFILE_ID, NOW
    )
    assert database.engine is not None
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO service_identities "
                "(id, profile_id, name, description, created_at, revoked_at) "
                "VALUES ('service_synthetic', :profile_id, 'Synthetic', NULL, :created_at, NULL)"
            ),
            {"profile_id": DEFAULT_PROFILE_ID, "created_at": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO api_credentials "
                "(id, service_identity_id, secret_hash, created_at, last_used_at, revoked_at) "
                "VALUES ('credential_synthetic', 'service_synthetic', 'hash-only', "
                ":created_at, NULL, NULL)"
            ),
            {"created_at": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO service_identity_scopes (service_identity_id, scope) "
                "VALUES ('service_synthetic', 'model:summary:read')"
            )
        )
    archive = tmp_path / "backup.dtwb"
    created = ArchiveService(source_settings, database).create(archive, created_at=NOW)
    database.close()

    target_settings = Settings(data_dir=tmp_path / "machine-b")
    restored = restore_archive(target_settings, archive)
    restored_database = Database(target_settings.database_path)
    restored_database.connect()
    restored_repositories = Repositories(restored_database.sessions())

    assert created.encrypted is False
    assert restored.schema_revision_after == "0010_phase_12"
    assert restored.installation_id != original_installation
    assert restored_repositories.raw_events.get(event.id) == event
    assert restored_repositories.evidence.get("evidence_manual") is not None
    assert restored_repositories.service_identities.get("service_synthetic") is not None
    assert restored_repositories.api_credentials.list_for_identity("service_synthetic") == ()
    assert restored_repositories.personal_models.latest_snapshot(DEFAULT_PROFILE_ID) is not None
    restored_database.close()


def test_encrypted_export_authenticates_and_migrates_an_older_model(
    tmp_path: Path,
) -> None:
    source_settings = Settings(data_dir=tmp_path / "old-machine")
    database, repositories = _storage(source_settings.database_path, "0007_phase_9")
    event = RawEvent(
        "event_old",
        DEFAULT_PROFILE_ID,
        None,
        "synthetic",
        {},
        NOW,
        NOW,
    )
    repositories.raw_events.add(event)
    repositories.evidence.add(
        Evidence(
            "evidence_old",
            DEFAULT_PROFILE_ID,
            EvidenceTargetType.PREFERENCE,
            "tools.local_first",
            1.0,
            1.0,
            1.0,
            {},
            "explicit_statement",
            event.id,
            "old-model-v1",
            NOW,
        )
    )
    ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
        DEFAULT_PROFILE_ID, NOW
    )
    archive = tmp_path / "portable.dtw"
    ArchiveService(source_settings, database).create(
        archive,
        passphrase="correct horse battery",  # noqa: S106 -- synthetic fixture secret.
        created_at=NOW,
    )
    database.close()

    with pytest.raises(PortabilityError, match="incorrect or the archive was modified"):
        restore_archive(Settings(data_dir=tmp_path / "wrong"), archive, "wrong password here")

    target_settings = Settings(data_dir=tmp_path / "new-machine")
    restored = restore_archive(target_settings, archive, "correct horse battery")

    assert restored.schema_revision_before == "0007_phase_9"
    assert restored.schema_revision_after == "0010_phase_12"
    with sqlite3.connect(target_settings.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
    assert "source_id" in columns


def test_restore_rejects_nonfresh_installations(tmp_path: Path) -> None:
    source_settings = Settings(data_dir=tmp_path / "source")
    database, _ = _storage(source_settings.database_path)
    archive = tmp_path / "backup.dtwb"
    ArchiveService(source_settings, database).create(archive, created_at=NOW)
    database.close()

    target_settings = Settings(data_dir=tmp_path / "target")
    target_database, target_repositories = _storage(target_settings.database_path)
    source = Source("existing", DEFAULT_PROFILE_ID, "manual", "Existing", NOW)
    target_repositories.sources.add(source)
    target_database.close()

    with pytest.raises(PortabilityError, match="fresh installation"):
        restore_archive(target_settings, archive)


def test_backup_manifest_contains_no_credentials(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    database, _ = _storage(settings.database_path)
    archive_path = tmp_path / "backup.dtwb"
    ArchiveService(settings, database).create(archive_path, created_at=NOW)
    database.close()

    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format_version"] == 1
    assert manifest["credentials_included"] is False
