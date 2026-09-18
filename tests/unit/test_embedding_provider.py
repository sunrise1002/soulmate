"""The kernel embedding port, its null default, and the lazily loaded local adapter."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from soulmate_core.embeddings import (
    EmbeddingProvider,
    EmbeddingUnavailableError,
    EmbeddingVector,
    NullEmbedding,
)
from soulmate_daemon.config import EmbeddingConfig, Settings
from soulmate_daemon.embeddings import LocalOnnxEmbedding, artifact_store, embedding_provider
from soulmate_daemon.model_artifacts import ModelArtifactStore

START = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
IDLE = timedelta(minutes=5)


class FakeSession:
    """A loaded model that records every run."""

    def __init__(self, failure: Exception | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._failure = failure

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        self.calls.append(tuple(texts))
        if self._failure is not None:
            raise self._failure
        return tuple((1.0, 0.0, 0.0, float(len(text))) for text in texts)


class FakeClock:
    """A clock the test advances explicitly."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def _installed_store(tmp_path: Path) -> ModelArtifactStore:
    store = artifact_store(Settings(data_dir=tmp_path))
    store.directory.mkdir(parents=True)
    for file in store.artifact.files:
        store.path(file).write_bytes(b"synthetic")
    return store


def _adapter(
    store: ModelArtifactStore,
    sessions: list[FakeSession],
    clock: FakeClock,
    *,
    failure: Exception | None = None,
) -> LocalOnnxEmbedding:
    def loader() -> FakeSession:
        if failure is not None:
            raise failure
        session = FakeSession()
        sessions.append(session)
        return session

    return LocalOnnxEmbedding(store, idle_timeout=IDLE, loader=loader, clock=clock)


def test_null_embedding_reports_no_model_and_refuses_to_embed() -> None:
    # Given: the default provider
    provider: EmbeddingProvider = NullEmbedding()

    # When: its capabilities are read and an embedding was requested
    with pytest.raises(EmbeddingUnavailableError) as error:
        provider.embed(["giao diện tối"])

    # Then: it advertises no model and tells the caller to fall back
    assert provider.model_id == "none"
    assert provider.dimensions == 0
    assert not provider.ready
    assert "No embedding provider is enabled." in str(error.value)
    provider.release()


def test_local_adapter_without_installed_files_never_loads_a_model(tmp_path: Path) -> None:
    # Given: an artifact that was never downloaded
    store = artifact_store(Settings(data_dir=tmp_path))
    sessions: list[FakeSession] = []
    adapter = _adapter(store, sessions, FakeClock())

    # When: an embedding was requested
    with pytest.raises(EmbeddingUnavailableError) as error:
        adapter.embed(["giao diện tối"])

    # Then: the adapter reports it cannot run and loaded nothing
    assert not adapter.ready
    assert "not installed" in str(error.value)
    assert sessions == []


def test_local_adapter_loads_once_and_reuses_the_session(tmp_path: Path) -> None:
    # Given: an installed artifact and a clock inside the idle window
    clock = FakeClock()
    sessions: list[FakeSession] = []
    adapter = _adapter(_installed_store(tmp_path), sessions, clock)

    # When: two embeddings run shortly after each other
    first = adapter.embed(["giao diện tối"])
    clock.now = START + IDLE - timedelta(seconds=1)
    second = adapter.embed(["dark theme", "light theme"])

    # Then: one session served both calls
    assert adapter.ready
    assert adapter.model_id == "bge-m3-int8"
    assert adapter.dimensions == 1024
    assert len(sessions) == 1
    assert sessions[0].calls == [("giao diện tối",), ("dark theme", "light theme")]
    assert len(first) == 1
    assert len(second) == 2


def test_local_adapter_releases_the_model_once_it_is_idle(tmp_path: Path) -> None:
    # Given: a loaded model
    clock = FakeClock()
    sessions: list[FakeSession] = []
    adapter = _adapter(_installed_store(tmp_path), sessions, clock)
    adapter.embed(["giao diện tối"])

    # When: exactly the idle timeout passed before the next call
    clock.now = START + IDLE
    adapter.embed(["giao diện tối"])

    # Then: the memory was returned and a fresh session was loaded
    assert len(sessions) == 2


def test_local_adapter_keeps_the_model_just_below_the_idle_timeout(tmp_path: Path) -> None:
    # Given: a loaded model
    clock = FakeClock()
    sessions: list[FakeSession] = []
    adapter = _adapter(_installed_store(tmp_path), sessions, clock)
    adapter.embed(["giao diện tối"])

    # When: one second less than the idle timeout passed
    clock.now = START + IDLE - timedelta(seconds=1)
    adapter.release_if_idle()
    adapter.embed(["giao diện tối"])

    # Then: the same session is still in use
    assert len(sessions) == 1


