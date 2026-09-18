"""Pinned embedding model artifacts: owner-initiated download, verification, import.

Artifacts are identified by URL and SHA-256 so a withdrawn or re-uploaded upstream
file is a verification failure instead of a silent substitution (ADR-016). Nothing
here runs automatically: the daemon calls it only for an explicit owner action.
"""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from shutil import rmtree
from typing import Literal

import httpx
from soulmate_llm_providers import MODEL_ARTIFACT_CLASSIFICATION, EgressPolicy

DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60.0
PARTIAL_SUFFIX = ".part"


class ModelArtifactError(RuntimeError):
    """An artifact could not be downloaded, verified, imported, or removed."""


@dataclass(frozen=True, slots=True)
class ModelFile:
    """One pinned file of an artifact; ``approximate_bytes`` is the size P6 downloaded."""

    name: str
    url: str
    sha256: str
    approximate_bytes: int


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    """Everything the owner and the runtime need to know before a model is used."""

    model_id: str
    display_name: str
    license: str
    source: str
    dimensions: int
    max_tokens: int
    pooling: Literal["cls", "mean"]
    peak_memory_bytes: int
    weights_file: str
    tokenizer_file: str
    files: tuple[ModelFile, ...]

    @property
    def download_bytes(self) -> int:
        """Return the published download size, used for the owner's download dialog."""
        return sum(file.approximate_bytes for file in self.files)

    def file(self, name: str) -> ModelFile:
        """Return one pinned file, rejecting any name that is not part of the artifact."""
        for file in self.files:
            if file.name == name:
                return file
        raise KeyError(name)


BGE_M3_INT8 = ModelArtifact(
    model_id="bge-m3-int8",
    display_name="BGE-M3 (int8)",
    license="MIT",
    source="https://huggingface.co/Xenova/bge-m3",
    dimensions=1024,
    max_tokens=128,
    pooling="cls",
    # Measured while loaded on macOS arm64: 1765 MB in the P0 spike and 1908 MB when
    # P6 re-ran the same harness against the downloaded artifact; the owner is shown
    # the larger, rounded figure before a download.
    peak_memory_bytes=2_000_000_000,
    weights_file="model_int8.onnx",
    tokenizer_file="tokenizer.json",
    files=(
        ModelFile(
            name="model_int8.onnx",
            url="https://huggingface.co/Xenova/bge-m3/resolve/main/onnx/model_int8.onnx",
            sha256="a206e10e995aa2a833924bcd725ba5dd6c3425cd34bac3cf2b5677cd2a1c51d6",
            approximate_bytes=568_456_694,
        ),
        ModelFile(
            name="tokenizer.json",
            url="https://huggingface.co/Xenova/bge-m3/resolve/main/tokenizer.json",
            sha256="6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790",
            approximate_bytes=17_082_821,
        ),
    ),
)

MODEL_ARTIFACTS: dict[str, ModelArtifact] = {BGE_M3_INT8.model_id: BGE_M3_INT8}


@dataclass(frozen=True, slots=True)
class ModelFileStatus:
    name: str
    installed: bool
    downloaded_bytes: int
    expected_bytes: int


@dataclass(frozen=True, slots=True)
class ModelArtifactStatus:
    model_id: str
    installed: bool
    downloaded_bytes: int
    expected_bytes: int
    files: tuple[ModelFileStatus, ...]


@dataclass(frozen=True, slots=True)
class ArtifactProgress:
    """Bytes already on disk for the whole artifact while one file is streaming."""

    file_name: str
    downloaded_bytes: int
    expected_bytes: int


type ProgressCallback = Callable[[ArtifactProgress], None]


def file_sha256(path: Path) -> str:
    """Hash a file in chunks so a gigabyte-sized artifact never enters memory at once."""
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


