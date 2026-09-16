"""Owner-only API for backups, encrypted exports, restores, and static imports."""

import base64
import binascii
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from soulmate_core.domain import AuditEvent, Source, SourceDeletion
from soulmate_core.importing import ImportFormat
from soulmate_core.preferences import ModelRebuilder

from soulmate_daemon.imports import ChatImportService, ImportResult
from soulmate_daemon.portability import (
    ArchiveResult,
    ArchiveService,
    PortabilityError,
    stage_restore,
)
from soulmate_daemon.remote_backup import (
    LAST_REMOTE_BACKUP_AT,
    RemoteBackupError,
    RemoteBackupResult,
    RemoteBackupService,
    parse_metadata_time,
)
from soulmate_daemon.runtime import runtime_of
from soulmate_daemon.system import DEFAULT_PROFILE_ID

MAX_IMPORT_CONTENT_LENGTH = 20_000_000
MAX_RESTORE_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_RESTORE_BASE64_LENGTH = ((MAX_RESTORE_UPLOAD_BYTES + 2) // 3) * 4


class SourceResponse(BaseModel):
    id: str
    source_type: str
    name: str
    created_at: datetime


class ImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    format: ImportFormat = ImportFormat.AUTO
    content: str = Field(min_length=1, max_length=MAX_IMPORT_CONTENT_LENGTH)

    @field_validator("name", "content")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Import name and content must not be blank.")
        return value


class ImportResponse(BaseModel):
    source: SourceResponse
    detected_format: str
    conversation_count: int
    message_count: int


class SourceDeletionResponse(BaseModel):
    source_id: str
    raw_event_count: int
    conversation_count: int
    message_count: int
    evidence_count: int
    snapshot_version: int


class ExportRequest(BaseModel):
    passphrase: str = Field(min_length=12, max_length=1024)


class RestoreRequest(BaseModel):
    archive_base64: str = Field(min_length=1, max_length=MAX_RESTORE_BASE64_LENGTH)
    passphrase: str | None = Field(default=None, max_length=1024)


class ArchiveResponse(BaseModel):
    path: str
    filename: str
    created_at: datetime
    size_bytes: int
    sha256: str
    encrypted: bool
    schema_revision: str


class RestoreResponse(BaseModel):
    staged: bool
    source_schema_revision: str
    restart_required: bool


class RemoteBackupResponse(BaseModel):
    archive: ArchiveResponse
    backend: str
    remote_key: str


class RemoteBackupStatusResponse(BaseModel):
    configured: bool
    backend: str
    automatic_daily: bool
    interval_hours: int
    last_success_at: datetime | None


def _source_response(source: Source) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        source_type=source.source_type,
        name=source.name,
        created_at=source.created_at,
    )


def _import_response(result: ImportResult) -> ImportResponse:
    return ImportResponse(
        source=_source_response(result.source),
        detected_format=result.detected_format.value,
        conversation_count=result.conversation_count,
        message_count=result.message_count,
    )


def _archive_response(result: ArchiveResult) -> ArchiveResponse:
    return ArchiveResponse(
        path=str(result.path),
        filename=result.path.name,
        created_at=result.created_at,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        encrypted=result.encrypted,
        schema_revision=result.schema_revision,
    )


def _remote_backup_response(app: FastAPI, result: RemoteBackupResult) -> RemoteBackupResponse:
    return RemoteBackupResponse(
        archive=_archive_response(result.archive),
        backend=runtime_of(app)["settings"].remote_backup.backend,
        remote_key=result.remote.key,
    )


def _remote_backup_service(app: FastAPI) -> RemoteBackupService:
    service = runtime_of(app)["remote_backup"]
    if service is None:
        raise HTTPException(status_code=409, detail="Remote backup is not configured.")
    return service


def _record_audit(app: FastAPI, action: str, metadata: dict[str, object]) -> None:
    runtime_of(app)["repositories"].audit_events.add(
        AuditEvent(
            id=f"audit_{uuid4().hex}",
            profile_id=DEFAULT_PROFILE_ID,
            action=action,
            actor_type="owner",
            actor_id=None,
            metadata=metadata,
            created_at=datetime.now(UTC),
        )
    )


def _artifact_path(app: FastAPI, kind: Literal["backup", "export"]) -> Path:
    settings = runtime_of(app)["settings"]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    extension = ".dtwb" if kind == "backup" else ".dtw"
    return (
        settings.data_dir.expanduser().resolve()
        / "backups"
        / f"soulmate-{kind}-{timestamp}-{uuid4().hex[:8]}{extension}"
    )


def _delete_response(result: SourceDeletion, snapshot_version: int) -> SourceDeletionResponse:
    return SourceDeletionResponse(
        source_id=result.source_id,
        raw_event_count=result.raw_event_count,
        conversation_count=result.conversation_count,
        message_count=result.message_count,
        evidence_count=result.evidence_count,
        snapshot_version=snapshot_version,
    )


