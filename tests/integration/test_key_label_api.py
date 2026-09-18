"""The owner-only key label API over a real migrated database."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.extraction import ALIAS_MAX_COUNT, LABEL_MAX_LENGTH

pytestmark = pytest.mark.integration

OWNER_CLIENT = ("127.0.0.1", 50000)
PROFILE_ID = "profile_default"
KEY = "ui.theme.dark"


def owner_client(app: FastAPI) -> TestClient:
    return TestClient(app, client=OWNER_CLIENT)


def _learn(client: TestClient, key: str = KEY, value: float = 0.8) -> None:
    response = client.post("/v1/preferences/corrections", json={"target_key": key, "value": value})
    assert response.status_code == 201


def _labels(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/v1/key-labels")
    assert response.status_code == 200
    labels: list[dict[str, Any]] = response.json()["labels"]
    return labels


def _revision(app: FastAPI) -> int:
    repositories = app.state.runtime["repositories"]
    revision: int = repositories.evidence.current_revision(PROFILE_ID)
    return revision


def test_an_owner_names_a_key_in_their_own_language(tmp_path: Path) -> None:
    # Given: a learned preference with no label yet
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)
        assert _labels(client) == []

        # When: the owner names it
        response = client.post(
            "/v1/key-labels",
            json={
                "target_type": "preference",
                "key": KEY,
                "label": "giao diện tối",
                "aliases": ["nền tối"],
            },
        )

        # Then: the label is stored as owner-written and listed back
        assert response.status_code == 200
        assert response.json()["label"] == "giao diện tối"
        assert response.json()["aliases"] == ["nền tối"]
        assert response.json()["source"] == "owner"
        assert [item["key"] for item in _labels(client)] == [KEY]


def test_naming_a_key_makes_its_stored_vector_stale(tmp_path: Path) -> None:
    # Given: a learned preference and the revision the embedding job is keyed by
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)
        before = _revision(app)

        # When: the owner changes the wording of the key
        client.post(
            "/v1/key-labels",
            json={"target_type": "preference", "key": KEY, "label": "giao diện tối"},
        )

        # Then: the revision advanced, so the next refresh re-embeds the key text
        assert _revision(app) > before


def test_removing_a_label_also_makes_the_vector_stale(tmp_path: Path) -> None:
    # Given: a stored owner label
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)
        client.post(
            "/v1/key-labels",
            json={"target_type": "preference", "key": KEY, "label": "giao diện tối"},
        )
        before = _revision(app)

        # When: the owner removes it
        response = client.post(
            "/v1/key-labels/remove", json={"target_type": "preference", "key": KEY}
        )

        # Then: the label is gone and the key must be embedded without it
        assert response.status_code == 204
        assert _labels(client) == []
        assert _revision(app) > before


def test_a_label_change_never_records_the_wording_in_the_audit_log(tmp_path: Path) -> None:
    # Given: a label containing personal wording
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)
        client.post(
            "/v1/key-labels",
            json={
                "target_type": "preference",
                "key": KEY,
                "label": "giao diện tối",
                "aliases": ["nền tối"],
            },
        )

        # When: the owner reads the audit log
        events = client.get("/v1/audit/events").json()

        # Then: only the shape of the change was recorded
        recorded = [item for item in events if item["action"] == "model.key_label_set"]
        assert len(recorded) == 1
        assert recorded[0]["metadata"] == {"target_type": "preference", "alias_count": 1}
        assert "giao diện tối" not in repr(events)


def test_naming_a_key_the_model_does_not_hold_is_refused(tmp_path: Path) -> None:
    # Given: an empty model
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        # When: the owner names an unknown key
        response = client.post(
            "/v1/key-labels",
            json={"target_type": "preference", "key": "ui.theme.unused", "label": "không dùng"},
        )

        # Then: the request fails instead of creating an orphan row
        assert response.status_code == 404
        assert response.json()["detail"] == "The key has no evidence."


def test_an_empty_label_is_refused(tmp_path: Path) -> None:
    # Given: a learned preference
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)

        # When: the owner submits neither a name nor an alias
        response = client.post(
            "/v1/key-labels", json={"target_type": "preference", "key": KEY, "aliases": []}
        )

        # Then: the reason is explicit
        assert response.status_code == 409
        assert response.json()["detail"] == "A key label needs a name or at least one alias."


def test_an_over_long_label_is_rejected_by_the_schema(tmp_path: Path) -> None:
    # Given: a label one character above the wire limit
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)

        # When: the owner saves it
        response = client.post(
            "/v1/key-labels",
            json={
                "target_type": "preference",
                "key": KEY,
                "label": "t" * (LABEL_MAX_LENGTH + 1),
            },
        )

        # Then: validation refuses it before it reaches storage
        assert response.status_code == 422


def test_more_aliases_than_the_limit_are_rejected_by_the_schema(tmp_path: Path) -> None:
    # Given: one alias more than the shared cap
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)

        # When: they are submitted
        response = client.post(
            "/v1/key-labels",
            json={
                "target_type": "preference",
                "key": KEY,
                "label": "giao diện tối",
                "aliases": [f"alias {index}" for index in range(ALIAS_MAX_COUNT + 1)],
            },
        )

        # Then: the request is refused rather than silently truncated on the wire
        assert response.status_code == 422


def test_an_unknown_target_type_is_rejected(tmp_path: Path) -> None:
    # Given: a learned preference
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)

        # When: an invalid target type is submitted
        response = client.post(
            "/v1/key-labels",
            json={"target_type": "nonsense", "key": KEY, "label": "giao diện tối"},
        )

        # Then: the enumeration is enforced at the boundary
        assert response.status_code == 422


def test_removing_a_label_that_was_never_written_is_refused(tmp_path: Path) -> None:
    # Given: a key with no label
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)

        # When: the owner removes it
        response = client.post(
            "/v1/key-labels/remove", json={"target_type": "preference", "key": KEY}
        )

        # Then: the missing label is reported rather than silently accepted
        assert response.status_code == 404
        assert response.json()["detail"] == "The key has no label."


def test_labels_survive_a_restart(tmp_path: Path) -> None:
    # Given: a label stored by one process
    settings = Settings(data_dir=tmp_path)
    with owner_client(create_app(settings)) as client:
        _learn(client)
        client.post(
            "/v1/key-labels",
            json={"target_type": "preference", "key": KEY, "label": "giao diện tối"},
        )

    # When: the daemon starts again over the same database
    with owner_client(create_app(settings)) as client:
        labels = _labels(client)

    # Then: the owner wording is still there
    assert [(item["key"], item["label"]) for item in labels] == [(KEY, "giao diện tối")]


def test_an_over_long_alias_is_rejected_by_the_schema(tmp_path: Path) -> None:
    # Given: one alias above the shared wording limit
    app = create_app(Settings(data_dir=tmp_path))
    with owner_client(app) as client:
        _learn(client)

        # When: the owner saves it
        response = client.post(
            "/v1/key-labels",
            json={
                "target_type": "preference",
                "key": KEY,
                "label": "giao diện tối",
                "aliases": ["n" * (LABEL_MAX_LENGTH + 1)],
            },
        )

        # Then: it is refused at the boundary rather than truncated in storage
        assert response.status_code == 422
