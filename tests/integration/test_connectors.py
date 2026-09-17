"""Exercise connector discovery, consent, durable sync, restart, and deletion."""

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_connector_sdk import (
    ConnectorContext,
    ConnectorCredential,
    ConnectorEvent,
    ConnectorManifest,
    ConnectorPermission,
    ConnectorSyncRequest,
    ConnectorSyncResult,
)
from soulmate_core.domain import Evidence, EvidenceTargetType
from soulmate_core.preferences import ModelRebuilder
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.connectors import credential_environment_name
from soulmate_daemon.system import DEFAULT_PROFILE_ID
from sqlalchemy import text

from .key_alias_support import alias

pytestmark = pytest.mark.integration
OWNER_CLIENT = ("127.0.0.1", 50000)
REMOTE_CLIENT = ("192.168.1.50", 51000)


class CredentialConnector:
    manifest = ConnectorManifest(
        connector_id="example.credential-test",
        name="Credential test",
        version="1.0.0",
        description="Synthetic credential connector.",
        permissions=(
            ConnectorPermission.CREDENTIALS_READ,
            ConnectorPermission.DATA_READ,
            ConnectorPermission.LEARNING_INGEST,
        ),
        data_access=("Synthetic credential-protected record",),
        credentials=(ConnectorCredential("token", "Synthetic token"),),
    )

    async def sync(
        self, request: ConnectorSyncRequest, context: ConnectorContext
    ) -> ConnectorSyncResult:
        assert request.configuration == {}
        assert context.credentials == {"token": "synthetic-secret-value"}
        return ConnectorSyncResult(
            events=(
                ConnectorEvent(
                    "credential-item",
                    "connector_synthetic_credential",
                    {"value": "safe record"},
                    datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ),
            cursor=None,
        )


def _owner(app: FastAPI) -> TestClient:
    return TestClient(app, client=OWNER_CLIENT)


def _wait_for_job(owner: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = owner.get(f"/v1/connectors/syncs/{job_id}")
        assert result.status_code == 200
        payload = result.json()
        if payload["status"] in {"succeeded", "failed"}:
            return cast(dict[str, object], payload)
        time.sleep(0.02)
    raise AssertionError("Connector sync did not complete.")


def _raw_events(app: FastAPI) -> list[tuple[str, str, str]]:
    database = app.state.runtime["database"]
    assert database.engine is not None
    with database.engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id, event_type, sensitivity FROM raw_events "
                    "WHERE event_type = 'connector_note_document' ORDER BY id"
                )
            ).tuples()
        )


def test_local_notes_sync_is_idempotent_persistent_and_provenance_deletable(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "plan.md").write_text("Synthetic owner note", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)

    with _owner(app) as owner:
        catalog = owner.get("/v1/connectors/catalog")
        assert catalog.status_code == 200
        manifest = next(
            item for item in catalog.json() if item["connector_id"] == "soulmate.local-notes"
        )
        assert manifest["configured"] is False
        assert manifest["permissions"] == ["data:read", "learning:ingest"]
        assert manifest["network_hosts"] == []
        assert manifest["credentials"] == []

        denied = owner.post(
            "/v1/connectors",
            json={
                "connector_id": "soulmate.local-notes",
                "permissions": ["data:read"],
                "configuration": {"path": str(notes)},
            },
        )
        assert denied.status_code == 409

        registered = owner.post(
            "/v1/connectors",
            json={
                "connector_id": "soulmate.local-notes",
                "permissions": ["data:read", "learning:ingest"],
                "configuration": {"path": str(notes)},
            },
        )
        assert registered.status_code == 201
        assert registered.json()["sync_status"] == "never"

        first_job = owner.post("/v1/connectors/soulmate.local-notes/sync")
        assert first_job.status_code == 202
        assert _wait_for_job(owner, first_job.json()["job_id"])["status"] == "succeeded"
        first_events = _raw_events(app)
        assert len(first_events) == 1
        assert first_events[0][1:] == ("connector_note_document", "sensitive")

        second_job = owner.post("/v1/connectors/soulmate.local-notes/sync")
        assert _wait_for_job(owner, second_job.json()["job_id"])["status"] == "succeeded"
        assert _raw_events(app) == first_events

        repositories = app.state.runtime["repositories"]
        event_id = first_events[0][0]
        now = datetime.now(UTC)
        repositories.evidence.add(
            Evidence(
                id="evidence_connector_test",
                profile_id=DEFAULT_PROFILE_ID,
                target_type=EvidenceTargetType.PREFERENCE,
                target_key="work.focus",
                value=0.7,
                strength=0.8,
                confidence=0.8,
                context={},
                source_type="connector_extraction",
                source_event_id=event_id,
                extractor_version="synthetic-test-v1",
                created_at=now,
            )
        )
        repositories.key_aliases.upsert(
            alias("work.focus", "work.deep_focus", profile_id=DEFAULT_PROFILE_ID)
        )
        ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
            DEFAULT_PROFILE_ID, now
        )

    restarted = create_app(settings)
    with _owner(restarted) as owner:
        registrations = owner.get("/v1/connectors").json()
        assert len(registrations) == 1
        assert registrations[0]["sync_status"] == "succeeded"
        assert len(_raw_events(restarted)) == 1

        disabled = owner.patch("/v1/connectors/soulmate.local-notes", json={"enabled": False})
        assert disabled.status_code == 200
        assert owner.post("/v1/connectors/soulmate.local-notes/sync").status_code == 409

        removed = owner.delete("/v1/connectors/soulmate.local-notes")
        assert removed.status_code == 200
        assert removed.json()["raw_event_count"] == 1
        assert removed.json()["evidence_count"] == 1
        assert _raw_events(restarted) == []
        assert owner.get("/v1/connectors").json() == []
        assert owner.get("/v1/preferences/work.focus/evidence").json() == []
        runtime_repositories = restarted.state.runtime["repositories"]
        assert runtime_repositories.key_aliases.list_for_profile(DEFAULT_PROFILE_ID) == ()


