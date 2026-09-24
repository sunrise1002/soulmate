"""Decision I/O sources: retention, removal, isolation, and portability."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.portability import ArchiveService, restore_archive
from soulmate_storage_sqlite import Database

from .decision_io_support import (
    ALL_SCOPES,
    LOCAL_CLIENT,
    OCCURRED_AT,
    client,
    create_identity,
    decision_payload,
    prepared,
    resolution_payload,
    settings_for,
)

pytestmark = pytest.mark.integration


def test_removing_a_source_removes_its_provenance_graph_and_rebuilds(tmp_path: Path) -> None:
    # Given: a promoted owner choice that produced Evidence
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        agent.post("/v1/external/decision-io/resolutions", json=resolution_payload(source_id))
    with client(tmp_path) as owner:
        before = owner.get("/v1/preferences").json()
        # When: the owner removes the source
        removed = owner.delete(f"/v1/decision-io/sources/{source_id}")
        after = owner.get("/v1/preferences").json()
        decisions = owner.get("/v1/decisions").json()
        observations = owner.get("/v1/decision-io/observations").json()
        remaining = owner.get("/v1/decision-io/sources").json()
    # Then: events, decisions, observations, and Evidence are gone
    assert before
    assert removed.status_code == 200, removed.text
    assert removed.json()["model_rebuilt"] is True
    assert removed.json()["decision_count"] == 1
    assert (after, decisions, observations, remaining) == ([], [], [], [])


def test_external_sources_are_not_reachable_from_another_device(tmp_path: Path) -> None:
    # Given: the owner-only Decision I/O surface
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings), client=("192.168.1.50", 52001)) as remote:
        # When: another device tries to list or register sources
        listed = remote.get("/v1/decision-io/sources")
        registered = remote.post("/v1/decision-io/sources", json={})
    # Then: both are refused by the shared authorization boundary
    assert listed.status_code == 403
    assert registered.status_code == 403


def test_unsupported_retention_is_rejected_rather_than_ignored(tmp_path: Path) -> None:
    # Given: an active service identity
    with client(tmp_path) as owner:
        issued = create_identity(owner, ALL_SCOPES)
        # When: the owner asks for a retention mode the repository cannot honour
        response = owner.post(
            "/v1/decision-io/sources",
            json={
                "name": "Synthetic coding agent",
                "provider": "synthetic_agent",
                "service_identity_id": issued["identity"]["id"],
                "data_classes": ["metadata"],
                "raw_retention_policy": "delete_after_extraction",
            },
        )
    # Then: the source is refused
    assert response.status_code == 422
    assert "delete_after_extraction" in response.text


def test_a_metadata_only_source_stores_no_event_content(tmp_path: Path) -> None:
    # Given: a source whose owner allowed metadata retention only
    with client(tmp_path) as owner:
        issued = create_identity(owner, ALL_SCOPES)
        source = owner.post(
            "/v1/decision-io/sources",
            json={
                "name": "Metadata-only agent",
                "provider": "synthetic_agent",
                "service_identity_id": issued["identity"]["id"],
                "data_classes": ["metadata"],
                "raw_retention_policy": "metadata_only",
            },
        ).json()
    # When: an interaction with distinctive content is recorded twice
    payload = {
        "source_id": source["id"],
        "external_event_id": "event-metadata-1",
        "occurred_at": OCCURRED_AT,
        "actor_type": "agent",
        "content": {"command": "synthetic-command-should-not-persist"},
    }
    with client(tmp_path, str(issued["api_key"])) as agent:
        first = agent.post("/v1/external/decision-io/interactions", json=payload)
        retry = agent.post("/v1/external/decision-io/interactions", json=payload)
    # Then: the event exists, stays idempotent, and keeps no content
    assert first.status_code == 201, first.text
    assert retry.json()["duplicate"] is True
    with sqlite3.connect(settings_for(tmp_path).database_path) as connection:
        stored = connection.execute(
            "SELECT content_json FROM raw_events WHERE source_id = ?", (source["id"],)
        ).fetchall()
    assert stored == [("{}",)]


def test_an_encrypted_export_restores_provenance_without_usable_credentials(
    tmp_path: Path,
) -> None:
    # Given: a source, an ingested decision, and a pending observation
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        agent.post(
            "/v1/external/decision-io/resolutions",
            json=resolution_payload(source_id, actor_type="agent"),
        )
    settings = settings_for(tmp_path)
    database = Database(settings.database_path)
    database.connect()
    archive = tmp_path / "export.dtw"
    ArchiveService(settings, database).create(
        archive,
        passphrase="correct horse battery",  # noqa: S106 -- synthetic fixture secret.
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    database.close()
    # When: the export is restored into a fresh installation
    target = Settings(data_dir=tmp_path / "restored")
    restored = restore_archive(target, archive, "correct horse battery")
    # Then: provenance and observations restore, but the old API key is unusable
    assert restored.schema_revision_after == "0012_phase_13"
    with TestClient(create_app(target), client=LOCAL_CLIENT) as owner:
        sources = owner.get("/v1/decision-io/sources").json()
        observations = owner.get("/v1/decision-io/observations").json()
    assert sources[0]["provider"] == "synthetic_agent"
    assert sources[0]["decision_count"] == 1
    assert observations[0]["status"] == "pending"
    with TestClient(
        create_app(target),
        client=LOCAL_CLIENT,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as agent:
        refused = agent.post(
            "/v1/external/decision-io/decisions",
            json=decision_payload(source_id, "event-after-restore"),
        )
    assert refused.status_code == 401
