"""Automatic normalized aliases, alias-aware prediction, and the owner alias API."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_core.domain import EvidenceTargetType
from soulmate_daemon.app import create_app
from soulmate_daemon.config import KeyAliasesConfig, Settings
from soulmate_daemon.conversation import ConversationService
from soulmate_llm_providers import FakeLLMProvider

from .key_alias_support import add_evidence

pytestmark = pytest.mark.integration

OWNER_CLIENT = ("127.0.0.1", 50000)
PROFILE_ID = "profile_default"


def owner_client(app: FastAPI) -> TestClient:
    return TestClient(app, client=OWNER_CLIENT)


def _correct(client: TestClient, key: str, value: float) -> dict[str, Any]:
    response = client.post("/v1/preferences/corrections", json={"target_key": key, "value": value})
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def _preferences(client: TestClient) -> dict[str, float]:
    return {item["key"]: item["value"] for item in client.get("/v1/preferences").json()}


def _aliases(client: TestClient) -> dict[str, Any]:
    response = client.get("/v1/key-aliases")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _target(key: str, target_type: str = "preference") -> dict[str, str]:
    return {"target_type": target_type, "alias_key": key}


def _decision(client: TestClient, office: dict[str, float], remote: dict[str, float]) -> str:
    response = client.post(
        "/v1/decisions",
        json={
            "domain": "career",
            "question": "Which role would I choose?",
            "options": [
                {"label": "Office", "description": "Office role", "features": office},
                {"label": "Remote", "description": "Remote role", "features": remote},
            ],
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def test_variant_key_is_merged_automatically_after_a_correction(tmp_path: Path) -> None:
    # Given: a learned preference under the normalized key
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _correct(client, "ui.theme.dark", 0.8)

        # When: the same preference arrives under a variant key
        body = _correct(client, "UI.Theme.Dark_Mode", 0.4)

        # Then: both evidence items reinforce one canonical preference
        preferences = client.get("/v1/preferences").json()
        assert [item["key"] for item in preferences] == ["ui.theme.dark"]
        assert len(preferences[0]["supporting_evidence_ids"]) == 2
        assert body["evidence"]["target_key"] == "UI.Theme.Dark_Mode"
        listed = _aliases(client)
        assert listed["enabled"] is True
        assert [
            (item["alias_key"], item["canonical_key"], item["method"], item["status"])
            for item in listed["aliases"]
        ] == [("UI.Theme.Dark_Mode", "ui.theme.dark", "normalized", "active")]
        assert (
            client.get("/v1/model/summary").json()["algorithm_version"].endswith(":key-aliases-v1")
        )


def test_chat_learning_merges_a_variant_key_after_review(tmp_path: Path) -> None:
    # Given: an extraction that proposes a variant of a known key
    provider = FakeLLMProvider(
        responses=["Noted."],
        structured_responses=[
            {
                "facts": [],
                "preferences": [
                    {
                        "target_key": "ui.theme.dark_mode",
                        "value": 0.9,
                        "strength": 0.9,
                        "confidence": 0.9,
                        "context": [],
                    }
                ],
                "goals": [],
                "constraints": [],
            }
        ],
    )
    app = create_app(Settings(data_dir=tmp_path), provider=provider)
    with owner_client(app) as client:
        _correct(client, "ui.theme.dark", 0.5)
        response = client.post("/v1/chat", json={"content": "Tôi thích giao diện tối."})
        assert response.status_code == 200
        repositories = app.state.runtime["repositories"]
        job = repositories.jobs.get(f"job_extract_{response.json()['user_message_id']}")
        assert job is not None

        # When: the deferred learning job runs
        asyncio.run(
            ConversationService(
                conversations=repositories.conversations,
                messages=repositories.messages,
                raw_events=repositories.raw_events,
                evidence=repositories.evidence,
                models=repositories.personal_models,
                provider=provider,
                jobs=repositories.jobs,
                aliases=repositories.key_aliases,
            ).retry_learning(job.payload)
        )

        # Then: the reviewed variant reinforces the known preference
        assert list(_preferences(client)) == ["ui.theme.dark"]
        assert [item["alias_key"] for item in _aliases(client)["aliases"]] == ["ui.theme.dark_mode"]


def test_prediction_uses_a_preference_learned_under_a_variant_key(tmp_path: Path) -> None:
    # Given: chat learned work.remote while the decision uses a variant key
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _correct(client, "work.remote", 0.9)
        decision_id = _decision(client, {"work.remote_mode": -1.0}, {"work.remote_mode": 1.0})

        # When: the decision is predicted
        response = client.post(f"/v1/decisions/{decision_id}/predict")

        # Then: the learned preference decides instead of a 50/50 guess
        assert response.status_code == 201
        prediction = response.json()
        assert prediction["predicted_choice"] == "Remote"
        assert prediction["ranking"][0]["probability"] > 0.6
        assert prediction["important_factors"] == ["work.remote"]
        assert prediction["algorithm_version"].endswith(":canonical-features-v1:key-normalizer-v1")


def test_resolution_learning_registers_aliases_for_variant_feature_keys(tmp_path: Path) -> None:
    # Given: a decision whose features use a variant of a learned key
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _correct(client, "work.remote", 0.2)
        decision_id = _decision(client, {"work.remote_mode": -1.0}, {"work.remote_mode": 1.0})
        options = client.get("/v1/decisions").json()[0]["decision"]["options"]
        remote = next(item for item in options if item["label"] == "Remote")

        # When: the owner resolves it
        response = client.post(
            f"/v1/decisions/{decision_id}/resolve", json={"chosen_option_id": remote["id"]}
        )

        # Then: the learned evidence joins the existing preference
        assert response.status_code == 201
        assert response.json()["learned_evidence"][0]["target_key"] == "work.remote_mode"
        assert list(_preferences(client)) == ["work.remote"]


def test_owner_review_rejects_restores_and_inverts_an_alias(tmp_path: Path) -> None:
    # Given: an automatic alias between two variants
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _correct(client, "ui.theme.dark", 0.8)
        _correct(client, "ui.theme.dark_mode", 0.8)
        assert list(_preferences(client)) == ["ui.theme.dark"]

        # When: the owner rejects the merge
        rejected = client.post(
            "/v1/key-aliases/review", json={**_target("ui.theme.dark_mode"), "action": "reject"}
        )

        # Then: the keys are separate again and stay separate after new evidence
        assert rejected.status_code == 200
        assert rejected.json()["alias"]["status"] == "rejected"
        assert sorted(_preferences(client)) == ["ui.theme.dark", "ui.theme.dark_mode"]
        _correct(client, "ui.theme.dark_mode", 0.8)
        assert _aliases(client)["aliases"][0]["status"] == "rejected"

        # When: the owner approves it again
        approved = client.post(
            "/v1/key-aliases/review", json={**_target("ui.theme.dark_mode"), "action": "approve"}
        )

        # Then: the keys are merged again
        assert approved.status_code == 200
        assert approved.json()["snapshot_version"] > rejected.json()["snapshot_version"]
        assert list(_preferences(client)) == ["ui.theme.dark"]

        # When: the owner inverts it
        inverted = client.post(
            "/v1/key-aliases/review", json={**_target("ui.theme.dark_mode"), "action": "invert"}
        )

        # Then: the variant now counts against the canonical preference
        assert inverted.status_code == 200
        assert inverted.json()["alias"]["polarity"] == -1
        assert _preferences(client)["ui.theme.dark"] < 0.8


def test_owner_can_merge_remove_and_audit_aliases(tmp_path: Path) -> None:
    # Given: two opposite keys that normalization does not connect
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _correct(client, "ui.theme.dark", 0.8)
        _correct(client, "ui.theme.light", -0.6)

        # When: the owner merges light into dark as an inverted axis
        created = client.post(
            "/v1/key-aliases",
            json={**_target(" ui.theme.light "), "canonical_key": "ui.theme.dark", "polarity": -1},
        )

        # Then: one signed preference remains
        assert created.status_code == 201
        assert created.json()["alias"]["method"] == "owner"
        assert created.json()["alias"]["alias_key"] == "ui.theme.light"
        assert list(_preferences(client)) == ["ui.theme.dark"]
        assert _preferences(client)["ui.theme.dark"] > 0.6

        # When: the owner removes the alias
        removed = client.post("/v1/key-aliases/remove", json=_target("ui.theme.light"))

        # Then: the original grouping returns and a second removal is missing
        assert removed.status_code == 200
        assert removed.json()["alias_key"] == "ui.theme.light"
        assert sorted(_preferences(client)) == ["ui.theme.dark", "ui.theme.light"]
        missing = client.post("/v1/key-aliases/remove", json=_target("ui.theme.light"))
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Key alias was not found."

        events = client.get("/v1/audit/events").json()
        alias_events = [item for item in events if item["action"].startswith("model.key_alias")]
        assert {item["action"] for item in alias_events} == {
            "model.key_alias_create",
            "model.key_alias_remove",
        }
        assert "ui.theme" not in str(alias_events)


@pytest.mark.parametrize(
    ("payload", "status", "detail"),
    [
        (
            {**_target("work.unknown"), "canonical_key": "work.remote"},
            404,
            "The key has no evidence.",
        ),
        (
            {**_target("work.office"), "canonical_key": "work.office"},
            409,
            "A target key alias must not point at itself.",
        ),
        (
            {**_target("work.office"), "canonical_key": "work.remote"},
            409,
            "Target key aliases form a cycle",
        ),
        (
            {**_target("work.office", "fact"), "canonical_key": "work.remote", "polarity": -1},
            404,
            "The key has no evidence.",
        ),
    ],
)
def test_invalid_owner_merges_are_rejected(
    tmp_path: Path, payload: dict[str, object], status: int, detail: str
) -> None:
    # Given: an owner alias work.remote -> work.office
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _correct(client, "work.office", 0.5)
        _correct(client, "work.remote", 0.5)
        setup = client.post(
            "/v1/key-aliases", json={**_target("work.remote"), "canonical_key": "work.office"}
        )
        assert setup.status_code == 201

        # When: an invalid merge is requested
        response = client.post("/v1/key-aliases", json=payload)

        # Then: it is rejected with a specific reason and nothing changes
        assert response.status_code == status
        assert response.json()["detail"].startswith(detail)
        assert len(_aliases(client)["aliases"]) == 1


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/v1/key-aliases", {**_target("a.b"), "canonical_key": "c.d", "polarity": 0}, "polarity"),
        ("/v1/key-aliases", {**_target("a.b"), "canonical_key": "   "}, "canonical_key"),
        ("/v1/key-aliases", {**_target("a.b")}, "canonical_key"),
        ("/v1/key-aliases/review", {**_target("a.b"), "action": "merge"}, "action"),
        ("/v1/key-aliases/review", {**_target(""), "action": "approve"}, "alias_key"),
        ("/v1/key-aliases/remove", {**_target("a" * 201)}, "alias_key"),
        ("/v1/key-aliases/remove", {**_target("a.b", "opinion")}, "target_type"),
        ("/v1/key-aliases/remove", {"target_type": "preference", "alias_key": None}, "alias_key"),
    ],
)
def test_malformed_alias_requests_fail_validation(
    tmp_path: Path, path: str, payload: dict[str, object], field: str
) -> None:
    # Given: a running daemon
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        # When: a malformed request is sent
        response = client.post(path, json=payload)

        # Then: validation names the offending field
        assert response.status_code == 422
        assert any(field in error["loc"] for error in response.json()["detail"])


def test_review_errors_report_missing_and_conflicting_aliases(tmp_path: Path) -> None:
    # Given: a fact alias created automatically
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        missing = client.post(
            "/v1/key-aliases/review", json={**_target("work.remote"), "action": "approve"}
        )
        repositories = app.state.runtime["repositories"]
        add_evidence(
            repositories,
            "evidence_city_1",
            "home.city",
            "hanoi",
            profile_id=PROFILE_ID,
            target_type=EvidenceTargetType.FACT,
        )
        add_evidence(
            repositories,
            "evidence_city_2",
            "Home.City",
            "hanoi",
            profile_id=PROFILE_ID,
            target_type=EvidenceTargetType.FACT,
        )
        _correct(client, "work.remote", 0.5)

        # When: a missing alias is reviewed and a fact alias is inverted
        inverted = client.post(
            "/v1/key-aliases/review", json={**_target("Home.City", "fact"), "action": "invert"}
        )

        # Then: the daemon reports not found and conflict
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Key alias was not found."
        assert inverted.status_code == 409
        assert inverted.json()["detail"] == "Only preference aliases can invert polarity."
        fact_alias = _aliases(client)["aliases"][0]
        assert (fact_alias["target_type"], fact_alias["polarity"]) == ("fact", 1)


def test_disabled_aliases_restore_original_keys_and_block_changes(tmp_path: Path) -> None:
    # Given: a merged variant stored while aliases were enabled
    enabled = Settings(data_dir=tmp_path)
    with owner_client(create_app(enabled)) as client:
        _correct(client, "ui.theme.dark", 0.8)
        _correct(client, "ui.theme.dark_mode", 0.8)
        assert list(_preferences(client)) == ["ui.theme.dark"]

    # When: the daemon restarts with aliases disabled
    disabled = Settings(data_dir=tmp_path, key_aliases=KeyAliasesConfig(enabled=False))
    with owner_client(create_app(disabled)) as client:
        # Then: the startup rebuild shows original keys and alias writes are refused
        assert sorted(_preferences(client)) == ["ui.theme.dark", "ui.theme.dark_mode"]
        listed = _aliases(client)
        assert listed["enabled"] is False
        assert len(listed["aliases"]) == 1
        for path, payload in (
            ("/v1/key-aliases", {**_target("ui.theme.dark_mode"), "canonical_key": "x.y"}),
            ("/v1/key-aliases/review", {**_target("ui.theme.dark_mode"), "action": "reject"}),
            ("/v1/key-aliases/remove", _target("ui.theme.dark_mode")),
        ):
            response = client.post(path, json=payload)
            assert response.status_code == 409
            assert response.json()["detail"] == "Key aliases are disabled in the configuration."
        _correct(client, "UI.Theme.Dark", 0.8)
        assert len(_aliases(client)["aliases"]) == 1
        assert client.get("/v1/model/summary").json()["algorithm_version"] == (
            "personal-model-v1:evidence-weights-v1"
        )

    # When: aliases are enabled again
    with owner_client(create_app(enabled)) as client:
        # Then: the stored alias applies again without new evidence
        assert sorted(_preferences(client)) == ["UI.Theme.Dark", "ui.theme.dark"]


def test_other_devices_cannot_reach_the_alias_api(tmp_path: Path) -> None:
    # Given: a daemon without LAN access
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app, client=("192.168.1.20", 50000)) as client:
        # When: a non-loopback caller lists aliases
        response = client.get("/v1/key-aliases")

        # Then: access is denied before the handler runs
        assert response.status_code == 403
