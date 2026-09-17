"""Owner-only API for the local embedding model artifact."""

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from soulmate_daemon.embedding_models import (
    EmbeddingModelError,
    EmbeddingModelService,
    EmbeddingModelState,
)
from soulmate_daemon.runtime import runtime_of


class EmbeddingModelFileResponse(BaseModel):
    name: str
    installed: bool
    downloaded_bytes: int
    expected_bytes: int


class EmbeddingModelResponse(BaseModel):
    """Everything the download dialog shows before the owner commits to a download."""

    provider: str
    model_id: str
    display_name: str
    license: str
    source: str
    dimensions: int
    download_bytes: int
    peak_memory_bytes: int
    installed: bool
    downloading: bool
    downloaded_bytes: int
    expected_bytes: int
    can_download: bool
    privacy_mode: str
    error: str | None
    files: list[EmbeddingModelFileResponse]


class EmbeddingModelImportRequest(BaseModel):
    """Offline fallback: install a pinned file the owner obtained elsewhere."""

    file_name: str = Field(min_length=1, max_length=200)
    source_path: str = Field(min_length=1, max_length=4096)

    @field_validator("file_name", "source_path")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Values must not be blank.")
        return value.strip()


def _response(state: EmbeddingModelState, privacy_mode: str) -> EmbeddingModelResponse:
    artifact = state.artifact
    return EmbeddingModelResponse(
        provider=state.provider,
        model_id=artifact.model_id,
        display_name=artifact.display_name,
        license=artifact.license,
        source=artifact.source,
        dimensions=artifact.dimensions,
        download_bytes=artifact.download_bytes,
        peak_memory_bytes=artifact.peak_memory_bytes,
        installed=state.status.installed,
        downloading=state.downloading,
        downloaded_bytes=state.downloaded_bytes,
        expected_bytes=state.expected_bytes,
        can_download=state.can_download,
        privacy_mode=privacy_mode,
        error=state.error,
        files=[
            EmbeddingModelFileResponse(
                name=item.name,
                installed=item.installed,
                downloaded_bytes=item.downloaded_bytes,
                expected_bytes=item.expected_bytes,
            )
            for item in state.status.files
        ],
    )


def build_embedding_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    def service() -> EmbeddingModelService:
        return runtime_of(app)["embedding_models"]

    def respond(state: EmbeddingModelState) -> EmbeddingModelResponse:
        return _response(state, runtime_of(app)["settings"].privacy.mode)

    @router.get("/v1/embedding-model", response_model=EmbeddingModelResponse)
    def read_model() -> EmbeddingModelResponse:
        return respond(service().state())

    @router.post("/v1/embedding-model/download", response_model=EmbeddingModelResponse)
    def start_download() -> EmbeddingModelResponse:
        try:
            state = service().start_download()
        except EmbeddingModelError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return respond(state)

    @router.post("/v1/embedding-model/cancel", response_model=EmbeddingModelResponse)
    async def cancel_download() -> EmbeddingModelResponse:
        try:
            state = await service().cancel()
        except EmbeddingModelError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return respond(state)

    @router.post("/v1/embedding-model/import", response_model=EmbeddingModelResponse)
    def import_model_file(request: EmbeddingModelImportRequest) -> EmbeddingModelResponse:
        try:
            state = service().import_file(request.file_name, Path(request.source_path))
        except EmbeddingModelError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return respond(state)

    @router.post("/v1/embedding-model/remove", response_model=EmbeddingModelResponse)
    def remove_model() -> EmbeddingModelResponse:
        try:
            state = service().remove()
        except EmbeddingModelError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return respond(state)

    return router
