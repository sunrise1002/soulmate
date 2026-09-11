"""Exercise Phase 1 API, persistence, restart, and installed CLI behavior."""

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
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _running_daemon(tmp_path: Path, port: int) -> Iterator[None]:
    executable = shutil.which("decision-twin")
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
    with TestClient(app) as client:
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
    with TestClient(create_app(settings)) as client:
        first_id = client.get("/v1/system/info").json()["installation_id"]
    with TestClient(create_app(settings)) as client:
        second_id = client.get("/v1/system/info").json()["installation_id"]
    assert first_id == second_id


def test_preference_correction_rebuilds_model_and_exposes_evidence(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    with TestClient(create_app(settings)) as client:
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
    with TestClient(create_app(Settings(data_dir=tmp_path / "owner-data"))) as client:
        response = client.post(
            "/v1/preferences/corrections",
            json={"target_key": "work.remote", "value": 2.0},
        )
        assert response.status_code == 422


def test_installed_cli_status_doctor_and_restart(tmp_path: Path) -> None:
    executable = shutil.which("decision-twin")
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
    executable = shutil.which("decision-twin")
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
    executable = shutil.which("decision-twin")
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


def test_cli_reports_bad_config_without_traceback(tmp_path: Path) -> None:
    executable = shutil.which("decision-twin")
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
