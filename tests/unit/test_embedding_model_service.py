"""Owner-driven model acquisition: download, cancel, import, remove, and audits."""

import asyncio
from collections.abc import Coroutine
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
import pytest
from soulmate_core.domain import AuditEvent
from soulmate_daemon.config import PrivacyConfig, Settings
from soulmate_daemon.embedding_models import (
    EMBEDDING_DOWNLOAD_COMPLETED,
    EMBEDDING_DOWNLOAD_DENIED,
    EMBEDDING_DOWNLOAD_FAILED,
    EMBEDDING_DOWNLOAD_STARTED,
    EMBEDDING_MODEL_IMPORTED,
    EMBEDDING_MODEL_REMOVED,
    EmbeddingModelError,
    EmbeddingModelService,
)
from soulmate_daemon.model_artifacts import (
    MODEL_ARTIFACTS,
    ArtifactDownloader,
    ModelArtifact,
    ModelArtifactError,
    ModelFile,
)
from soulmate_llm_providers import EgressPolicy, PrivacyMode

PROFILE_ID = "profile_default"
WEIGHTS = b"synthetic-weights" * 8
TOKENIZER = b"synthetic-tokenizer"
WEIGHTS_URL = "https://models.example.test/weights.onnx"
TOKENIZER_URL = "https://models.example.test/tokenizer.json"


class RecordingAuditEvents:
    """Collect audit events without a database."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def add(self, event: AuditEvent) -> None:
        self.events.append(event)

    def get(self, event_id: str) -> AuditEvent | None:
        return next((event for event in self.events if event.id == event_id), None)

    def list_for_profile(self, profile_id: str, limit: int = 100) -> tuple[AuditEvent, ...]:
        return tuple(event for event in self.events if event.profile_id == profile_id)[:limit]

    def actions(self) -> list[str]:
        return [event.action for event in self.events]

    def metadata(self, index: int) -> dict[str, Any]:
        recorded = self.events[index].metadata
        assert recorded is not None
        return recorded


def _artifact(*, weights_sha: str | None = None) -> ModelArtifact:
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
                url=WEIGHTS_URL,
                sha256=weights_sha if weights_sha is not None else sha256(WEIGHTS).hexdigest(),
                approximate_bytes=len(WEIGHTS),
            ),
            ModelFile(
                name="tokenizer.json",
                url=TOKENIZER_URL,
                sha256=sha256(TOKENIZER).hexdigest(),
                approximate_bytes=len(TOKENIZER),
            ),
        ),
    )


def _transport(*, block: asyncio.Event | None = None) -> httpx.MockTransport:
    bodies = {WEIGHTS_URL: WEIGHTS, TOKENIZER_URL: TOKENIZER}

    async def handler(request: httpx.Request) -> httpx.Response:
        if block is not None:
            await block.wait()
        return httpx.Response(200, content=bodies[str(request.url)])

    return httpx.MockTransport(handler)


def _service(
    tmp_path: Path,
    audit: RecordingAuditEvents,
    client: httpx.AsyncClient | None,
    *,
    mode: PrivacyMode = "strict_local",
) -> EmbeddingModelService:
    settings = Settings(data_dir=tmp_path, privacy=PrivacyConfig(mode=mode))
    downloader = ArtifactDownloader(
        EgressPolicy(settings.privacy.mode), client=client, chunk_bytes=8
    )
    return EmbeddingModelService(settings, audit, profile_id=PROFILE_ID, downloader=downloader)


def _run(work: Coroutine[Any, Any, None]) -> None:
    asyncio.run(work)


@pytest.fixture(autouse=True)
def synthetic_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin a small synthetic artifact so tests never touch the real 568 MB download."""
    monkeypatch.setitem(MODEL_ARTIFACTS, "bge-m3-int8", _artifact())


def test_owner_download_installs_the_artifact_and_records_audits(tmp_path: Path) -> None:
    # Given: a strict local installation with nothing downloaded
    audit = RecordingAuditEvents()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=_transport()) as client:
            service = _service(tmp_path, audit, client)
            # When: the owner starts the download and it finishes
            started = service.start_download()
            assert started.downloading
            await service.wait()
            state = service.state()

        # Then: the model is installed and both steps are audited without key names
        assert state.status.installed
        assert not state.downloading
        assert state.error is None
        assert audit.actions() == [
            EMBEDDING_DOWNLOAD_STARTED,
            EMBEDDING_DOWNLOAD_COMPLETED,
        ]
        assert audit.metadata(0)["model_id"] == "bge-m3-int8"
        assert audit.metadata(0)["privacy_mode"] == "strict_local"

    _run(exercise())


def test_offline_mode_refuses_to_start_a_download(tmp_path: Path) -> None:
    # Given: an installation in offline mode
    audit = RecordingAuditEvents()
    service = _service(tmp_path, audit, None, mode="offline")

    # When: the owner presses download
    with pytest.raises(EmbeddingModelError) as error:
        service.start_download()

    # Then: the refusal is audited and nothing is downloading
    assert "privacy mode" in str(error.value)
    assert audit.actions() == [EMBEDDING_DOWNLOAD_DENIED]
    assert not service.state().can_download
    assert not service.state().downloading


def test_a_verification_failure_is_reported_and_leaves_nothing_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an artifact pinned to a hash the server does not serve
    monkeypatch.setitem(
        MODEL_ARTIFACTS, "bge-m3-int8", _artifact(weights_sha=sha256(b"other").hexdigest())
    )
    audit = RecordingAuditEvents()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=_transport()) as client:
            service = _service(tmp_path, audit, client)
            # When: the owner downloads it
            service.start_download()
            await service.wait()
            state = service.state()

        # Then: the failure is visible to the owner and audited
        assert not state.status.installed
        assert state.error is not None
        assert "SHA-256" in state.error
        assert audit.actions() == [EMBEDDING_DOWNLOAD_STARTED, EMBEDDING_DOWNLOAD_FAILED]
        assert audit.metadata(1)["error_type"] == ModelArtifactError.__name__

    _run(exercise())


