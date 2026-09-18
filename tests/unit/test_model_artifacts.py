"""Pinned artifact storage, resumable verified download, and the egress boundary."""

import asyncio
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from soulmate_daemon.model_artifacts import (
    BGE_M3_INT8,
    ArtifactDownloader,
    ArtifactProgress,
    ModelArtifact,
    ModelArtifactError,
    ModelArtifactStore,
    ModelFile,
    file_sha256,
)
from soulmate_llm_providers import EgressDeniedError, EgressPolicy, PrivacyMode

WEIGHTS = b"synthetic-weights-payload" * 4
TOKENIZER = b"synthetic-tokenizer-payload"
WEIGHTS_URL = "https://models.example.test/weights.onnx"
TOKENIZER_URL = "https://models.example.test/tokenizer.json"


def _artifact(*, weights_url: str = WEIGHTS_URL, weights_sha: str | None = None) -> ModelArtifact:
    return ModelArtifact(
        model_id="synthetic-model",
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
                url=weights_url,
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


def _store(tmp_path: Path, artifact: ModelArtifact | None = None) -> ModelArtifactStore:
    resolved = artifact if artifact is not None else _artifact()
    return ModelArtifactStore(resolved, tmp_path / "models" / resolved.model_id)


def _bodies() -> dict[str, bytes]:
    return {WEIGHTS_URL: WEIGHTS, TOKENIZER_URL: TOKENIZER}


def _transport(
    bodies: dict[str, bytes],
    requests: list[httpx.Request],
    *,
    honor_range: bool = True,
    status: int = 200,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if status != 200:
            return httpx.Response(status)
        body = bodies[str(request.url)]
        requested = request.headers.get("range")
        if honor_range and requested is not None:
            offset = int(requested.removeprefix("bytes=").rstrip("-"))
            return httpx.Response(
                206,
                content=body[offset:],
                headers={"content-range": f"bytes {offset}-{len(body) - 1}/{len(body)}"},
            )
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)


def _download(
    store: ModelArtifactStore,
    transport: httpx.MockTransport,
    *,
    mode: PrivacyMode = "strict_local",
    progress: list[ArtifactProgress] | None = None,
) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            downloader = ArtifactDownloader(EgressPolicy(mode), client=client, chunk_bytes=8)
            await downloader.download(
                store, on_progress=None if progress is None else progress.append
            )

    asyncio.run(run())


def test_download_stores_and_verifies_every_pinned_file(tmp_path: Path) -> None:
    # Given: an artifact whose files are served in full
    store = _store(tmp_path)
    requests: list[httpx.Request] = []
    progress: list[ArtifactProgress] = []

    # When: the owner downloads it in strict local mode
    _download(store, _transport(_bodies(), requests), progress=progress)

    # Then: both files are installed with the pinned content and progress was reported
    assert store.installed()
    assert store.weights_path.read_bytes() == WEIGHTS
    assert store.tokenizer_path.read_bytes() == TOKENIZER
    assert [str(request.url) for request in requests] == [WEIGHTS_URL, TOKENIZER_URL]
    assert progress
    assert [item.downloaded_bytes for item in progress] == sorted(
        item.downloaded_bytes for item in progress
    )
    assert progress[-1].downloaded_bytes == len(WEIGHTS) + len(TOKENIZER)


def test_download_resumes_from_an_interrupted_partial_file(tmp_path: Path) -> None:
    # Given: half of the weights already on disk
    store = _store(tmp_path)
    store.directory.mkdir(parents=True)
    partial = store.partial_path(store.artifact.files[0])
    partial.write_bytes(WEIGHTS[:10])
    requests: list[httpx.Request] = []

    # When: the download runs again
    _download(store, _transport(_bodies(), requests))

    # Then: only the missing bytes were requested and the file verifies
    assert requests[0].headers["range"] == "bytes=10-"
    assert store.weights_path.read_bytes() == WEIGHTS


def test_download_restarts_when_the_server_ignores_the_range_request(tmp_path: Path) -> None:
    # Given: a partial file and a server that always answers with the whole body
    store = _store(tmp_path)
    store.directory.mkdir(parents=True)
    store.partial_path(store.artifact.files[0]).write_bytes(WEIGHTS[:10])
    requests: list[httpx.Request] = []

    # When: the download runs
    _download(store, _transport(_bodies(), requests, honor_range=False))

    # Then: the file is rewritten from the start instead of being appended to
    assert store.weights_path.read_bytes() == WEIGHTS


def test_download_discards_a_file_that_fails_sha256_verification(tmp_path: Path) -> None:
    # Given: an artifact pinned to a hash the served body does not match
    store = _store(tmp_path, _artifact(weights_sha=sha256(b"other").hexdigest()))
    requests: list[httpx.Request] = []

    # When: the owner downloads it
    with pytest.raises(ModelArtifactError) as error:
        _download(store, _transport(_bodies(), requests))

    # Then: the download failed and no partial or activated file survives
    assert "SHA-256" in str(error.value)
    assert not store.installed()
    assert not store.weights_path.exists()
    assert not store.partial_path(store.artifact.files[0]).exists()


def test_offline_mode_denies_the_download_before_any_request(tmp_path: Path) -> None:
    # Given: the offline privacy mode
    store = _store(tmp_path)
    requests: list[httpx.Request] = []

    # When: a download is attempted
    with pytest.raises(EgressDeniedError):
        _download(store, _transport(_bodies(), requests), mode="offline")

    # Then: nothing was requested and nothing was written
    assert requests == []
    assert not store.directory.exists()


def test_plain_http_artifact_endpoint_is_denied_in_every_mode(tmp_path: Path) -> None:
    # Given: an artifact pinned to an endpoint without transport security
    store = _store(tmp_path, _artifact(weights_url="http://models.example.test/weights.onnx"))
    requests: list[httpx.Request] = []

    # When: the owner downloads it in hybrid mode, the most permissive one
    with pytest.raises(EgressDeniedError):
        _download(store, _transport(_bodies(), requests), mode="hybrid")

    # Then: the egress boundary refused it
    assert requests == []


def test_strict_local_mode_allows_a_pinned_artifact_but_not_personal_data() -> None:
    # Given: the default privacy mode
    policy = EgressPolicy("strict_local")

    # When: the same endpoint is checked for an artifact and for personal data
    artifact = policy.can_send(
        provider="model_artifact:bge-m3-int8",
        endpoint=BGE_M3_INT8.files[0].url,
        data_classification="model_artifact",
    )
    personal = policy.can_send(
        provider="model_artifact:bge-m3-int8",
        endpoint=BGE_M3_INT8.files[0].url,
        data_classification="personal",
    )

    # Then: only the artifact download passes the boundary
    assert artifact
    assert not personal


def test_failed_http_status_leaves_the_artifact_uninstalled(tmp_path: Path) -> None:
    # Given: a server answering every request with 404
    store = _store(tmp_path)
    requests: list[httpx.Request] = []

    # When: the owner downloads it
    with pytest.raises(ModelArtifactError):
        _download(store, _transport(_bodies(), requests, status=404))

    # Then: no file remains installed
    assert not store.installed()


def test_a_broken_connection_keeps_the_partial_file_for_a_later_resume(tmp_path: Path) -> None:
    # Given: a server that fails after the response has started
    store = _store(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadError("Synthetic connection failure")

    # When: the download runs
    store.directory.mkdir(parents=True)
    store.partial_path(store.artifact.files[0]).write_bytes(WEIGHTS[:10])
    with pytest.raises(ModelArtifactError):
        _download(store, httpx.MockTransport(handler))

    # Then: the already downloaded bytes are kept so the owner can resume
    assert store.partial_path(store.artifact.files[0]).read_bytes() == WEIGHTS[:10]


def test_an_installed_file_is_never_downloaded_again(tmp_path: Path) -> None:
    # Given: the tokenizer already installed
    store = _store(tmp_path)
    store.directory.mkdir(parents=True)
    store.tokenizer_path.write_bytes(TOKENIZER)
    requests: list[httpx.Request] = []

    # When: the download runs
    _download(store, _transport(_bodies(), requests))

    # Then: only the missing file was fetched
    assert [str(request.url) for request in requests] == [WEIGHTS_URL]


def test_manual_import_installs_a_verified_file(tmp_path: Path) -> None:
    # Given: a file the owner obtained without network access
    store = _store(tmp_path)
    source = tmp_path / "weights.onnx"
    source.write_bytes(WEIGHTS)

    # When: the owner imports it
    status = store.import_file("weights.onnx", source)

    # Then: it is installed and the original file is untouched
    assert store.weights_path.read_bytes() == WEIGHTS
    assert source.exists()
    assert [item.installed for item in status.files] == [True, False]


def test_manual_import_rejects_a_file_with_the_wrong_hash(tmp_path: Path) -> None:
    # Given: a file that is not the pinned artifact
    store = _store(tmp_path)
    source = tmp_path / "weights.onnx"
    source.write_bytes(b"not the pinned weights")

    # When: the owner imports it
    with pytest.raises(ModelArtifactError) as error:
        store.import_file("weights.onnx", source)

    # Then: nothing is installed and the staged copy is gone
    assert "SHA-256" in str(error.value)
    assert not store.weights_path.exists()
    assert not store.partial_path(store.artifact.files[0]).exists()


def test_manual_import_rejects_a_missing_source_and_an_unknown_file_name(tmp_path: Path) -> None:
    # Given: an empty store
    store = _store(tmp_path)
    source = tmp_path / "weights.onnx"
    source.write_bytes(WEIGHTS)

    # When: the source is missing, or the name is not part of the artifact
    with pytest.raises(ModelArtifactError) as missing:
        store.import_file("weights.onnx", tmp_path / "absent.onnx")
    with pytest.raises(ModelArtifactError) as unknown:
        store.import_file("unexpected.bin", source)

    # Then: both are refused with a specific message
    assert "does not exist" in str(missing.value)
    assert "not part of this model" in str(unknown.value)


def test_remove_deletes_installed_and_partial_files(tmp_path: Path) -> None:
    # Given: one installed file and one interrupted download
    store = _store(tmp_path)
    store.directory.mkdir(parents=True)
    store.tokenizer_path.write_bytes(TOKENIZER)
    store.partial_path(store.artifact.files[0]).write_bytes(WEIGHTS[:5])

    # When: the owner removes the model
    store.remove()

    # Then: the directory is gone and removing again is harmless
    assert not store.directory.exists()
    store.remove()


def test_status_reports_zero_before_anything_is_downloaded(tmp_path: Path) -> None:
    # Given: an untouched store
    store = _store(tmp_path)

    # When: its status is read
    status = store.status()

    # Then: nothing is installed and the published sizes are reported
    assert not status.installed
    assert status.downloaded_bytes == 0
    assert status.expected_bytes == len(WEIGHTS) + len(TOKENIZER)
    assert [item.name for item in status.files] == ["weights.onnx", "tokenizer.json"]


def test_an_empty_pinned_file_still_verifies(tmp_path: Path) -> None:
    # Given: an artifact whose weights file is empty
    empty = _artifact(weights_sha=sha256(b"").hexdigest())
    store = _store(tmp_path, empty)
    bodies = {WEIGHTS_URL: b"", TOKENIZER_URL: TOKENIZER}

    # When: the owner downloads it
    _download(store, _transport(bodies, []))

    # Then: the zero-byte file is installed
    assert store.installed()
    assert store.weights_path.read_bytes() == b""


def test_unknown_file_names_are_rejected_by_the_artifact(tmp_path: Path) -> None:
    # Given: the pinned default artifact
    del tmp_path

    # When: an unknown file name is requested
    with pytest.raises(KeyError):
        BGE_M3_INT8.file("model_fp16.onnx")

    # Then: the known names stay available
    assert BGE_M3_INT8.file(BGE_M3_INT8.weights_file).sha256


def test_file_sha256_hashes_large_content_in_chunks(tmp_path: Path) -> None:
    # Given: content larger than one read chunk
    path = tmp_path / "artifact.bin"
    content = b"soulmate" * 400_000
    path.write_bytes(content)

    # When: the helper hashes it
    digest = file_sha256(path)

    # Then: the digest matches the whole content
    assert digest == sha256(content).hexdigest()


def test_default_artifact_pins_match_the_recorded_spike_measurements() -> None:
    # Given: the pins recorded in the P0 spike report
    report = (
        Path(__file__).resolve().parents[2] / "docs/phases/key-consistency-p0-spike-report.md"
    ).read_text(encoding="utf-8")

    # When: the shipped artifact is compared with it
    hashes = [file.sha256 for file in BGE_M3_INT8.files]

    # Then: every pinned hash and endpoint is the documented one
    assert all(digest in report for digest in hashes)
    assert all(
        file.url.startswith("https://huggingface.co/Xenova/bge-m3/") for file in BGE_M3_INT8.files
    )
    assert BGE_M3_INT8.license == "MIT"
    assert BGE_M3_INT8.pooling == "cls"
    assert BGE_M3_INT8.max_tokens == 128
