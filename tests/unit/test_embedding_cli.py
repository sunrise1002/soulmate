"""The offline `embedding-model` command: status only, never a download."""

import json
from pathlib import Path

import pytest
from soulmate_daemon.cli import EMBEDDING_RUNTIME_MODULES, _embedding_model, _embedding_runtime
from soulmate_daemon.config import Settings
from soulmate_daemon.embeddings import artifact_store
from soulmate_daemon.model_artifacts import BGE_M3_INT8


def _report(
    capsys: pytest.CaptureFixture[str], settings: Settings, *, verify: bool = False, code: int = 0
) -> dict[str, object]:
    assert _embedding_model(settings, verify) == code
    return dict(json.loads(capsys.readouterr().out))


def test_a_fresh_installation_reports_the_model_as_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: an installation that never downloaded a model
    settings = Settings(data_dir=tmp_path)

    # When: the owner inspects the local embedding model
    report = _report(capsys, settings)

    # Then: the size and memory need are shown without fetching anything
    assert report["installed"] is False
    assert report["downloaded_bytes"] == 0
    assert report["provider"] == "none"
    assert report["model_id"] == BGE_M3_INT8.model_id
    assert report["download_bytes"] == BGE_M3_INT8.download_bytes
    assert report["peak_memory_bytes"] == BGE_M3_INT8.peak_memory_bytes
    assert not (tmp_path / "models").exists()


def test_an_installed_artifact_is_reported_as_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: both pinned files present on disk
    settings = Settings(data_dir=tmp_path)
    store = artifact_store(settings)
    store.directory.mkdir(parents=True)
    for file in BGE_M3_INT8.files:
        store.path(file).write_bytes(b"synthetic weights")

    # When: the owner inspects the local embedding model
    report = _report(capsys, settings)

    # Then: it counts as installed, and the directory is named for a manual removal
    assert report["installed"] is True
    assert report["downloaded_bytes"] == len(b"synthetic weights") * len(BGE_M3_INT8.files)
    assert report["directory"] == str(store.directory)


def test_the_packaged_runtimes_are_reported_with_their_versions() -> None:
    # Given: a workspace that installed the embeddings extra

    # When: the runtimes are probed
    runtime = _embedding_runtime()

    # Then: every module the ONNX adapter imports is accounted for
    assert set(runtime) == set(EMBEDDING_RUNTIME_MODULES)


def test_a_missing_runtime_is_reported_instead_of_raising(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an installation without the optional native runtimes
    def refuse(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("soulmate_daemon.cli.import_module", refuse)

    # When: the owner inspects the local embedding model
    report = _report(capsys, Settings(data_dir=tmp_path))

    # Then: the command still succeeds and says the model cannot run here
    assert report["runtime_available"] is False
    assert report["runtime"] == dict.fromkeys(EMBEDDING_RUNTIME_MODULES, "missing")


def test_a_runtime_without_a_version_attribute_is_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a module that imports but exposes no version
    monkeypatch.setattr("soulmate_daemon.cli.import_module", lambda name: object())  # noqa: ARG005

    # When: the runtimes are probed
    runtime = _embedding_runtime()

    # Then: an unusable runtime is never reported as available
    assert runtime == dict.fromkeys(EMBEDDING_RUNTIME_MODULES, "missing")


def test_verifying_without_an_installed_model_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: an installation that never downloaded a model
    settings = Settings(data_dir=tmp_path)

    # When: the owner verifies it anyway
    report = _report(capsys, settings, verify=True, code=1)

    # Then: the command exits non-zero and says what is missing
    assert report["verified"] is False
    assert report["error"] == "The model is not installed."


def test_verifying_an_unusable_model_reports_the_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: files with the pinned names but contents no runtime can load
    settings = Settings(data_dir=tmp_path)
    store = artifact_store(settings)
    store.directory.mkdir(parents=True)
    for file in BGE_M3_INT8.files:
        store.path(file).write_bytes(b"not a model")

    # When: the owner verifies it
    report = _report(capsys, settings, verify=True, code=1)

    # Then: the failure is reported instead of raised, and nothing else broke
    assert report["verified"] is False
    assert report["error"] == "The embedding model could not be loaded."
    assert report["installed"] is True


def test_reading_the_status_never_loads_the_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: files no runtime can load
    settings = Settings(data_dir=tmp_path)
    store = artifact_store(settings)
    store.directory.mkdir(parents=True)
    for file in BGE_M3_INT8.files:
        store.path(file).write_bytes(b"not a model")

    # When: the owner reads the status without asking for verification
    report = _report(capsys, settings)

    # Then: nothing was loaded, so no verification result is reported at all
    assert "verified" not in report
    assert report["installed"] is True
