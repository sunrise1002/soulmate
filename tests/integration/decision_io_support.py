"""Shared fixtures for the Decision I/O integration tests (Phase 13, ADR-014)."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings

LOCAL_CLIENT = ("127.0.0.1", 52000)
INTERACTION_SCOPE = "interaction:record"
DECISION_SCOPE = "decision:record"
RESOLUTION_SCOPE = "decision:resolution:record"
OUTCOME_OBSERVE_SCOPE = "outcome:observe"
OUTCOME_RECORD_SCOPE = "outcome:record"
ALL_SCOPES = [INTERACTION_SCOPE, DECISION_SCOPE, RESOLUTION_SCOPE, OUTCOME_OBSERVE_SCOPE]
OCCURRED_AT = "2026-09-23T10:00:00+00:00"


def settings_for(tmp_path: Path) -> Settings:
    return Settings.model_validate({"data_dir": str(tmp_path / "owner-data")})


def client(tmp_path: Path, api_key: str | None = None) -> TestClient:
    headers = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    return TestClient(create_app(settings_for(tmp_path)), client=LOCAL_CLIENT, headers=headers)


def create_identity(owner: TestClient, scopes: list[str]) -> dict[str, Any]:
    response = owner.post(
        "/v1/service-identities",
        json={"name": "Synthetic adapter", "description": None, "scopes": scopes},
    )
    assert response.status_code == 201
    issued: dict[str, Any] = response.json()
    return issued


def register_source(
    owner: TestClient,
    identity_id: str,
    data_classes: list[str] | None = None,
    author_scope: str = "mixed",
) -> dict[str, Any]:
    response = owner.post(
        "/v1/decision-io/sources",
        json={
            "name": "Synthetic coding agent",
            "provider": "synthetic_agent",
            "service_identity_id": identity_id,
            "data_classes": data_classes or ["metadata", "decision", "correction", "outcome"],
            "author_scope": author_scope,
            "raw_retention_policy": "structured_only",
            "adapter_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    source: dict[str, Any] = response.json()
    return source


def prepared(
    tmp_path: Path,
    scopes: list[str] | None = None,
    data_classes: list[str] | None = None,
    author_scope: str = "mixed",
) -> tuple[str, str]:
    """Create an identity, its API key, and one owner-approved pushed source."""
    with client(tmp_path) as owner:
        issued = create_identity(owner, scopes or ALL_SCOPES)
        source = register_source(
            owner, issued["identity"]["id"], data_classes=data_classes, author_scope=author_scope
        )
    return str(issued["api_key"]), str(source["id"])


def decision_history(owner: TestClient, decision_id: str) -> dict[str, Any]:
    """Return one decision's stored lifecycle from the owner history endpoint."""
    entries = owner.get("/v1/decisions").json()
    matched = [item for item in entries if item["decision"]["id"] == decision_id]
    assert matched, f"decision {decision_id} is not in the owner history"
    history: dict[str, Any] = matched[0]
    return history


def decision_payload(source_id: str, external_event_id: str = "event-decision-1") -> dict[str, Any]:
    return {
        "source_id": source_id,
        "external_event_id": external_event_id,
        "occurred_at": OCCURRED_AT,
        "actor_type": "agent",
        "content": {"repository": "synthetic"},
        "external_decision_id": "decision-1",
        "domain": "code",
        "question": "Which refactor should be applied?",
        "options": [
            {
                "external_option_id": "option-a",
                "label": "Extract function",
                "description": "Split the long function",
                "features": {"code.simplicity": 1.0},
            },
            {
                "external_option_id": "option-b",
                "label": "Leave as is",
                "description": "Keep the long function",
                "features": {"code.simplicity": -1.0},
            },
        ],
    }


def resolution_payload(
    source_id: str,
    actor_type: str = "owner",
    external_event_id: str = "event-resolution-1",
    external_option_id: str = "option-a",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "external_event_id": external_event_id,
        "occurred_at": OCCURRED_AT,
        "actor_type": actor_type,
        "content": {"chosen": external_option_id},
        "external_decision_id": "decision-1",
        "external_option_id": external_option_id,
    }


def outcome_payload(
    source_id: str,
    kind: str = "technical",
    external_event_id: str = "event-outcome-1",
    technical_status: str | None = None,
    disposition: str | None = None,
    external_decision_id: str = "decision-1",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "external_event_id": external_event_id,
        "occurred_at": OCCURRED_AT,
        "actor_type": "agent",
        "content": {"suite": "unit"},
        "external_decision_id": external_decision_id,
        "kind": kind,
        "technical_status": technical_status,
        "disposition": disposition,
    }
