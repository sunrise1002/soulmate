"""Exercise local APIs, persistence, restart, and installed CLI behavior."""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.conversation import ConversationService
from soulmate_llm_providers import FakeLLMProvider, ProviderError
from soulmate_storage_sqlite import Database, Repositories

pytestmark = pytest.mark.integration


OWNER_CLIENT = ("127.0.0.1", 50000)


def owner_client(app: FastAPI) -> TestClient:
    """Call the service the way the owner's own machine does, over loopback."""
    return TestClient(app, client=OWNER_CLIENT)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _running_daemon(tmp_path: Path, port: int) -> Iterator[None]:
    executable = shutil.which("soulmate")
    assert executable is not None, "Install the workspace before running tests."
    env = dict(os.environ, SOULMATE_SERVER__PORT=str(port), DATA_DIR=str(tmp_path / "data"))
    opener = build_opener(ProxyHandler({}))
    output_path = tmp_path / f"daemon-output-{time.monotonic_ns()}.txt"
    with output_path.open("w+", encoding="utf-8") as output:
        process = subprocess.Popen(
            [executable, "serve"], cwd=tmp_path, env=env, stdout=output, stderr=output
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output.seek(0)
                    pytest.fail(f"Daemon exited during startup: {output.read()}")
                try:
                    with opener.open(f"http://127.0.0.1:{port}/v1/health", timeout=0.3) as response:
                        if json.load(response)["status"] == "healthy":
                            break
                except (URLError, TimeoutError):
                    time.sleep(0.05)
            else:
                pytest.fail("Daemon did not become healthy within 10 seconds.")
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_app_migrates_storage_and_exposes_minimal_local_api(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    app = create_app(settings)
    with owner_client(app) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "healthy",
            "database": "available",
            "migration": "current",
        }
        info = client.get("/v1/system/info")
        assert info.status_code == 200
        assert info.json()["installation_id"].startswith("installation_")
        assert info.json()["profile_id"] == "profile_default"
        assert info.json()["privacy_mode"] == "strict_local"
        assert client.get("/docs").status_code == 404
    assert settings.database_path.is_file()


def test_installation_identity_survives_application_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    with owner_client(create_app(settings)) as client:
        first_id = client.get("/v1/system/info").json()["installation_id"]
    with owner_client(create_app(settings)) as client:
        second_id = client.get("/v1/system/info").json()["installation_id"]
    assert first_id == second_id


def test_preference_correction_rebuilds_model_and_exposes_evidence(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    with owner_client(create_app(settings)) as client:
        empty = client.get("/v1/model/summary")
        assert empty.status_code == 200
        assert empty.json()["version"] is None

        correction = client.post(
            "/v1/preferences/corrections",
            json={
                "target_key": "work.remote",
                "value": 0.75,
                "context": {"domain": "career"},
            },
        )
        assert correction.status_code == 201
        result = correction.json()
        evidence_id = result["evidence"]["id"]
        assert result["snapshot_version"] == 1

        preferences = client.get("/v1/preferences")
        assert preferences.status_code == 200
        assert preferences.json()[0]["key"] == "work.remote"
        assert preferences.json()[0]["value"] == pytest.approx(0.75)

        support = client.get("/v1/preferences/work.remote/evidence")
        assert support.status_code == 200
        assert [item["id"] for item in support.json()] == [evidence_id]
        detail = client.get(f"/v1/evidence/{evidence_id}")
        assert detail.status_code == 200
        assert detail.json()["source_type"] == "user_correction"

        summary = client.get("/v1/model/summary").json()
        assert summary["version"] == 1
        assert summary["evidence_revision"] == 1
        assert summary["preference_count"] == 1


def test_preference_correction_validates_external_input(tmp_path: Path) -> None:
    with owner_client(create_app(Settings(data_dir=tmp_path / "owner-data"))) as client:
        response = client.post(
            "/v1/preferences/corrections",
            json={"target_key": "work.remote", "value": 2.0},
        )
        assert response.status_code == 422


def test_desktop_model_flow_lists_and_deletes_evidence(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    with owner_client(create_app(settings)) as client:
        correction = client.post(
            "/v1/preferences/corrections",
            json={"target_key": "work.remote", "value": 0.75},
        )
        evidence_id = correction.json()["evidence"]["id"]

        deleted = client.delete(f"/v1/evidence/{evidence_id}")

        assert deleted.status_code == 200
        assert deleted.json() == {
            "removed_evidence_id": evidence_id,
            "snapshot_version": 2,
        }
        assert client.get("/v1/preferences").json() == []
        assert client.get(f"/v1/evidence/{evidence_id}").status_code == 404
        assert client.delete(f"/v1/evidence/{evidence_id}").status_code == 404


def test_desktop_history_endpoints_return_local_owner_records(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    provider = FakeLLMProvider(
        responses=["Synthetic response"],
        structured_responses=[{"facts": [], "preferences": [], "goals": [], "constraints": []}],
    )
    with owner_client(create_app(settings, provider=provider)) as client:
        chat = client.post("/v1/chat", json={"content": "Synthetic message"})
        decision = client.post("/v1/decisions", json=_decision_payload())
        decision_id = decision.json()["id"]
        prediction = client.post(f"/v1/decisions/{decision_id}/predict")
        chosen_option_id = decision.json()["options"][0]["id"]
        resolution = client.post(
            f"/v1/decisions/{decision_id}/resolve",
            json={"chosen_option_id": chosen_option_id},
        )

        conversations = client.get("/v1/conversations")
        decisions = client.get("/v1/decisions")

        assert chat.status_code == 200
        assert decision.status_code == prediction.status_code == 201
        assert resolution.status_code == 201
        assert conversations.status_code == 200
        assert [message["role"] for message in conversations.json()[0]["messages"]] == [
            "user",
            "assistant",
        ]
        assert decisions.status_code == 200
        history = decisions.json()[0]
        assert history["decision"]["id"] == decision_id
        assert history["prediction"]["decision_id"] == decision_id
        assert history["resolution"]["chosen_option_id"] == chosen_option_id


def test_installed_cli_status_doctor_and_restart(tmp_path: Path) -> None:
    executable = shutil.which("soulmate")
    assert executable is not None
    port = _free_port()
    env = dict(os.environ, SOULMATE_SERVER__PORT=str(port), DATA_DIR=str(tmp_path / "data"))

    unavailable = subprocess.run(
        [executable, "status"], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    assert unavailable.returncode == 1
    assert json.loads(unavailable.stdout)["reachable"] is False

    with _running_daemon(tmp_path, port):
        status = subprocess.run(
            [executable, "status"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert status.returncode == 0
        first_id = json.loads(status.stdout)["system"]["installation_id"]
        doctor = subprocess.run(
            [executable, "doctor"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert doctor.returncode == 0
        doctor_result = json.loads(doctor.stdout)
        assert doctor_result["healthy"] is True
        assert doctor_result["checks"]["journal_mode"] == "wal"
        assert doctor_result["checks"]["port_available"] is False

    with _running_daemon(tmp_path, port):
        status = subprocess.run(
            [executable, "status"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert json.loads(status.stdout)["system"]["installation_id"] == first_id


def test_doctor_does_not_create_a_missing_database(tmp_path: Path) -> None:
    executable = shutil.which("soulmate")
    assert executable is not None
    data_dir = tmp_path / "not-created"
    result = subprocess.run(
        [executable, "doctor"],
        cwd=tmp_path,
        env=dict(os.environ, DATA_DIR=str(data_dir)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["checks"]["database_exists"] is False
    assert not data_dir.exists()


def test_rebuild_model_cli_creates_versioned_snapshots(tmp_path: Path) -> None:
    executable = shutil.which("soulmate")
    assert executable is not None
    env = dict(os.environ, DATA_DIR=str(tmp_path / "data"))

    first = subprocess.run(
        [executable, "rebuild-model"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    second = subprocess.run(
        [executable, "rebuild-model"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout)["snapshot_version"] == 1
    assert json.loads(second.stdout)["snapshot_version"] == 2
    assert json.loads(second.stdout)["evidence_revision"] == 0


def test_portability_cli_imports_backs_up_exports_and_restores(tmp_path: Path) -> None:
    executable = shutil.which("soulmate")
    assert executable is not None
    source_dir = tmp_path / "machine-a"
    target_dir = tmp_path / "machine-b"
    transcript = tmp_path / "synthetic.md"
    transcript.write_text("User: I prefer local tools.\nAssistant: Noted.", encoding="utf-8")
    archive = tmp_path / "backup.dtwb"
    encrypted = tmp_path / "portable.dtw"
    passphrase_file = tmp_path / "phrase.txt"
    passphrase_file.write_text("synthetic export phrase\n", encoding="utf-8")
    source_env = dict(os.environ, DATA_DIR=str(source_dir))

    imported = subprocess.run(
        [executable, "import", str(transcript)],
        cwd=tmp_path,
        env=source_env,
        capture_output=True,
        text=True,
        check=False,
    )
    backup = subprocess.run(
        [executable, "backup", "--output", str(archive)],
        cwd=tmp_path,
        env=source_env,
        capture_output=True,
        text=True,
        check=False,
    )
    exported = subprocess.run(
        [
            executable,
            "export",
            "--output",
            str(encrypted),
            "--passphrase-file",
            str(passphrase_file),
        ],
        cwd=tmp_path,
        env=source_env,
        capture_output=True,
        text=True,
        check=False,
    )
    restored = subprocess.run(
        [executable, "restore", str(archive)],
        cwd=tmp_path,
        env=dict(os.environ, DATA_DIR=str(target_dir)),
        capture_output=True,
        text=True,
        check=False,
    )

    assert imported.returncode == backup.returncode == exported.returncode == 0
    assert restored.returncode == 0
    assert json.loads(imported.stdout)["message_count"] == 2
    assert json.loads(backup.stdout)["encrypted"] is False
    assert json.loads(exported.stdout)["encrypted"] is True
    assert json.loads(restored.stdout)["schema_revision_after"] == "0011_key_consistency"
    target_database = Database(target_dir / "soulmate.db")
    target_database.migrate()
    target_repositories = Repositories(target_database.sessions())
    sources = target_repositories.sources.list_for_profile("profile_default")
    assert sources[0].name == transcript.name
    target_database.close()


def test_cli_reports_bad_config_without_traceback(tmp_path: Path) -> None:
    executable = shutil.which("soulmate")
    assert executable is not None
    result = subprocess.run(
        [executable, "serve", "--config", str(tmp_path / "missing.toml")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "Configuration file not found" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("command", ["remote-backup", "remote-restore-latest"])
def test_remote_backup_cli_is_explicitly_disabled_by_default(tmp_path: Path, command: str) -> None:
    executable = shutil.which("soulmate")
    assert executable is not None

    result = subprocess.run(
        [executable, command],
        cwd=tmp_path,
        env=dict(os.environ, DATA_DIR=str(tmp_path / "data")),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout) in (
        {"uploaded": False, "error": "Remote backup is not configured."},
        {"restored": False, "error": "Remote backup is not configured."},
    )
    assert "Traceback" not in result.stderr


def test_chat_extracts_preferences_and_persists_context_across_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    first_provider = FakeLLMProvider(
        responses=["That sounds like a useful work preference."],
        structured_responses=[
            {
                "facts": [],
                "preferences": [
                    {
                        "target_key": "work.remote",
                        "value": 0.9,
                        "strength": 0.8,
                        "confidence": 0.95,
                        "context": {"domain": "career"},
                    }
                ],
                "goals": [],
                "constraints": [],
            }
        ],
    )
    first_app = create_app(settings, provider=first_provider)
    with owner_client(first_app) as client:
        response = client.post("/v1/chat", json={"content": "I strongly prefer remote work."})
        assert response.status_code == 200
        body = response.json()
        conversation_id = body["conversation_id"]
        assert body["accepted_evidence"] == []
        assert body["snapshot_version"] is None
        assert body["learning_status"] == "pending"
        assert body["learning_error"] is None
        repositories = first_app.state.runtime["repositories"]
        job = repositories.jobs.get(f"job_extract_{body['user_message_id']}")
        assert job is not None
        asyncio.run(
            ConversationService(
                conversations=repositories.conversations,
                messages=repositories.messages,
                raw_events=repositories.raw_events,
                evidence=repositories.evidence,
                models=repositories.personal_models,
                provider=first_provider,
                jobs=repositories.jobs,
            ).retry_learning(job.payload)
        )
        evidence = repositories.evidence.list_for_profile("profile_default")[0]
        assert evidence.target_key == "work.remote"
        assert evidence.extractor_model == "fake-model-v1"
        assert evidence.source_message_id == body["user_message_id"]
        assert client.get("/v1/preferences").json()[0]["value"] == pytest.approx(0.9)

    second_provider = FakeLLMProvider(
        responses=["Your remote-work preference is relevant."],
        structured_responses=[{"facts": [], "preferences": [], "goals": [], "constraints": []}],
    )
    second_app = create_app(settings, provider=second_provider)
    with owner_client(second_app) as client:
        response = client.post(
            "/v1/chat",
            json={"conversation_id": conversation_id, "content": "What about remote work?"},
        )
        assert response.status_code == 200
        assert response.json()["snapshot_version"] is None
        assert response.json()["learning_status"] == "pending"
        repositories = second_app.state.runtime["repositories"]
        job = repositories.jobs.get(f"job_extract_{response.json()['user_message_id']}")
        assert job is not None
        asyncio.run(
            ConversationService(
                conversations=repositories.conversations,
                messages=repositories.messages,
                raw_events=repositories.raw_events,
                evidence=repositories.evidence,
                models=repositories.personal_models,
                provider=second_provider,
                jobs=repositories.jobs,
            ).retry_learning(job.payload)
        )
        assert client.get("/v1/model/summary").json()["version"] == 1

    chat_prompt = second_provider.requests[0]
    assert "work.remote" in chat_prompt[0].content
    assert [(item.role, item.content) for item in chat_prompt[1:]] == [
        ("user", "I strongly prefer remote work."),
        ("assistant", "That sounds like a useful work preference."),
        ("user", "What about remote work?"),
    ]


def _learn_from_chat(app: FastAPI, provider: FakeLLMProvider, message_id: str) -> None:
    repositories = app.state.runtime["repositories"]
    job = repositories.jobs.get(f"job_extract_{message_id}")
    assert job is not None
    asyncio.run(
        ConversationService(
            conversations=repositories.conversations,
            messages=repositories.messages,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            provider=provider,
            jobs=repositories.jobs,
        ).retry_learning(job.payload)
    )


def _extraction_known_keys(provider: FakeLLMProvider) -> dict[str, list[str]]:
    system_prompt = provider.requests[-1][0].content
    assert "reuse that exact key" in system_prompt
    assert "one signed axis" in system_prompt
    return dict(json.loads(system_prompt.split("Known keys by type: ", 1)[1]))


def test_chat_extraction_receives_known_keys_to_reuse(tmp_path: Path) -> None:
    # Given: an existing preference and a provider that reuses its key
    provider = FakeLLMProvider(
        responses=["Noted."],
        structured_responses=[
            {
                "facts": [],
                "preferences": [
                    {
                        "target_key": "ui.theme.dark",
                        "value": 0.7,
                        "strength": 0.8,
                        "confidence": 0.9,
                        "context": [],
                    }
                ],
                "goals": [],
                "constraints": [],
            }
        ],
    )
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        correction = client.post(
            "/v1/preferences/corrections", json={"target_key": "ui.theme.dark", "value": 0.8}
        )
        assert correction.status_code == 201

        # When: a related chat message is learned
        chat = client.post("/v1/chat", json={"content": "I still like dark mode."})
        assert chat.status_code == 200
        _learn_from_chat(app, provider, chat.json()["user_message_id"])

        # Then: the extractor saw the key and both statements reinforce one preference
        assert _extraction_known_keys(provider) == {
            "namespaces": ["ui.theme"],
            "facts": [],
            "preferences": ["ui.theme.dark"],
            "goals": [],
            "constraints": [],
        }
        preferences = client.get("/v1/preferences").json()
        assert [item["key"] for item in preferences] == ["ui.theme.dark"]


def test_chat_extraction_receives_empty_known_keys_without_a_model(tmp_path: Path) -> None:
    # Given: an empty Personal Model and a provider that proposes nothing
    provider = FakeLLMProvider(
        responses=["Hello."],
        structured_responses=[{"facts": [], "preferences": [], "goals": [], "constraints": []}],
    )
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        # When: a chat message is learned
        chat = client.post("/v1/chat", json={"content": "Hello"})
        _learn_from_chat(app, provider, chat.json()["user_message_id"])

    # Then: every known-key type is present and empty
    assert _extraction_known_keys(provider) == {
        "namespaces": [],
        "facts": [],
        "preferences": [],
        "goals": [],
        "constraints": [],
    }


def test_chat_learning_failure_keeps_evidence_unchanged_with_known_keys(tmp_path: Path) -> None:
    # Given: an existing preference and a provider without a structured response
    provider = FakeLLMProvider(responses=["Noted."])
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        client.post(
            "/v1/preferences/corrections", json={"target_key": "ui.theme.dark", "value": 0.8}
        )
        chat = client.post("/v1/chat", json={"content": "I still like dark mode."})
        assert chat.status_code == 200

        # When: learning runs and the provider fails
        # Then: the provider error surfaces and no evidence is added
        with pytest.raises(ProviderError, match="no structured response configured"):
            _learn_from_chat(app, provider, chat.json()["user_message_id"])
        repositories = app.state.runtime["repositories"]
        assert len(repositories.evidence.list_for_profile("profile_default")) == 1


def test_chat_preserves_reply_when_learning_output_is_invalid(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        responses=["Synthetic response"],
        structured_responses=[
            {
                "preferences": [
                    {
                        "target_key": "work.remote",
                        "value": 4,
                        "strength": 1,
                        "confidence": 1,
                        "context": {},
                    }
                ]
            },
            {
                "facts": [],
                "preferences": [
                    {
                        "target_key": "work.remote",
                        "value": 0.8,
                        "strength": 0.9,
                        "confidence": 0.9,
                        "context": {},
                    }
                ],
                "goals": [],
                "constraints": [],
            },
        ],
    )
    settings = Settings(data_dir=tmp_path / "owner-data")
    app = create_app(settings, provider=provider)
    with owner_client(app) as client:
        response = client.post("/v1/chat", json={"content": "Synthetic message"})
        assert response.status_code == 200
        body = response.json()
        assert body["message"]["content"] == "Synthetic response"
        assert body["learning_status"] == "pending"
        assert body["learning_error"] is None
        assert len(provider.requests) == 1
        conversations = client.get("/v1/conversations").json()
        assert [item["content"] for item in conversations[0]["messages"]] == [
            "Synthetic message",
            "Synthetic response",
        ]
        assert client.get("/v1/model/summary").json()["evidence_revision"] == 0
        repositories = app.state.runtime["repositories"]
        job = repositories.jobs.get(f"job_extract_{body['user_message_id']}")
        assert job is not None
        assert set(job.payload) == {"profile_id", "source_event_id", "source_message_id"}
        assert "Synthetic message" not in json.dumps(job.payload)

        service = ConversationService(
            conversations=repositories.conversations,
            messages=repositories.messages,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            provider=provider,
            jobs=repositories.jobs,
        )
        with pytest.raises(ValueError):
            asyncio.run(service.retry_learning(job.payload))
        assert [item["content"] for item in conversations[0]["messages"]] == [
            "Synthetic message",
            "Synthetic response",
        ]
        asyncio.run(service.retry_learning(job.payload))
        assert client.get("/v1/preferences").json()[0]["key"] == "work.remote"


def _decision_payload() -> dict[str, object]:
    return {
        "domain": "career",
        "question": "Which work arrangement would I choose?",
        "options": [
            {
                "label": "Office role",
                "description": "Work from an office every day",
                "features": {"work.remote": -1.0},
                "feature_confidence": 1.0,
            },
            {
                "label": "Remote role",
                "description": "Work remotely every day",
                "features": {"work.remote": 1.0},
                "feature_confidence": 1.0,
            },
        ],
    }


def test_decision_prediction_resolution_learning_and_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    with owner_client(create_app(settings)) as client:
        correction = client.post(
            "/v1/preferences/corrections",
            json={"target_key": "work.remote", "value": 0.75, "context": {"domain": "career"}},
        )
        assert correction.status_code == 201
        created = client.post("/v1/decisions", json=_decision_payload())
        assert created.status_code == 201
        decision = created.json()
        assert decision["status"] == "open"
        office_id, remote_id = (item["id"] for item in decision["options"])

        prediction = client.post(f"/v1/decisions/{decision['id']}/predict")
        assert prediction.status_code == 201
        predicted = prediction.json()
        assert predicted["mode"] == "predict_me"
        assert predicted["predicted_option_id"] == remote_id
        assert predicted["model_snapshot_version"] == 1
        assert predicted["algorithm_version"].startswith("decision-predictor-v2:")
        assert predicted["important_factors"] == ["work.remote"]
        assert predicted["supporting_evidence"][0]["source_type"] == "user_correction"
        assert sum(item["probability"] for item in predicted["ranking"]) == pytest.approx(1.0)

        resolution = client.post(
            f"/v1/decisions/{decision['id']}/resolve",
            json={"chosen_option_id": office_id},
        )
        assert resolution.status_code == 201
        resolved = resolution.json()
        assert resolved["chosen_option_id"] == office_id
        assert resolved["learned_evidence"][0]["source_type"] == "actual_choice"
        assert resolved["learned_evidence"][0]["value"] == -1.0
        assert resolved["snapshot_version"] == 2
        assert (
            client.post(
                f"/v1/decisions/{decision['id']}/resolve", json={"chosen_option_id": office_id}
            ).status_code
            == 409
        )

    database = Database(settings.database_path)
    database.migrate()
    repositories = Repositories(database.sessions())
    assert repositories.decisions.latest_prediction(decision["id"]) is not None
    assert repositories.decisions.get_resolution(decision["id"]) is not None
    database.close()

    with owner_client(create_app(settings)) as client:
        next_decision = client.post("/v1/decisions", json=_decision_payload()).json()
        next_prediction = client.post(f"/v1/decisions/{next_decision['id']}/predict").json()
        assert next_prediction["predicted_choice"] == "Office role"
        assert next_prediction["model_snapshot_version"] == 2
        assert "bradley-terry-online-v1" in next_prediction["algorithm_version"]
        assert next_prediction["similar_decision_ids"] == [decision["id"]]


def test_active_question_answer_rebuilds_model_and_survives_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    with owner_client(create_app(settings)) as client:
        for key, value in (("work.speed", 0.2), ("work.quality", 0.3)):
            assert (
                client.post(
                    "/v1/preferences/corrections",
                    json={"target_key": key, "value": value},
                ).status_code
                == 201
            )

        generated = client.post("/v1/active-questions/generate", json={"limit": 1})
        assert generated.status_code == 201
        question = generated.json()[0]
        assert set(question["preference_keys"]) == {"work.speed", "work.quality"}
        assert question["model_snapshot_version"] == 2

        answered = client.post(
            f"/v1/active-questions/{question['id']}/answer", json={"choice": "b"}
        )
        assert answered.status_code == 201
        assert answered.json()["choice"] == "b"
        assert len(answered.json()["learned_evidence"]) == 2
        assert (
            client.post(
                f"/v1/active-questions/{question['id']}/answer", json={"choice": "other"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/v1/active-questions/{question['id']}/answer", json={"choice": "a"}
            ).status_code
            == 409
        )

    with owner_client(create_app(settings)) as client:
        stored = client.get("/v1/active-questions")
        assert stored.status_code == 200
        assert stored.json()[0]["status"] == "answered"
        assert client.get("/v1/model/summary").json()["evidence_revision"] == 4


def test_outcomes_inform_advise_me_without_changing_predict_me(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    payload = {
        "domain": "career",
        "question": "Stay with the familiar path or try a new one?",
        "options": [
            {
                "label": "Familiar path",
                "description": "Keep the known path",
                "features": {"novelty": -1.0},
                "feature_confidence": 1.0,
            },
            {
                "label": "New path",
                "description": "Try a new path",
                "features": {"novelty": 1.0},
                "feature_confidence": 1.0,
            },
        ],
    }
    with owner_client(create_app(settings)) as client:
        client.post("/v1/preferences/corrections", json={"target_key": "novelty", "value": -1.0})
        historical = client.post("/v1/decisions", json=payload).json()
        historical_prediction = client.post(f"/v1/decisions/{historical['id']}/predict").json()
        assert historical_prediction["predicted_choice"] == "Familiar path"
        familiar_id = next(
            item["id"] for item in historical["options"] if item["label"] == "Familiar path"
        )
        client.post(
            f"/v1/decisions/{historical['id']}/resolve",
            json={"chosen_option_id": familiar_id},
        )
        outcome = client.post(
            f"/v1/decisions/{historical['id']}/outcome",
            json={"satisfaction": 0.0, "regret": True, "notes": "Synthetic outcome"},
        )
        assert outcome.status_code == 201
        assert (
            client.post(
                f"/v1/decisions/{historical['id']}/outcome",
                json={"satisfaction": 1.0, "regret": False},
            ).status_code
            == 409
        )

        current = client.post("/v1/decisions", json=payload).json()
        assert (
            client.post(
                f"/v1/decisions/{current['id']}/outcome",
                json={"satisfaction": 0.5, "regret": False},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/v1/decisions/{current['id']}/outcome",
                json={"satisfaction": 1.1, "regret": False},
            ).status_code
            == 422
        )
        prediction = client.post(f"/v1/decisions/{current['id']}/predict").json()
        client.post("/v1/preferences/corrections", json={"target_key": "novelty", "value": -0.9})
        advice = client.post(f"/v1/decisions/{current['id']}/advise")

        assert prediction["predicted_choice"] == "Familiar path"
        assert advice.status_code == 201
        assert advice.json()["mode"] == "advise_me"
        assert advice.json()["predicted_choice"] == "Familiar path"
        assert advice.json()["recommended_choice"] == "New path"
        assert advice.json()["supporting_outcome_ids"] == [outcome.json()["id"]]
        assert advice.json()["model_snapshot_version"] > prediction["model_snapshot_version"]

    database = Database(settings.database_path)
    database.migrate()
    stored_outcome = Repositories(database.sessions()).outcomes.get_for_decision(historical["id"])
    assert stored_outcome is not None
    source_event_id = stored_outcome.source_event_id
    database.close()

    with owner_client(create_app(settings)) as client:
        history = client.get("/v1/decisions").json()
        historical_item = next(
            item for item in history if item["decision"]["id"] == historical["id"]
        )
        current_item = next(item for item in history if item["decision"]["id"] == current["id"])
        assert historical_item["outcome"]["regret"] is True
        assert current_item["advice"]["recommended_choice"] == "New path"

        deleted = client.delete(f"/v1/decisions/{historical['id']}/outcome")
        assert deleted.json() == {"removed_outcome_id": outcome.json()["id"]}
        refreshed = client.get("/v1/decisions").json()
        assert all(item["outcome"] is None for item in refreshed)
        assert all(item["advice"] is None for item in refreshed)
        assert client.delete(f"/v1/decisions/{historical['id']}/outcome").status_code == 404

    database = Database(settings.database_path)
    database.migrate()
    assert Repositories(database.sessions()).raw_events.get(source_event_id) is None
    database.close()


def test_decision_extracts_natural_option_features_with_validated_provider_output(
    tmp_path: Path,
) -> None:
    provider = FakeLLMProvider(
        structured_responses=[
            {
                "options": [
                    {"option_index": 0, "features": {"cost.low": 1.0}, "confidence": 0.8},
                    {"option_index": 1, "features": {"cost.low": -1.0}, "confidence": 0.9},
                ]
            }
        ]
    )
    payload = {
        "domain": "purchase",
        "question": "Which plan would I choose?",
        "options": [
            {"label": "Basic", "description": "Low monthly price"},
            {"label": "Premium", "description": "Higher monthly price"},
        ],
    }
    with owner_client(
        create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    ) as client:
        response = client.post("/v1/decisions", json=payload)
        assert response.status_code == 201
        assert response.json()["options"][0]["features"] == {"cost.low": 1.0}
        assert response.json()["options"][1]["feature_confidence"] == 0.9
    assert len(provider.requests) == 1


def _theme_payload() -> dict[str, object]:
    return {
        "domain": "general",
        "question": "Which theme do I prefer?",
        "options": [
            {"label": "Dark", "description": "Dark theme"},
            {"label": "Light", "description": "Light theme"},
        ],
    }


def test_decision_extraction_reuses_known_preference_keys_for_prediction(
    tmp_path: Path,
) -> None:
    # Given: chat-style preferences for the dark and light theme keys
    provider = FakeLLMProvider(
        structured_responses=[
            {
                "options": [
                    {
                        "option_index": 0,
                        "features": {"ui.theme.dark": 1.0, "ui.theme.light": -1.0},
                        "confidence": 0.95,
                    },
                    {
                        "option_index": 1,
                        "features": {"ui.theme.dark": -1.0, "ui.theme.light": 1.0},
                        "confidence": 0.95,
                    },
                ]
            }
        ]
    )
    with owner_client(
        create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    ) as client:
        for key, value in (("ui.theme.dark", 0.8), ("ui.theme.light", -0.6)):
            correction = client.post(
                "/v1/preferences/corrections", json={"target_key": key, "value": value}
            )
            assert correction.status_code == 201

        # When: a natural-language decision is created and predicted
        decision = client.post("/v1/decisions", json=_theme_payload())
        assert decision.status_code == 201
        prediction = client.post(f"/v1/decisions/{decision.json()['id']}/predict")

    # Then: the provider sees the existing keys and the prediction uses them
    request = json.loads(provider.requests[0][1].content)
    assert request["known_keys"] == {
        "namespaces": ["ui.theme"],
        "preferences": ["ui.theme.dark", "ui.theme.light"],
    }
    assert prediction.status_code == 201
    body = prediction.json()
    assert body["predicted_choice"] == "Dark"
    assert body["ranking"][0]["probability"] > 0.5
    assert body["important_factors"] == ["ui.theme.dark", "ui.theme.light"]


def test_decision_extraction_sends_empty_known_keys_without_preferences(
    tmp_path: Path,
) -> None:
    # Given: an empty Personal Model
    provider = FakeLLMProvider(
        structured_responses=[
            {
                "options": [
                    {"option_index": 0, "features": {"ui.theme.dark": 1.0}, "confidence": 0.9},
                    {"option_index": 1, "features": {"ui.theme.dark": -1.0}, "confidence": 0.9},
                ]
            }
        ]
    )
    with owner_client(
        create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    ) as client:
        # When: a natural-language decision is created and predicted
        decision = client.post("/v1/decisions", json=_theme_payload())
        prediction = client.post(f"/v1/decisions/{decision.json()['id']}/predict")

    # Then: no keys are offered and the prediction stays at chance
    assert decision.status_code == 201
    request = json.loads(provider.requests[0][1].content)
    assert request["known_keys"] == {"namespaces": [], "preferences": []}
    assert prediction.json()["ranking"][0]["probability"] == pytest.approx(0.5)
    assert prediction.json()["uncertain_factors"] == ["ui.theme.dark"]


def test_decision_extraction_reports_provider_failure_without_persisting(
    tmp_path: Path,
) -> None:
    # Given: a provider with no structured response, which raises ProviderError
    provider = FakeLLMProvider()
    with owner_client(
        create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    ) as client:
        # When: a natural-language decision is created
        response = client.post("/v1/decisions", json=_theme_payload())

        # Then: the failure is reported and no decision is stored
        assert response.status_code == 502
        assert response.json()["detail"] == "The model provider request failed."
        assert client.get("/v1/decisions").json() == []


def test_decision_prediction_without_prior_model_creates_snapshot_and_validates_input(
    tmp_path: Path,
) -> None:
    with owner_client(create_app(Settings(data_dir=tmp_path / "owner-data"))) as client:
        invalid = _decision_payload()
        invalid["domain"] = " "
        assert client.post("/v1/decisions", json=invalid).status_code == 422

        decision = client.post("/v1/decisions", json=_decision_payload()).json()
        prediction = client.post(f"/v1/decisions/{decision['id']}/predict")
        assert prediction.status_code == 201
        assert prediction.json()["model_snapshot_version"] == 1
        assert prediction.json()["uncertain_factors"] == ["work.remote"]


def test_decision_rejects_invalid_natural_feature_extraction(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        structured_responses=[
            {
                "options": [
                    {"option_index": 0, "features": {"cost.low": 2.0}, "confidence": 0.8},
                    {"option_index": 1, "features": {"cost.low": -1.0}, "confidence": 0.9},
                ]
            }
        ]
    )
    payload = {
        "domain": "purchase",
        "question": "Which plan would I choose?",
        "options": [
            {"label": "Basic", "description": "Low monthly price"},
            {"label": "Premium", "description": "Higher monthly price"},
        ],
    }
    with owner_client(
        create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    ) as client:
        response = client.post("/v1/decisions", json=payload)
        assert response.status_code == 502
        assert response.json()["detail"] == "The model provider returned invalid structured output."