class ModelArtifactStore:
    """The files of one pinned artifact inside ``DATA_DIR/models/<model_id>``."""

    def __init__(self, artifact: ModelArtifact, directory: Path) -> None:
        self._artifact = artifact
        self._directory = directory

    @property
    def artifact(self) -> ModelArtifact:
        return self._artifact

    @property
    def directory(self) -> Path:
        return self._directory

    def path(self, file: ModelFile) -> Path:
        return self._directory / file.name

    def partial_path(self, file: ModelFile) -> Path:
        return self._directory / f"{file.name}{PARTIAL_SUFFIX}"

    @property
    def weights_path(self) -> Path:
        return self.path(self._artifact.file(self._artifact.weights_file))

    @property
    def tokenizer_path(self) -> Path:
        return self.path(self._artifact.file(self._artifact.tokenizer_file))

    def installed(self) -> bool:
        """Report whether every pinned file was verified and activated."""
        return all(self.path(file).is_file() for file in self._artifact.files)

    def status(self) -> ModelArtifactStatus:
        files = tuple(self._file_status(file) for file in self._artifact.files)
        return ModelArtifactStatus(
            model_id=self._artifact.model_id,
            installed=all(item.installed for item in files),
            downloaded_bytes=sum(item.downloaded_bytes for item in files),
            expected_bytes=sum(item.expected_bytes for item in files),
            files=files,
        )

    def _file_status(self, file: ModelFile) -> ModelFileStatus:
        path = self.path(file)
        if path.is_file():
            size = path.stat().st_size
            return ModelFileStatus(file.name, True, size, size)
        partial = self.partial_path(file)
        downloaded = partial.stat().st_size if partial.is_file() else 0
        return ModelFileStatus(file.name, False, downloaded, file.approximate_bytes)

    def activate(self, source: Path, file: ModelFile) -> None:
        """Verify a completed file and move it into place, deleting it on a mismatch."""
        try:
            digest = file_sha256(source)
        except OSError as exc:
            source.unlink(missing_ok=True)
            raise ModelArtifactError(f"{file.name} could not be read for verification.") from exc
        if digest != file.sha256:
            source.unlink(missing_ok=True)
            raise ModelArtifactError(f"{file.name} failed SHA-256 verification and was discarded.")
        try:
            source.replace(self.path(file))
        except OSError as exc:
            raise ModelArtifactError(f"{file.name} could not be stored.") from exc

    def import_file(self, name: str, source: Path) -> ModelArtifactStatus:
        """Install one pinned file from a path the owner downloaded elsewhere."""
        try:
            file = self._artifact.file(name)
        except KeyError as exc:
            raise ModelArtifactError(f"{name} is not part of this model.") from exc
        if not source.is_file():
            raise ModelArtifactError("The file to import does not exist.")
        self._directory.mkdir(parents=True, exist_ok=True)
        staged = self.partial_path(file)
        try:
            with source.open("rb") as reader, staged.open("wb") as writer:
                while chunk := reader.read(DOWNLOAD_CHUNK_BYTES):
                    writer.write(chunk)
        except OSError as exc:
            staged.unlink(missing_ok=True)
            raise ModelArtifactError("The file to import could not be copied.") from exc
        self.activate(staged, file)
        return self.status()

    def remove(self) -> None:
        """Delete every file of this artifact, including interrupted downloads."""
        if not self._directory.exists():
            return
        try:
            rmtree(self._directory)
        except OSError as exc:
            raise ModelArtifactError("The model files could not be removed.") from exc


class ArtifactDownloader:
    """Resumable, verified download of a pinned artifact behind the egress policy."""

    def __init__(
        self,
        policy: EgressPolicy,
        *,
        client: httpx.AsyncClient | None = None,
        chunk_bytes: int = DOWNLOAD_CHUNK_BYTES,
    ) -> None:
        self._policy = policy
        self._client = client
        self._chunk_bytes = chunk_bytes

    def authorize(self, artifact: ModelArtifact) -> None:
        """Apply the central privacy boundary before any request is prepared."""
        for file in artifact.files:
            self._policy.require(
                provider=f"model_artifact:{artifact.model_id}",
                endpoint=file.url,
                data_classification=MODEL_ARTIFACT_CLASSIFICATION,
            )

    async def download(
        self, store: ModelArtifactStore, *, on_progress: ProgressCallback | None = None
    ) -> ModelArtifactStatus:
        """Fetch every missing file, resuming partial ones, and verify each before use."""
        artifact = store.artifact
        self.authorize(artifact)
        store.directory.mkdir(parents=True, exist_ok=True)
        if self._client is not None:
            await self._download_files(store, self._client, on_progress)
            return store.status()
        async with httpx.AsyncClient(
            timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            await self._download_files(store, client, on_progress)
        return store.status()

    async def _download_files(
        self,
        store: ModelArtifactStore,
        client: httpx.AsyncClient,
        on_progress: ProgressCallback | None,
    ) -> None:
        for file in store.artifact.files:
            if store.path(file).is_file():
                continue
            await self._download_file(store, client, file, on_progress)

    async def _download_file(
        self,
        store: ModelArtifactStore,
        client: httpx.AsyncClient,
        file: ModelFile,
        on_progress: ProgressCallback | None,
    ) -> None:
        partial = store.partial_path(file)
        offset = partial.stat().st_size if partial.is_file() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        completed = sum(
            store.path(other).stat().st_size
            for other in store.artifact.files
            if other.name != file.name and store.path(other).is_file()
        )
        try:
            async with client.stream("GET", file.url, headers=headers) as response:
                if response.status_code not in {200, 206}:
                    raise ModelArtifactError(f"{file.name} could not be downloaded.")
                resumed = response.status_code == 206 and offset > 0
                expected = _expected_bytes(response, file, resumed=resumed, offset=offset)
                written = offset if resumed else 0
                with partial.open("ab" if resumed else "wb") as handle:
                    async for chunk in response.aiter_bytes(self._chunk_bytes):
                        handle.write(chunk)
                        written += len(chunk)
                        if on_progress is not None:
                            on_progress(
                                ArtifactProgress(
                                    file_name=file.name,
                                    downloaded_bytes=completed + written,
                                    expected_bytes=completed + expected,
                                )
                            )
        except httpx.HTTPError as exc:
            # The partial file stays so the owner can resume instead of restarting.
            raise ModelArtifactError(f"{file.name} could not be downloaded.") from exc
        except OSError as exc:
            raise ModelArtifactError(f"{file.name} could not be written to disk.") from exc
        store.activate(partial, file)


def _expected_bytes(
    response: httpx.Response, file: ModelFile, *, resumed: bool, offset: int
) -> int:
    """Prefer the server's own size, falling back to the published size for progress."""
    length = response.headers.get("content-length")
    if length is not None and length.isdigit():
        return int(length) + (offset if resumed else 0)
    return max(file.approximate_bytes, offset)
