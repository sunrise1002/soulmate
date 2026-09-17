"""Owner-only embedding model API: status, refusals, manual import, and removal."""

from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import PrivacyConfig, Settings
from soulmate_daemon.model_artifacts import MODEL_ARTIFACTS, ModelArtifact, ModelFile

pytestmark = pytest.mark.integration

OWNER_CLIENT = ("127.0.0.1", 50000)
WEIGHTS = b"synthetic-weights-payload"
TOKENIZER = b"synthetic-tokenizer-payload"


def _artifact() -> ModelArtifact:
    return ModelArtifact(
        model_id="bge-m3-int8",
        display_name="Synthetic model",
        license="MIT",
        source="https://models.example.test",
        dimensions=4,
        max_tokens=128,
        pooling="cls",
        peak_memory_bytes=1_000,
        weights_file="weights.onnx",
        tokenizer_file="tokenizer.json",
        files=(
            ModelFile(
                name="weights.onnx",
                url="https://models.example.test/weights.onnx",
                sha256=sha256(WEIGHTS).hexdigest(),
                approximate_bytes=len(WEIGHTS),
            ),
            ModelFile(
                name="tokenizer.json",
                url="https://models.example.test/tokenizer.json",
                sha256=sha256(TOKENIZER).hexdigest(),
                approximate_bytes=len(TOKENIZER),
            ),
        ),
    )


def owner_client(app: FastAPI) -> TestClient:
    return TestClient(app, client=OWNER_CLIENT)


def _status(client: TestClient) -> dict[str, Any]:
    response = client.get("/v1/embedding-model")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _audit_actions(client: TestClient) -> list[str]:
    return [item["action"] for item in client.get("/v1/audit/events").json()]


def test_status_describes_the_pinned_model_before_any_download(tmp_path: Path) -> None:
    # Given: a fresh installation with the default privacy mode
    app = create_app(Settings(data_dir=tmp_path))

    # When: the owner opens the model screen
    with owner_client(app) as client:
        body = _status(client)

    # Then: the dialog can show what the download costs, and nothing is installed
    assert body["provider"] == "none"
    assert body["model_id"] == "bge-m3-int8"
    assert body["license"] == "MIT"
    assert body["download_bytes"] > 0
    assert body["peak_memory_bytes"] > 0
    assert body["installed"] is False
    assert body["downloading"] is False
    assert body["downloaded_bytes"] == 0
    assert body["can_download"] is True
    assert body["privacy_mode"] == "strict_local"
    assert [item["name"] for item in body["files"]] == ["model_int8.onnx", "tokenizer.json"]


def test_offline_mode_refuses_the_download_and_says_so_in_the_status(tmp_path: Path) -> None:
    # Given: an installation in offline mode
    app = create_app(Settings(data_dir=tmp_path, privacy=PrivacyConfig(mode="offline")))

    with owner_client(app) as client:
        # When: the owner presses download
        response = client.post("/v1/embedding-model/download")

        # Then: the request is refused and the screen shows the download as unavailable
        assert response.status_code == 409
        assert "privacy mode" in response.json()["detail"]
        body = _status(client)
        assert body["can_download"] is False
        assert body["installed"] is False
        assert "model.embedding_download_denied" in _audit_actions(client)


def test_cancelling_without_a_running_download_is_refused(tmp_path: Path) -> None:
    # Given: an installation that never started a download
    app = create_app(Settings(data_dir=tmp_path))

    with owner_client(app) as client:
        # When: the owner cancels
        response = client.post("/v1/embedding-model/cancel")

        # Then: the request is refused
        assert response.status_code == 409
        assert "No model download" in response.json()["detail"]


def test_manual_import_installs_the_model_and_removal_undoes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: pinned files the owner copied onto the device without network access
    monkeypatch.setitem(MODEL_ARTIFACTS, "bge-m3-int8", _artifact())
    weights = tmp_path / "weights.onnx"
    weights.write_bytes(WEIGHTS)
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_bytes(TOKENIZER)
    app = create_app(Settings(data_dir=tmp_path))

    with owner_client(app) as client:
        # When: both files are imported and the model is removed again
        for name, source in (("weights.onnx", weights), ("tokenizer.json", tokenizer)):
            response = client.post(
                "/v1/embedding-model/import",
                json={"file_name": name, "source_path": str(source)},
            )
            assert response.status_code == 200
        installed = response.json()
        removed = client.post("/v1/embedding-model/remove")

        # Then: the model became usable offline and both actions are audited
        assert installed["installed"] is True
        assert removed.status_code == 200
        assert removed.json()["installed"] is False
        actions = _audit_actions(client)
        assert actions.count("model.embedding_model_imported") == 2
        assert "model.embedding_model_removed" in actions


def test_importing_a_file_that_fails_verification_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a file that does not match the pinned hash
    monkeypatch.setitem(MODEL_ARTIFACTS, "bge-m3-int8", _artifact())
    source = tmp_path / "weights.onnx"
    source.write_bytes(b"not the pinned weights")
    app = create_app(Settings(data_dir=tmp_path))

    with owner_client(app) as client:
        # When: the owner imports it
        response = client.post(
            "/v1/embedding-model/import",
            json={"file_name": "weights.onnx", "source_path": str(source)},
        )

        # Then: the import is refused and nothing was installed
        assert response.status_code == 409
        assert "SHA-256" in response.json()["detail"]
        assert _status(client)["installed"] is False


def test_importing_an_unknown_file_or_a_missing_path_is_refused(tmp_path: Path) -> None:
    # Given: an installation with no model files
    app = create_app(Settings(data_dir=tmp_path))

    with owner_client(app) as client:
        # When: an unknown name, a missing path, and a blank name are submitted
        unknown = client.post(
            "/v1/embedding-model/import",
            json={"file_name": "unexpected.bin", "source_path": str(tmp_path / "any.bin")},
        )
        missing = client.post(
            "/v1/embedding-model/import",
            json={"file_name": "tokenizer.json", "source_path": str(tmp_path / "absent.json")},
        )
        blank = client.post(
            "/v1/embedding-model/import",
            json={"file_name": "  ", "source_path": str(tmp_path / "any.bin")},
        )

        # Then: each is refused without touching the store
        assert unknown.status_code == 409
        assert missing.status_code == 409
        assert blank.status_code == 422


def test_removing_without_stored_files_is_refused(tmp_path: Path) -> None:
    # Given: an installation that never downloaded a model
    app = create_app(Settings(data_dir=tmp_path))

    with owner_client(app) as client:
        # When: the owner removes it
        response = client.post("/v1/embedding-model/remove")

        # Then: the request is refused
        assert response.status_code == 409
        assert "No model files" in response.json()["detail"]
