"""Exercise durable, permissioned delegated decisions and owner approval."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings

pytestmark = pytest.mark.integration

LOCAL_CLIENT = ("127.0.0.1", 52000)
DELEGATE_SCOPE = "agent:delegate"
PREDICT_SCOPE = "decision:predict"
ACTION_TYPE = "calendar.invitation.respond"
FEATURE_KEYS = tuple(f"calendar.signal_{index}" for index in range(8))


def _settings(tmp_path: Path) -> Settings:
    return Settings.model_validate({"data_dir": str(tmp_path / "owner-data")})


def _client(tmp_path: Path, api_key: str | None = None) -> TestClient:
    headers = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    return TestClient(create_app(_settings(tmp_path)), client=LOCAL_CLIENT, headers=headers)


def _identity(owner: TestClient, name: str = "Calendar agent") -> dict[str, Any]:
    response = owner.post(
        "/v1/service-identities",
        json={"name": name, "scopes": [DELEGATE_SCOPE, PREDICT_SCOPE]},
    )
    assert response.status_code == 201
    result: dict[str, Any] = response.json()
    return result


def _decision_payload(question: str) -> dict[str, object]:
    return {
        "domain": "calendar",
        "question": question,
        "options": [
            {
                "label": "Accept",
                "description": "Accept the invitation",
                "features": dict.fromkeys(FEATURE_KEYS, 1.0),
            },
            {
                "label": "Decline",
                "description": "Decline the invitation",
                "features": dict.fromkeys(FEATURE_KEYS, -1.0),
            },
        ],
    }


def _seed_high_confidence_prediction(
    tmp_path: Path, owner: TestClient, api_key: str
) -> dict[str, Any]:
    for key in FEATURE_KEYS:
        corrected = owner.post(
            "/v1/preferences/corrections", json={"target_key": key, "value": 1.0}
        )
        assert corrected.status_code == 201

    with _client(tmp_path, api_key) as external:
        prior = external.post(
            "/v1/external/predict-choice",
            json=_decision_payload("Accept the first synthetic invitation?"),
        )
    assert prior.status_code == 201
    prior_body = prior.json()
    resolved = owner.post(
        f"/v1/decisions/{prior_body['decision_id']}/resolve",
        json={"chosen_option_id": prior_body["predicted_option_id"]},
    )
    assert resolved.status_code == 201

    with _client(tmp_path, api_key) as external:
        prediction = external.post(
            "/v1/external/predict-choice",
            json=_decision_payload("Accept the second synthetic invitation?"),
        )
    assert prediction.status_code == 201
    result: dict[str, Any] = prediction.json()
    assert result["confidence"] >= 0.9
    return result


def test_low_impact_high_confidence_delegation_is_durable_and_idempotent(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as owner:
        issued = _identity(owner)
        prediction = _seed_high_confidence_prediction(tmp_path, owner, str(issued["api_key"]))
        policy = owner.post(
            "/v1/delegation-policies",
            json={
                "service_identity_id": issued["identity"]["id"],
                "action_type": ACTION_TYPE,
                "impact": "low",
                "minimum_confidence": 0.9,
                "allow_automatic": True,
            },
        )
        assert policy.status_code == 201
        policy_id = policy.json()["id"]

    payload = {
        "decision_id": prediction["decision_id"],
        "action_type": ACTION_TYPE,
        "action_label": "Respond to a synthetic calendar invitation",
        "external_request_id": "calendar-event-2",
    }
    with _client(tmp_path, str(issued["api_key"])) as external:
        created = external.post("/v1/external/delegation-requests", json=payload)
        duplicate = external.post("/v1/external/delegation-requests", json=payload)
        assert created.status_code == duplicate.status_code == 201
        assert duplicate.json()["id"] == created.json()["id"]
        assert created.json()["status"] == "approved"
        completed = external.post(
            f"/v1/external/delegation-requests/{created.json()['id']}/complete"
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"

    with _client(tmp_path, str(issued["api_key"])) as restarted:
        stored = restarted.get(f"/v1/external/delegation-requests/{created.json()['id']}")
    assert stored.status_code == 200
    assert stored.json()["status"] == "completed"

    with _client(tmp_path) as owner:
        requests = owner.get("/v1/delegation-requests").json()
        audit = owner.get("/v1/audit/events?limit=100").json()
    assert requests[0]["prediction_id"].startswith("prediction_")
    actions = {item["action"] for item in audit}
    assert {
        "delegation_policy_set",
        "delegation_request_created",
        "delegation_request_completed",
    } <= actions
    assert all("action_label" not in (item["metadata"] or {}) for item in audit)

    with _client(tmp_path) as owner:
        removed = owner.delete(f"/v1/delegation-policies/{policy_id}")
        retained = owner.get("/v1/delegation-requests").json()
    assert removed.status_code == 204
    assert retained[0]["policy_id"] is None


def test_high_impact_delegation_requires_owner_and_is_agent_isolated(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as owner:
        issued = _identity(owner)
        other = _identity(owner, "Other agent")
        prediction = _seed_high_confidence_prediction(tmp_path, owner, str(issued["api_key"]))
        policy = owner.post(
            "/v1/delegation-policies",
            json={
                "service_identity_id": issued["identity"]["id"],
                "action_type": ACTION_TYPE,
                "impact": "high",
                "minimum_confidence": 1.0,
                "allow_automatic": False,
            },
        )
        assert policy.status_code == 201

    payload = {
        "decision_id": prediction["decision_id"],
        "action_type": ACTION_TYPE,
        "action_label": "Respond to a high-impact synthetic invitation",
        "external_request_id": "calendar-event-high",
    }
    with _client(tmp_path, str(issued["api_key"])) as external:
        pending = external.post("/v1/external/delegation-requests", json=payload)
        assert pending.status_code == 201
        assert pending.json()["status"] == "pending"
        denied_completion = external.post(
            f"/v1/external/delegation-requests/{pending.json()['id']}/complete"
        )
        assert denied_completion.status_code == 409

    with _client(tmp_path, str(other["api_key"])) as other_external:
        isolated = other_external.get(f"/v1/external/delegation-requests/{pending.json()['id']}")
    assert isolated.status_code == 404

    with _client(tmp_path) as owner:
        approved = owner.post(f"/v1/delegation-requests/{pending.json()['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

    with _client(tmp_path, str(issued["api_key"])) as external:
        completed = external.post(
            f"/v1/external/delegation-requests/{pending.json()['id']}/complete"
        )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_delegation_scope_and_owner_policy_are_both_required(tmp_path: Path) -> None:
    with _client(tmp_path) as owner:
        predict_only = owner.post(
            "/v1/service-identities",
            json={"name": "Predict only", "scopes": [PREDICT_SCOPE]},
        ).json()
        refused_policy = owner.post(
            "/v1/delegation-policies",
            json={
                "service_identity_id": predict_only["identity"]["id"],
                "action_type": ACTION_TYPE,
                "impact": "low",
                "minimum_confidence": 0.9,
                "allow_automatic": True,
            },
        )
    assert refused_policy.status_code == 409

    with _client(tmp_path, str(predict_only["api_key"])) as external:
        denied = external.post(
            "/v1/external/delegation-requests",
            json={
                "decision_id": "decision_unknown",
                "action_type": ACTION_TYPE,
                "action_label": "Synthetic action",
                "external_request_id": "event-unknown",
            },
        )
    assert denied.status_code == 403
    assert DELEGATE_SCOPE in denied.json()["detail"]