def build_data_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/data/sources", response_model=list[SourceResponse])
    def sources() -> list[SourceResponse]:
        records = runtime_of(app)["repositories"].sources.list_for_profile(DEFAULT_PROFILE_ID)
        return [
            _source_response(item) for item in records if item.source_type.startswith("import:")
        ]

    @router.post("/v1/data/imports", response_model=ImportResponse, status_code=201)
    def import_history(request: ImportRequest) -> ImportResponse:
        repositories = runtime_of(app)["repositories"]
        try:
            result = ChatImportService(repositories.sources).import_content(
                DEFAULT_PROFILE_ID,
                request.name,
                request.content,
                request.format,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _record_audit(
            app,
            "data.import",
            {
                "source_id": result.source.id,
                "format": result.detected_format.value,
                "conversation_count": result.conversation_count,
                "message_count": result.message_count,
            },
        )
        return _import_response(result)

    @router.delete("/v1/data/sources/{source_id}", response_model=SourceDeletionResponse)
    def delete_source(source_id: str) -> SourceDeletionResponse:
        repositories = runtime_of(app)["repositories"]
        result = ChatImportService(repositories.sources).delete_import(
            DEFAULT_PROFILE_ID, source_id
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Imported source was not found.")
        snapshot = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
            DEFAULT_PROFILE_ID
        )
        _record_audit(
            app,
            "data.source_delete",
            {
                "source_id": source_id,
                "raw_event_count": result.raw_event_count,
                "conversation_count": result.conversation_count,
                "message_count": result.message_count,
                "evidence_count": result.evidence_count,
                "snapshot_version": snapshot.version,
            },
        )
        return _delete_response(result, snapshot.version)

    @router.post("/v1/data/backups", response_model=ArchiveResponse, status_code=201)
    def create_backup() -> ArchiveResponse:
        runtime = runtime_of(app)
        try:
            result = ArchiveService(runtime["settings"], runtime["database"]).create(
                _artifact_path(app, "backup")
            )
        except (OSError, PortabilityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _record_audit(
            app,
            "data.backup",
            {"sha256": result.sha256, "size_bytes": result.size_bytes},
        )
        return _archive_response(result)

    @router.get("/v1/data/remote-backups/status", response_model=RemoteBackupStatusResponse)
    def remote_backup_status() -> RemoteBackupStatusResponse:
        runtime = runtime_of(app)
        settings = runtime["settings"].remote_backup
        return RemoteBackupStatusResponse(
            configured=runtime["remote_backup"] is not None,
            backend=settings.backend,
            automatic_daily=settings.automatic_daily,
            interval_hours=settings.interval_hours,
            last_success_at=parse_metadata_time(
                runtime["repositories"].system_metadata.get(LAST_REMOTE_BACKUP_AT)
            ),
        )

    @router.post("/v1/data/remote-backups", response_model=RemoteBackupResponse, status_code=201)
    def create_remote_backup() -> RemoteBackupResponse:
        try:
            result = _remote_backup_service(app).create_and_upload()
        except (OSError, PortabilityError, RemoteBackupError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _record_audit(
            app,
            "data.remote_backup",
            {
                "sha256": result.archive.sha256,
                "size_bytes": result.archive.size_bytes,
                "backend": runtime_of(app)["settings"].remote_backup.backend,
                "trigger": "manual",
            },
        )
        return _remote_backup_response(app, result)

    @router.post("/v1/data/remote-restores/latest", response_model=RestoreResponse, status_code=202)
    def prepare_latest_remote_restore() -> RestoreResponse:
        service = _remote_backup_service(app)
        try:
            downloaded = service.download_latest()
            revision = stage_restore(
                runtime_of(app)["settings"],
                downloaded.path.read_bytes(),
                service.passphrase,
            )
        except (OSError, PortabilityError, RemoteBackupError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _record_audit(
            app,
            "data.remote_restore_staged",
            {
                "source_schema_revision": revision,
                "backend": runtime_of(app)["settings"].remote_backup.backend,
            },
        )
        return RestoreResponse(
            staged=True,
            source_schema_revision=revision,
            restart_required=True,
        )

    @router.post("/v1/data/exports", response_model=ArchiveResponse, status_code=201)
    def create_export(request: ExportRequest) -> ArchiveResponse:
        runtime = runtime_of(app)
        try:
            result = ArchiveService(runtime["settings"], runtime["database"]).create(
                _artifact_path(app, "export"), passphrase=request.passphrase
            )
        except (OSError, PortabilityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _record_audit(
            app,
            "data.export",
            {"sha256": result.sha256, "size_bytes": result.size_bytes, "encrypted": True},
        )
        return _archive_response(result)

    @router.post("/v1/data/restores", response_model=RestoreResponse, status_code=202)
    def prepare_restore(request: RestoreRequest) -> RestoreResponse:
        try:
            payload = base64.b64decode(request.archive_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Restore archive encoding is invalid."
            ) from exc
        if len(payload) > MAX_RESTORE_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "Desktop restore archives must not exceed 64 MiB; "
                    "use the CLI for larger archives."
                ),
            )
        try:
            revision = stage_restore(runtime_of(app)["settings"], payload, request.passphrase)
        except (OSError, PortabilityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _record_audit(app, "data.restore_staged", {"source_schema_revision": revision})
        return RestoreResponse(staged=True, source_schema_revision=revision, restart_required=True)

    return router
