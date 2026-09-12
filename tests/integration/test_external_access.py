"""Exercise scoped external REST access, persistence, and local audit records."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings

pytestmark = pytest.mark.integration

LOCAL_CLIENT = ("127.0.0.1", 52000)
PREDICT_SCOPE = "decision:predict"
RECORD_SCOPE = "decision:record"
OUTCOME_SCOPE = "outcome:record"
PREFERENCE_SCOPE = "preference:summary:read"


def _settings(tmp_path: Path) -> Settings:
    return Settings.model_validate({"data_dir": str(tmp_path / "owner-data")})


def _client(tmp_path: Path, api_key: str | None = None) -> TestClient:
    headers = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    return TestClient(create_app(_settings(tmp_path)), client=LOCAL_CLIENT, headers=headers)


def _decision_payload() -> dict[str, object]:
    return {
        "domain": "shopping",
        "question": "Which laptop would the owner prefer?",
        "options": [
            {
                "label": "Quiet laptop",
                "description": "Quiet and efficient",
                "features": {"computer.quiet": 1.0, "computer.performance": 0.3},
            },
            {
                "label": "Fast laptop",
                "description": "Fast but loud",
                "features": {"computer.quiet": -1.0, "computer.performance": 1.0},
            },
        ],
    }


def _create_identity(
    owner: TestClient, scopes: list[str], name: str = "Synthetic agent"
) -> dict[str, Any]:
    response = owner.post(
        "/v1/service-identities",
        json={"name": name, "description": "Offline test identity", "scopes": scopes},
    )
    assert response.status_code == 201
    result: dict[str, Any] = response.json()
    return result


def test_scoped_prediction_returns_no_raw_personal_records_and_is_audited(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as owner:
        owner.post(
            "/v1/preferences/corrections",
            json={"target_key": "computer.quiet", "value": 0.9},
        )
        issued = _create_identity(owner, [PREDICT_SCOPE])
    api_key = str(issued["api_key"])

    with _client(tmp_path, api_key) as external:
        prediction = external.post("/v1/external/predict-choice", json=_decision_payload())

    assert prediction.status_code == 201
    body = prediction.json()
    assert body["predicted_choice"] == "Quiet laptop"
    assert body["model_snapshot_version"] >= 1
    serialized = prediction.text
    assert "supporting_evidence" not in serialized
    assert "source_event" not in serialized
    assert "notes" not in serialized

    with _client(tmp_path) as owner:
        events = owner.get("/v1/audit/events?limit=10").json()
    request_event = next(item for item in events if item["action"] == "external_request")
    assert request_event["actor_id"] == issued["identity"]["id"]
    assert request_event["metadata"] == {
        "credential_id": issued["identity"]["credentials"][0]["id"],
        "method": "POST",
        "path": "/v1/external/predict-choice",
        "status": 201,
    }


def test_external_routes_require_the_exact_scope_even_on_loopback(tmp_path: Path) -> None:
    with _client(tmp_path) as owner:
        issued = _create_identity(owner, [PREFERENCE_SCOPE, "model:summary:read"])

    with _client(tmp_path, str(issued["api_key"])) as external:
        allowed = external.get("/v1/external/preference-summary")
        model = external.get("/v1/external/model-summary")
        denied = external.post("/v1/external/rank-options", json=_decision_payload())

    assert allowed.status_code == 200
    assert model.status_code == 200
    assert denied.status_code == 403
    assert PREDICT_SCOPE in denied.json()["detail"]

    with _client(tmp_path) as owner:
        updated = owner.post(
            f"/v1/service-identities/{issued['identity']['id']}/scopes",
            json={"scopes": [PREDICT_SCOPE]},
        )
        events = owner.get("/v1/audit/events?limit=10").json()
    assert updated.status_code == 200
    with _client(tmp_path, str(issued["api_key"])) as external:
        assert (
            external.post("/v1/external/rank-options", json=_decision_payload()).status_code == 201
        )
    denied_event = next(
        item
        for item in events
        if item["action"] == "external_request" and item["metadata"]["status"] == 403
    )
    assert denied_event["actor_id"] == issued["identity"]["id"]


def test_api_keys_are_hash_only_restart_safe_and_revocable(tmp_path: Path) -> None:
    with _client(tmp_path) as owner:
        issued = _create_identity(owner, [PREFERENCE_SCOPE])
    api_key = str(issued["api_key"])
    identity = issued["identity"]
    credential_id = identity["credentials"][0]["id"]

    assert api_key.encode() not in (tmp_path / "owner-data" / "decision-twin.db").read_bytes()
    with _client(tmp_path, api_key) as restarted_external:
        assert restarted_external.get("/v1/external/preference-summary").status_code == 200

    with _client(tmp_path) as owner:
        revoked = owner.delete(
            f"/v1/service-identities/{identity['id']}/credentials/{credential_id}"
        )
    assert revoked.status_code == 200
    assert revoked.json()["active"] is False

    with _client(tmp_path, api_key) as external:
        assert external.get("/v1/external/preference-summary").status_code == 401


def test_external_agent_records_a_decision_and_outcome_with_separate_scopes(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as owner:
        issued = _create_identity(owner, [RECORD_SCOPE, OUTCOME_SCOPE])
    api_key = str(issued["api_key"])

    with _client(tmp_path, api_key) as external:
        recorded = external.post("/v1/external/record-decision", json=_decision_payload())
    assert recorded.status_code == 201
    decision_id = recorded.json()["id"]
    chosen_option_id = recorded.json()["option_ids"][0]

    with _client(tmp_path) as owner:
        resolved = owner.post(
            f"/v1/decisions/{decision_id}/resolve",
            json={"chosen_option_id": chosen_option_id},
        )
    assert resolved.status_code == 201

    with _client(tmp_path, api_key) as external:
        outcome = external.post(
            "/v1/external/record-outcome",
            json={
                "decision_id": decision_id,
                "satisfaction": 0.8,
                "regret": False,
                "notes": "Synthetic outcome",
            },
        )
    assert outcome.status_code == 201
    assert outcome.json()["decision_id"] == decision_id
    assert "notes" not in outcome.json()


def test_invalid_external_keys_return_no_personal_data_but_leave_an_audit_record(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as owner:
        missing = owner.get("/v1/external/preference-summary")
    with _client(tmp_path, "sk_soulmate.missing.invalid") as unknown:
        invalid = unknown.get("/v1/external/preference-summary")

    assert missing.status_code == 401
    assert invalid.status_code == 401
    with _client(tmp_path) as owner:
        events = owner.get("/v1/audit/events?limit=10").json()
    denied = [item for item in events if item["action"] == "external_request"]
    assert len(denied) == 2
    assert all(item["actor_type"] == "anonymous" for item in denied)
    assert all(item["metadata"]["status"] == 401 for item in denied)
