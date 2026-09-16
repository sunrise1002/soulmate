"""Exercise the owner-only Phase 10 data API."""

import base64
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AnyHttpUrl, SecretStr
from soulmate_daemon.app import create_app
from soulmate_daemon.config import (
    PrivacyConfig,
    RemoteBackupConfig,
    S3BackupConfig,
    Settings,
)
from soulmate_daemon.portability import ArchiveResult
from soulmate_daemon.remote_backup import RemoteBackupObject

pytestmark = pytest.mark.integration
OWNER_CLIENT = ("127.0.0.1", 50000)
REMOTE_CLIENT = ("192.168.1.50", 51000)


class MemoryBackupStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.records: dict[str, RemoteBackupObject] = {}

    def upload(self, archive: ArchiveResult) -> RemoteBackupObject:
        key = f"owner/{archive.path.name}"
        record = RemoteBackupObject(key, archive.size_bytes, archive.created_at)
        self.objects[key] = archive.path.read_bytes()
        self.records[key] = record
        return record

    def latest(self) -> RemoteBackupObject | None:
        return max(self.records.values(), key=lambda item: item.last_modified, default=None)

    def download(self, remote: RemoteBackupObject, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[remote.key])


def _remote_settings(data_dir: Path, *, automatic_daily: bool = False) -> Settings:
    return Settings(
        data_dir=data_dir,
        privacy=PrivacyConfig(mode="hybrid"),
        remote_backup=RemoteBackupConfig(
            backend="s3",
            automatic_daily=automatic_daily,
            passphrase=SecretStr("synthetic remote phrase"),
            s3=S3BackupConfig(
                endpoint_url=AnyHttpUrl("https://backup.example.test"),
                bucket="private-backups",
                access_key_id=SecretStr("synthetic-access-key"),
                secret_access_key=SecretStr("synthetic-secret-key"),
            ),
        ),
    )


def _owner(app: FastAPI) -> TestClient:
    return TestClient(app, client=OWNER_CLIENT)


def test_owner_imports_backs_up_deletes_and_restores_on_restart(tmp_path: Path) -> None:
    source_settings = Settings(data_dir=tmp_path / "machine-a")
    with _owner(create_app(source_settings)) as owner:
        imported = owner.post(
            "/v1/data/imports",
            json={
                "name": "Synthetic notes.md",
                "format": "auto",
                "content": "# Transcript\nUser: I like focused work.\nAssistant: Noted.",
            },
        )
        assert imported.status_code == 201
        source_id = imported.json()["source"]["id"]
        assert imported.json()["detected_format"] == "markdown"
        assert imported.json()["message_count"] == 2
        assert len(owner.get("/v1/conversations").json()) == 1
        assert owner.get("/v1/data/sources").json()[0]["id"] == source_id

        backup = owner.post("/v1/data/backups")
        assert backup.status_code == 201
        backup_path = Path(backup.json()["path"])
        assert backup_path.is_file()
        assert backup.json()["encrypted"] is False

        exported = owner.post(
            "/v1/data/exports",
            json={"passphrase": "synthetic export phrase"},
        )
        assert exported.status_code == 201
        assert Path(exported.json()["path"]).read_bytes().startswith(b"SOULMATE-DTW\x00")

        deleted = owner.delete(f"/v1/data/sources/{source_id}")
        assert deleted.status_code == 200
        assert deleted.json()["message_count"] == 2
        assert deleted.json()["snapshot_version"] == 1
        assert owner.get("/v1/conversations").json() == []
        assert owner.delete(f"/v1/data/sources/{source_id}").status_code == 404

    target_settings = Settings(data_dir=tmp_path / "machine-b")
    encoded = base64.b64encode(backup_path.read_bytes()).decode("ascii")
    with _owner(create_app(target_settings)) as owner:
        staged = owner.post("/v1/data/restores", json={"archive_base64": encoded})
        assert staged.status_code == 202
        assert staged.json()["restart_required"] is True

    with _owner(create_app(target_settings)) as restored_owner:
        conversations = restored_owner.get("/v1/conversations").json()
        assert len(conversations) == 1
        assert conversations[0]["messages"][0]["content"] == "I like focused work."
        assert restored_owner.get("/v1/data/sources").json()[0]["name"] == "Synthetic notes.md"


def test_data_operations_are_owner_only(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "owner-data"))
    with TestClient(app, client=REMOTE_CLIENT) as remote:
        assert remote.get("/v1/data/sources").status_code == 403
        assert remote.post("/v1/data/backups").status_code == 403
        assert remote.post("/v1/data/remote-backups").status_code == 403
        assert remote.post("/v1/data/remote-restores/latest").status_code == 403


def test_owner_uploads_and_restores_latest_encrypted_remote_backup(tmp_path: Path) -> None:
    store = MemoryBackupStore()
    source_settings = _remote_settings(tmp_path / "machine-a")
    with _owner(create_app(source_settings, remote_backup_store=store)) as owner:
        imported = owner.post(
            "/v1/data/imports",
            json={
                "name": "Synthetic remote notes.md",
                "content": "User: I prefer portable systems.\nAssistant: Noted.",
            },
        )
        uploaded = owner.post("/v1/data/remote-backups")
        status = owner.get("/v1/data/remote-backups/status")

        assert imported.status_code == 201
        assert uploaded.status_code == 201
        assert uploaded.json()["archive"]["encrypted"] is True
        assert uploaded.json()["backend"] == "s3"
        assert status.json()["configured"] is True
        assert datetime.fromisoformat(status.json()["last_success_at"]).tzinfo is UTC

    target_settings = _remote_settings(tmp_path / "machine-b")
    with _owner(create_app(target_settings, remote_backup_store=store)) as owner:
        staged = owner.post("/v1/data/remote-restores/latest")
        assert staged.status_code == 202
        assert staged.json()["restart_required"] is True

    with _owner(create_app(target_settings, remote_backup_store=store)) as restored:
        sources = restored.get("/v1/data/sources").json()
        assert sources[0]["name"] == "Synthetic remote notes.md"


def test_daily_remote_backup_runs_once_and_survives_daemon_restart(tmp_path: Path) -> None:
    store = MemoryBackupStore()
    settings = _remote_settings(tmp_path / "owner-data", automatic_daily=True)

    with _owner(create_app(settings, remote_backup_store=store)):
        deadline = time.monotonic() + 3
        while not store.records and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(store.records) == 1

    with _owner(create_app(settings, remote_backup_store=store)):
        time.sleep(0.4)
        assert len(store.records) == 1
