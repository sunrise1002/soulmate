"""Exercise the empty application and installed daemon process."""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings

pytestmark = pytest.mark.integration


def test_empty_app_lifecycle_does_not_create_storage(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "owner-data")
    app = create_app(settings)
    with TestClient(app) as client:
        assert app.state.settings is settings
        assert client.get("/v1/health").status_code == 404
        assert client.get("/docs").status_code == 404
    assert not settings.data_dir.exists()


def test_installed_cli_starts_empty_daemon(tmp_path: Path) -> None:
    executable = shutil.which("decision-twin")
    assert executable is not None, "Install the workspace before running tests."
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, SOULMATE_SERVER__PORT=str(port), DATA_DIR=str(tmp_path / "data"))
    opener = build_opener(ProxyHandler({}))
    with (tmp_path / "daemon-output.txt").open("w+", encoding="utf-8") as output:
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
                    request = Request(f"http://127.0.0.1:{port}/")
                    with opener.open(request, timeout=0.3):
                        pytest.fail("The Phase 0 daemon must not expose product routes.")
                except HTTPError as response:
                    assert response.code == 404
                    response.close()
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.05)
            else:
                pytest.fail("Daemon did not start within 10 seconds.")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    assert not (tmp_path / "data").exists()


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