def test_connector_management_is_owner_only(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app, client=REMOTE_CLIENT) as remote:
        assert remote.get("/v1/connectors/catalog").status_code == 403
        assert remote.get("/v1/connectors").status_code == 403
        assert remote.post("/v1/connectors/soulmate.local-notes/sync").status_code == 403


def test_connector_failure_status_does_not_disclose_private_configuration(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "private-missing-notes"
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with _owner(app) as owner:
        assert (
            owner.post(
                "/v1/connectors",
                json={
                    "connector_id": "soulmate.local-notes",
                    "permissions": ["data:read", "learning:ingest"],
                    "configuration": {"path": str(private_path)},
                },
            ).status_code
            == 201
        )
        queued = owner.post("/v1/connectors/soulmate.local-notes/sync")
        result = _wait_for_job(owner, queued.json()["job_id"])
        assert result["status"] == "failed"
        assert result["error"] == "Connector synchronization failed."
        assert str(private_path) not in str(result)
        registration = owner.get("/v1/connectors").json()[0]
        assert registration["last_error_code"] == "sync_failed"

        audits = app.state.runtime["repositories"].audit_events.list_for_profile(DEFAULT_PROFILE_ID)
        failure = next(item for item in audits if item.action == "connector.sync_failed")
        assert failure.metadata == {
            "connector_id": "soulmate.local-notes",
            "error_code": "sync_failed",
        }


def test_connector_credentials_are_supplied_at_sync_but_never_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment_name = credential_environment_name("example.credential-test", "token")
    monkeypatch.setenv(environment_name, "synthetic-secret-value")
    app = create_app(Settings(data_dir=tmp_path / "data"), connectors=(CredentialConnector(),))
    with _owner(app) as owner:
        catalog = owner.get("/v1/connectors/catalog").json()
        manifest = next(
            item for item in catalog if item["connector_id"] == "example.credential-test"
        )
        assert manifest["credentials"] == [
            {
                "key": "token",
                "label": "Synthetic token",
                "required": True,
                "available": True,
            }
        ]
        rejected = owner.post(
            "/v1/connectors",
            json={
                "connector_id": "example.credential-test",
                "permissions": ["credentials:read", "data:read", "learning:ingest"],
                "configuration": {"token": "must-not-be-stored"},
            },
        )
        assert rejected.status_code == 409
        registered = owner.post(
            "/v1/connectors",
            json={
                "connector_id": "example.credential-test",
                "permissions": ["credentials:read", "data:read", "learning:ingest"],
                "configuration": {},
            },
        )
        assert registered.status_code == 201
        assert registered.json()["configuration"] == {}
        queued = owner.post("/v1/connectors/example.credential-test/sync")
        assert _wait_for_job(owner, queued.json()["job_id"])["status"] == "succeeded"

        database = app.state.runtime["database"]
        assert database.engine is not None
        with database.engine.connect() as connection:
            stored = " ".join(
                str(value)
                for row in connection.execute(
                    text(
                        "SELECT configuration_json, cursor_json, last_error_code "
                        "FROM connector_registrations"
                    )
                )
                for value in row
                if value is not None
            )
        assert "synthetic-secret-value" not in stored
