"""Remote backup service, storage port, and durable scheduling behavior."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from mypy_boto3_s3.client import S3Client
from pydantic import AnyHttpUrl, SecretStr
from soulmate_daemon.config import PrivacyConfig, RemoteBackupConfig, S3BackupConfig, Settings
from soulmate_daemon.portability import ARCHIVE_MAGIC, ArchiveResult
from soulmate_daemon.remote_backup import (
    LAST_REMOTE_BACKUP_AT,
    RemoteBackupError,
    RemoteBackupObject,
    RemoteBackupService,
    S3RemoteBackupStore,
    build_remote_backup_store,
    enqueue_remote_backup_if_due,
)
from soulmate_storage_sqlite import Database, Repositories

NOW = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)


class MemoryBackupStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.records: dict[str, RemoteBackupObject] = {}

    def upload(self, archive: ArchiveResult) -> RemoteBackupObject:
        path = archive.path
        key = f"portable/{path.name}"
        record = RemoteBackupObject(key, archive.size_bytes, archive.created_at)
        self.objects[key] = path.read_bytes()
        self.records[key] = record
        return record

    def latest(self) -> RemoteBackupObject | None:
        return max(self.records.values(), key=lambda item: item.last_modified, default=None)

    def download(self, remote: RemoteBackupObject, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[remote.key])


class FakeS3Client:
    def __init__(self) -> None:
        self.uploaded: tuple[str, str, str, dict[str, object]] | None = None
        self.pages: list[dict[str, object]] = []
        self.download_body = b"encrypted-archive"

    def upload_file(self, filename: str, bucket: str, key: str, **kwargs: object) -> None:
        extra_args = cast(dict[str, object], kwargs["ExtraArgs"])
        self.uploaded = (filename, bucket, key, extra_args)

    def list_objects_v2(self, **_kwargs: object) -> dict[str, object]:
        return self.pages.pop(0)

    def download_file(self, _bucket: str, _key: str, destination: str) -> None:
        Path(destination).write_bytes(self.download_body)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        privacy=PrivacyConfig(mode="hybrid"),
        remote_backup=RemoteBackupConfig(
            backend="s3",
            automatic_daily=True,
            passphrase=SecretStr("synthetic backup phrase"),
            s3=S3BackupConfig(
                endpoint_url=AnyHttpUrl("https://backup.example.test"),
                bucket="private-backups",
                access_key_id=SecretStr("synthetic-access-key"),
                secret_access_key=SecretStr("synthetic-secret-key"),
            ),
        ),
    )


def test_remote_backup_is_encrypted_and_downloadable_through_port(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.migrate()
    repositories = Repositories(database.sessions())
    store = MemoryBackupStore()
    service = RemoteBackupService(settings, database, repositories.system_metadata, store)

    result = service.create_and_upload(NOW)
    downloaded = service.download_latest()

    assert result.archive.encrypted is True
    assert result.archive.path.read_bytes().startswith(ARCHIVE_MAGIC)
    assert downloaded.path.read_bytes() == result.archive.path.read_bytes()
    assert repositories.system_metadata.get(LAST_REMOTE_BACKUP_AT) == NOW.isoformat()
    database.close()


def test_daily_enqueue_is_persisted_and_becomes_due_after_interval(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.migrate()
    repositories = Repositories(database.sessions())

    first = enqueue_remote_backup_if_due(
        repositories.jobs,
        repositories.system_metadata,
        now=NOW,
    )
    duplicate = enqueue_remote_backup_if_due(
        repositories.jobs,
        repositories.system_metadata,
        now=NOW + timedelta(hours=23),
    )
    next_day = enqueue_remote_backup_if_due(
        repositories.jobs,
        repositories.system_metadata,
        now=NOW + timedelta(hours=24),
    )

    assert first is not None
    assert repositories.jobs.get(first.id) == first
    assert duplicate is None
    assert next_day is not None
    database.close()


def test_external_store_is_denied_until_hybrid_privacy_is_explicit(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"privacy": PrivacyConfig()})

    with pytest.raises(RemoteBackupError, match="privacy mode denied"):
        build_remote_backup_store(settings)


def test_s3_adapter_uses_versioned_keys_and_selects_latest_object(tmp_path: Path) -> None:
    client = FakeS3Client()
    client.pages = [
        {
            "Contents": [
                {
                    "Key": "soulmate/2026/09/15/older.dtw",
                    "Size": 10,
                    "LastModified": NOW - timedelta(days=1),
                },
                {
                    "Key": "soulmate/ignore.txt",
                    "Size": 1,
                    "LastModified": NOW + timedelta(days=1),
                },
            ],
            "IsTruncated": True,
            "NextContinuationToken": "next-page",
        },
        {
            "Contents": [
                {
                    "Key": "soulmate/2026/09/16/latest.dtw",
                    "Size": len(client.download_body),
                    "LastModified": NOW,
                }
            ],
            "IsTruncated": False,
        },
    ]
    store = S3RemoteBackupStore(_settings(tmp_path), client=cast(S3Client, client))
    archive_path = tmp_path / "soulmate-remote-backup.dtw"
    archive_path.write_bytes(client.download_body)
    archive = ArchiveResult(
        path=archive_path,
        created_at=NOW,
        size_bytes=len(client.download_body),
        sha256="a" * 64,
        encrypted=True,
        schema_revision="0010_phase_12",
    )

    uploaded = store.upload(archive)
    latest = store.latest()
    assert latest is not None
    destination = tmp_path / "downloaded.dtw"
    store.download(latest, destination)

    assert uploaded.key == "soulmate/2026/09/16/soulmate-remote-backup.dtw"
    assert client.uploaded is not None
    assert client.uploaded[1:3] == ("private-backups", uploaded.key)
    assert latest.key.endswith("latest.dtw")
    assert destination.read_bytes() == client.download_body