def test_a_second_download_is_refused_while_one_is_running(tmp_path: Path) -> None:
    # Given: a download that has not finished yet
    audit = RecordingAuditEvents()
    block = asyncio.Event()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=_transport(block=block)) as client:
            service = _service(tmp_path, audit, client)
            service.start_download()
            await asyncio.sleep(0)

            # When: the owner presses download again
            with pytest.raises(EmbeddingModelError) as error:
                service.start_download()

            # Then: the running download continues and finishes on its own
            assert "already running" in str(error.value)
            block.set()
            await service.wait()
            assert service.state().status.installed

    _run(exercise())


def test_downloading_an_installed_model_is_refused(tmp_path: Path) -> None:
    # Given: an installed model
    audit = RecordingAuditEvents()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=_transport()) as client:
            service = _service(tmp_path, audit, client)
            service.start_download()
            await service.wait()

            # When: the owner presses download again
            with pytest.raises(EmbeddingModelError) as error:
                service.start_download()

            # Then: nothing is downloaded a second time
            assert "already installed" in str(error.value)

    _run(exercise())


def test_cancelling_keeps_the_partial_download_for_a_later_resume(tmp_path: Path) -> None:
    # Given: a download waiting on a slow server
    audit = RecordingAuditEvents()
    block = asyncio.Event()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=_transport(block=block)) as client:
            service = _service(tmp_path, audit, client)
            service.start_download()
            await asyncio.sleep(0)

            # When: the owner cancels it
            state = await service.cancel()

            # Then: nothing is installed, no error is shown, and a later start works
            assert not state.downloading
            assert state.error is None
            assert not state.status.installed
            block.set()
            service.start_download()
            await service.wait()
            assert service.state().status.installed

    _run(exercise())


def test_cancelling_without_a_running_download_is_refused(tmp_path: Path) -> None:
    # Given: an idle service
    service = _service(tmp_path, RecordingAuditEvents(), None)

    # When: the owner cancels
    async def exercise() -> None:
        with pytest.raises(EmbeddingModelError) as error:
            await service.cancel()
        # Then: the refusal names the missing download
        assert "No model download" in str(error.value)

    _run(exercise())


def test_manual_import_and_removal_are_audited(tmp_path: Path) -> None:
    # Given: pinned files the owner copied onto the device
    audit = RecordingAuditEvents()
    service = _service(tmp_path, audit, None)
    weights = tmp_path / "weights.onnx"
    weights.write_bytes(WEIGHTS)
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_bytes(TOKENIZER)

    # When: both are imported and then removed
    service.import_file("weights.onnx", weights)
    imported = service.import_file("tokenizer.json", tokenizer)
    removed = service.remove()

    # Then: the model became installed offline and every action is audited
    assert imported.status.installed
    assert not removed.status.installed
    assert audit.actions() == [
        EMBEDDING_MODEL_IMPORTED,
        EMBEDDING_MODEL_IMPORTED,
        EMBEDDING_MODEL_REMOVED,
    ]


def test_manual_import_of_the_wrong_file_is_refused(tmp_path: Path) -> None:
    # Given: a file that does not match the pinned hash
    audit = RecordingAuditEvents()
    service = _service(tmp_path, audit, None)
    source = tmp_path / "weights.onnx"
    source.write_bytes(b"not the pinned weights")

    # When: the owner imports it
    with pytest.raises(EmbeddingModelError) as error:
        service.import_file("weights.onnx", source)

    # Then: no file was installed and no action was audited
    assert "SHA-256" in str(error.value)
    assert not service.state().status.installed
    assert audit.actions() == []


def test_removing_without_stored_files_is_refused(tmp_path: Path) -> None:
    # Given: a service that never downloaded anything
    service = _service(tmp_path, RecordingAuditEvents(), None)

    # When: the owner removes the model
    with pytest.raises(EmbeddingModelError) as error:
        service.remove()

    # Then: the refusal explains that nothing is stored
    assert "No model files" in str(error.value)


def test_state_reports_download_progress_while_it_runs(tmp_path: Path) -> None:
    # Given: a download waiting on a slow server
    audit = RecordingAuditEvents()
    block = asyncio.Event()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=_transport(block=block)) as client:
            service = _service(tmp_path, audit, client)
            service.start_download()
            await asyncio.sleep(0)

            # When: the owner reads the state before and after the transfer
            during = service.state()
            block.set()
            await service.wait()
            after = service.state()

            # Then: progress starts at zero and ends at the artifact size
            assert during.downloading
            assert during.downloaded_bytes == 0
            assert not after.downloading
            assert after.downloaded_bytes == len(WEIGHTS) + len(TOKENIZER)
            assert after.expected_bytes == len(WEIGHTS) + len(TOKENIZER)

    _run(exercise())


def test_shutdown_stops_a_running_download(tmp_path: Path) -> None:
    # Given: a download waiting on a slow server
    audit = RecordingAuditEvents()
    block = asyncio.Event()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=_transport(block=block)) as client:
            service = _service(tmp_path, audit, client)
            service.start_download()
            await asyncio.sleep(0)

            # When: the daemon shuts down
            await service.shutdown()

            # Then: the task is gone and a second shutdown is harmless
            assert not service.state().downloading
            await service.shutdown()

    _run(exercise())
