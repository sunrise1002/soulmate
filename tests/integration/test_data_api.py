"""Exercise the owner-only Phase 10 data API."""

import base64
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings

pytestmark = pytest.mark.integration
OWNER_CLIENT = ("127.0.0.1", 50000)
REMOTE_CLIENT = ("192.168.1.50", 51000)


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
