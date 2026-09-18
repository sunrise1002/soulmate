"""Local embedding adapter for the kernel embedding port.

The ONNX runtime is imported lazily inside the session loader, so an installation
that never enables embeddings never loads a native library, and a runtime that
fails to load degrades to the lexical key ranking of step A instead of failing a
request.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

from soulmate_core.embeddings import (
    EmbeddingProvider,
    EmbeddingUnavailableError,
    EmbeddingVector,
    NullEmbedding,
)

from soulmate_daemon.config import Settings
from soulmate_daemon.model_artifacts import (
    MODEL_ARTIFACTS,
    ModelArtifact,
    ModelArtifactStore,
)


class EmbeddingSession(Protocol):
    """A loaded model that can embed text until it is released."""

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]: ...


type SessionLoader = Callable[[], EmbeddingSession]
type Clock = Callable[[], datetime]


def artifact_for(settings: Settings) -> ModelArtifact:
    """Return the pinned artifact the configuration selects."""
    return MODEL_ARTIFACTS[settings.embedding.model_id]


def artifact_store(settings: Settings) -> ModelArtifactStore:
    """Locate the artifact files without creating or downloading anything."""
    artifact = artifact_for(settings)
    return ModelArtifactStore(artifact, settings.models_directory / artifact.model_id)


class LocalOnnxEmbedding:
    """Embed text on the device, loading the model on first use and releasing it when idle."""

    def __init__(
        self,
        store: ModelArtifactStore,
        *,
        idle_timeout: timedelta,
        loader: SessionLoader | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._idle_timeout = idle_timeout
        self._loader = loader if loader is not None else onnx_session_loader(store)
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._session: EmbeddingSession | None = None
        self._last_used: datetime | None = None

    @property
    def model_id(self) -> str:
        return self._store.artifact.model_id

    @property
    def dimensions(self) -> int:
        return self._store.artifact.dimensions

    @property
    def ready(self) -> bool:
        return self._store.installed()

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        if not texts:
            return ()
        self.release_if_idle()
        session = self._session if self._session is not None else self._load()
        self._last_used = self._clock()
        try:
            return session.embed(texts)
        except Exception as exc:
            # A native runtime defines its own exception tree: every onnxruntime
            # error derives straight from Exception, so narrowing here would let a
            # broken model escape instead of degrading to the lexical ranking.
            self.release()
            raise EmbeddingUnavailableError("The embedding model failed while running.") from exc

    def release_if_idle(self) -> None:
        """Free the model once it has not been used for the configured idle time."""
        if self._session is None or self._last_used is None:
            return
        if self._clock() - self._last_used >= self._idle_timeout:
            self.release()

    def release(self) -> None:
        self._session = None
        self._last_used = None

    def _load(self) -> EmbeddingSession:
        if not self.ready:
            raise EmbeddingUnavailableError("The embedding model is not installed.")
        try:
            session = self._loader()
        except Exception as exc:
            # Loading raises whatever the runtime, the tokenizer, or the file system
            # raises; a corrupt or foreign model file must still degrade quietly.
            raise EmbeddingUnavailableError("The embedding model could not be loaded.") from exc
        self._session = session
        return session


def onnx_session_loader(store: ModelArtifactStore) -> SessionLoader:
    """Build the default loader; its dependencies are imported only when it runs."""

    def load() -> EmbeddingSession:
        return _OnnxSession(store)

    return load


class _OnnxSession:
    """CLS pooling with L2 normalization, matching the P0 spike measurements."""

    def __init__(self, store: ModelArtifactStore) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        artifact = store.artifact
        self._numpy = np
        self._tokenizer = Tokenizer.from_file(str(store.tokenizer_path))
        self._tokenizer.enable_truncation(max_length=artifact.max_tokens)
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        self._session = ort.InferenceSession(
            str(store.weights_path), options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {value.name for value in self._session.get_inputs()}
        self._pooling = artifact.pooling

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        np = self._numpy
        encodings = self._tokenizer.encode_batch(list(texts))
        ids = np.array([encoding.ids for encoding in encodings], dtype=np.int64)
        mask = np.array([encoding.attention_mask for encoding in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = np.asarray(self._session.run(None, feeds)[0], dtype=np.float32)
        if hidden.ndim == 2:  # The export already pools.
            pooled = hidden
        elif self._pooling == "cls":
            pooled = hidden[:, 0]
        else:
            weights = mask.astype(np.float32)[:, :, None]
            pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.clip(norms, 1e-9, None)
        return tuple(tuple(float(value) for value in row) for row in normalized)


def embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Return the configured provider; the default never touches a model runtime."""
    if settings.embedding.provider == "none":
        return NullEmbedding()
    return LocalOnnxEmbedding(
        artifact_store(settings),
        idle_timeout=timedelta(seconds=settings.embedding.idle_release_seconds),
    )
