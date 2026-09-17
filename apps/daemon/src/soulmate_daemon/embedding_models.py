"""Owner-driven acquisition of the pinned embedding model artifact.

Nothing here runs by itself: every download, import, and removal is one explicit
owner action, gated by the central egress policy and verified against the pinned
SHA-256 before the model can be used (ADR-016).
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from soulmate_core.domain import AuditEvent, AuditEventRepository
from soulmate_llm_providers import EgressDeniedError, EgressPolicy

from soulmate_daemon.config import Settings
from soulmate_daemon.embeddings import artifact_store
from soulmate_daemon.model_artifacts import (
    ArtifactDownloader,
    ArtifactProgress,
    ModelArtifact,
    ModelArtifactError,
    ModelArtifactStatus,
    ModelArtifactStore,
)

EMBEDDING_DOWNLOAD_STARTED = "model.embedding_download_started"
EMBEDDING_DOWNLOAD_COMPLETED = "model.embedding_download_completed"
EMBEDDING_DOWNLOAD_FAILED = "model.embedding_download_failed"
EMBEDDING_DOWNLOAD_DENIED = "model.embedding_download_denied"
EMBEDDING_MODEL_IMPORTED = "model.embedding_model_imported"
EMBEDDING_MODEL_REMOVED = "model.embedding_model_removed"


class EmbeddingModelError(RuntimeError):
    """An owner action on the model artifact conflicts with its current state."""


@dataclass(frozen=True, slots=True)
class EmbeddingModelState:
    """What the client shows next to the download button."""

    provider: str
    artifact: ModelArtifact
    status: ModelArtifactStatus
    downloading: bool
    downloaded_bytes: int
    expected_bytes: int
    error: str | None
    can_download: bool


class EmbeddingModelService:
    """Owner-only acquisition of the pinned artifact; one download runs at a time."""

    def __init__(
        self,
        settings: Settings,
        audit_events: AuditEventRepository,
        *,
        profile_id: str,
        downloader: ArtifactDownloader | None = None,
    ) -> None:
        self._settings = settings
        self._audit_events = audit_events
        self._profile_id = profile_id
        self._store = artifact_store(settings)
        self._downloader = (
            downloader
            if downloader is not None
            else ArtifactDownloader(EgressPolicy(settings.privacy.mode))
        )
        self._task: asyncio.Task[ModelArtifactStatus] | None = None
        self._progress: ArtifactProgress | None = None
        self._error: str | None = None

    @property
    def store(self) -> ModelArtifactStore:
        return self._store

    def state(self) -> EmbeddingModelState:
        status = self._store.status()
        downloading = self._task is not None and not self._task.done()
        progress = self._progress
        return EmbeddingModelState(
            provider=self._settings.embedding.provider,
            artifact=self._store.artifact,
            status=status,
            downloading=downloading,
            downloaded_bytes=(
                progress.downloaded_bytes
                if downloading and progress is not None
                else status.downloaded_bytes
            ),
            expected_bytes=(
                progress.expected_bytes
                if downloading and progress is not None
                else status.expected_bytes
            ),
            error=self._error,
            can_download=self._can_download(),
        )

    def _can_download(self) -> bool:
        try:
            self._downloader.authorize(self._store.artifact)
        except EgressDeniedError:
            return False
        return True

    def start_download(self) -> EmbeddingModelState:
        """Start the one background download an owner action may create."""
        if self._task is not None and not self._task.done():
            raise EmbeddingModelError("A model download is already running.")
        if self._store.installed():
            raise EmbeddingModelError("The model is already installed.")
        try:
            self._downloader.authorize(self._store.artifact)
        except EgressDeniedError as exc:
            self._audit(EMBEDDING_DOWNLOAD_DENIED, {})
            raise EmbeddingModelError(
                "The configured privacy mode denies downloading a model."
            ) from exc
        self._error = None
        self._progress = None
        self._audit(
            EMBEDDING_DOWNLOAD_STARTED,
            {"download_bytes": self._store.artifact.download_bytes},
        )
        self._task = asyncio.create_task(self._run_download(), name="soulmate-model-download")
        return self.state()

    async def _run_download(self) -> ModelArtifactStatus:
        try:
            status = await self._downloader.download(self._store, on_progress=self._record)
        except (EgressDeniedError, ModelArtifactError, OSError) as exc:
            self._error = str(exc)
            self._audit(EMBEDDING_DOWNLOAD_FAILED, {"error_type": type(exc).__name__})
            raise
        self._audit(EMBEDDING_DOWNLOAD_COMPLETED, {"downloaded_bytes": status.downloaded_bytes})
        return status

    def _record(self, progress: ArtifactProgress) -> None:
        self._progress = progress

    async def wait(self) -> None:
        """Await the running download, ignoring a failure already recorded in the state."""
        if self._task is None:
            return
        task = self._task
        try:
            await task
        except (EgressDeniedError, ModelArtifactError, OSError, asyncio.CancelledError):
            return

    async def shutdown(self) -> None:
        """Stop a running download so the process can exit; the partial file remains."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        await self.wait()

    async def cancel(self) -> EmbeddingModelState:
        """Stop a running download; the partial file stays so it can be resumed."""
        if self._task is None or self._task.done():
            raise EmbeddingModelError("No model download is running.")
        self._task.cancel()
        await self.wait()
        self._error = None
        self._progress = None
        return self.state()

    def import_file(self, name: str, source: Path) -> EmbeddingModelState:
        """Install one pinned file the owner obtained without network access."""
        if self._task is not None and not self._task.done():
            raise EmbeddingModelError("A model download is already running.")
        try:
            self._store.import_file(name, source)
        except ModelArtifactError as exc:
            raise EmbeddingModelError(str(exc)) from exc
        self._error = None
        self._audit(EMBEDDING_MODEL_IMPORTED, {"file": name})
        return self.state()

    def remove(self) -> EmbeddingModelState:
        """Delete the artifact, including a partial download."""
        if self._task is not None and not self._task.done():
            raise EmbeddingModelError("A model download is already running.")
        if not self._store.directory.exists():
            raise EmbeddingModelError("No model files are stored.")
        try:
            self._store.remove()
        except ModelArtifactError as exc:
            raise EmbeddingModelError(str(exc)) from exc
        self._error = None
        self._progress = None
        self._audit(EMBEDDING_MODEL_REMOVED, {})
        return self.state()

    def _audit(self, action: str, metadata: dict[str, object]) -> None:
        # Model acquisition carries no personal data, so only the artifact is recorded.
        self._audit_events.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                profile_id=self._profile_id,
                action=action,
                actor_type="owner",
                actor_id=None,
                metadata={
                    "model_id": self._store.artifact.model_id,
                    "privacy_mode": self._settings.privacy.mode,
                    **metadata,
                },
                created_at=datetime.now(UTC),
            )
        )