def test_local_adapter_returns_nothing_for_an_empty_request(tmp_path: Path) -> None:
    # Given: an installed artifact
    sessions: list[FakeSession] = []
    adapter = _adapter(_installed_store(tmp_path), sessions, FakeClock())

    # When: an empty batch was submitted
    vectors = adapter.embed([])

    # Then: no model was loaded at all
    assert vectors == ()
    assert sessions == []


def test_a_missing_native_runtime_degrades_instead_of_failing(tmp_path: Path) -> None:
    # Given: an installed artifact but no onnxruntime on the machine
    sessions: list[FakeSession] = []
    adapter = _adapter(
        _installed_store(tmp_path),
        sessions,
        FakeClock(),
        failure=ImportError("No module named 'onnxruntime'"),
    )

    # When: an embedding was requested
    with pytest.raises(EmbeddingUnavailableError) as error:
        adapter.embed(["giao diện tối"])

    # Then: the caller learns to fall back, with the real cause attached
    assert "could not be loaded" in str(error.value)
    assert isinstance(error.value.__cause__, ImportError)


class NativeRuntimeError(Exception):
    """Mirror an onnxruntime failure: it derives from Exception, not RuntimeError."""


def test_a_native_load_failure_degrades_instead_of_failing(tmp_path: Path) -> None:
    # Given: a corrupt model file, which onnxruntime reports with its own exception
    sessions: list[FakeSession] = []
    adapter = _adapter(
        _installed_store(tmp_path),
        sessions,
        FakeClock(),
        failure=NativeRuntimeError("INVALID_PROTOBUF : Protobuf parsing failed."),
    )

    # When: an embedding was requested
    with pytest.raises(EmbeddingUnavailableError) as error:
        adapter.embed(["giao diện tối"])

    # Then: the port contract holds for an exception tree the adapter cannot enumerate
    assert "could not be loaded" in str(error.value)
    assert isinstance(error.value.__cause__, NativeRuntimeError)


def test_a_native_run_failure_releases_the_session(tmp_path: Path) -> None:
    # Given: a loaded session whose native run fails
    store = _installed_store(tmp_path)
    session = FakeSession(failure=NativeRuntimeError("RUNTIME_EXCEPTION : Non-zero status code."))
    adapter = LocalOnnxEmbedding(
        store, idle_timeout=IDLE, loader=lambda: session, clock=FakeClock()
    )

    # When: an embedding was requested
    with pytest.raises(EmbeddingUnavailableError) as error:
        adapter.embed(["giao diện tối"])

    # Then: the broken session was dropped and the caller can fall back
    assert "failed while running" in str(error.value)
    assert isinstance(error.value.__cause__, NativeRuntimeError)


def test_a_failing_model_run_releases_the_session(tmp_path: Path) -> None:
    # Given: a session that raises while running
    store = _installed_store(tmp_path)
    session = FakeSession(failure=RuntimeError("Synthetic inference failure"))
    adapter = LocalOnnxEmbedding(
        store, idle_timeout=IDLE, loader=lambda: session, clock=FakeClock()
    )

    # When: an embedding was requested
    with pytest.raises(EmbeddingUnavailableError) as error:
        adapter.embed(["giao diện tối"])

    # Then: the broken session was dropped so the next call reloads
    assert "failed while running" in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)
    adapter.release()


def test_release_before_any_load_is_harmless(tmp_path: Path) -> None:
    # Given: an adapter that never ran
    sessions: list[FakeSession] = []
    adapter = _adapter(_installed_store(tmp_path), sessions, FakeClock())

    # When: the daemon releases it anyway
    adapter.release_if_idle()
    adapter.release()

    # Then: nothing was loaded and nothing failed
    assert sessions == []


def test_configuration_selects_the_null_provider_by_default(tmp_path: Path) -> None:
    # Given: the default configuration
    settings = Settings(data_dir=tmp_path)

    # When: the provider is built
    provider = embedding_provider(settings)

    # Then: no model runtime is involved
    assert isinstance(provider, NullEmbedding)
    assert settings.embedding.provider == "none"


def test_configuration_selects_the_local_provider_when_enabled(tmp_path: Path) -> None:
    # Given: a configuration that enables local embeddings
    settings = Settings(data_dir=tmp_path, embedding=EmbeddingConfig(provider="local"))

    # When: the provider is built
    provider: EmbeddingProvider = embedding_provider(settings)

    # Then: the local adapter satisfies the port and stays unloaded until used
    assert isinstance(provider, LocalOnnxEmbedding)
    assert provider.model_id == "bge-m3-int8"
    assert not provider.ready
