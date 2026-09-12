"""Owner-only HTTP lifecycle for optional connector plugins."""

import json
from datetime import datetime

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from soulmate_connector_sdk import (
    ConnectorCredential,
    ConnectorManifest,
    ConnectorPermission,
    ConnectorRegistration,
)
from soulmate_core.domain import Job
from soulmate_core.preferences import ModelRebuilder
from sqlalchemy.exc import IntegrityError

from soulmate_daemon.connectors import ConnectorError, ConnectorService
from soulmate_daemon.runtime import runtime_of
from soulmate_daemon.system import DEFAULT_PROFILE_ID

MAX_CONFIGURATION_BYTES = 64 * 1024


class CredentialDeclarationResponse(BaseModel):
    key: str
    label: str
    required: bool
    available: bool


class ConnectorManifestResponse(BaseModel):
    connector_id: str
    name: str
    version: str
    description: str
    permissions: tuple[str, ...]
    data_access: tuple[str, ...]
    network_hosts: tuple[str, ...]
    credentials: tuple[CredentialDeclarationResponse, ...]
    learning_mode: str
    configured: bool


class ConnectorRegistrationResponse(BaseModel):
    connector_id: str
    name: str
    enabled: bool
    granted_permissions: tuple[str, ...]
    configuration: dict[str, object]
    sync_status: str
    last_sync_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class ConnectorRegisterRequest(BaseModel):
    connector_id: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    permissions: tuple[ConnectorPermission, ...]
    configuration: dict[str, object] = Field(default_factory=dict)

    @field_validator("configuration")
    @classmethod
    def configuration_must_be_bounded(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("Connector configuration must be JSON serializable.") from exc
        if len(encoded) > MAX_CONFIGURATION_BYTES:
            raise ValueError("Connector configuration must not exceed 64 KiB.")
        return value


class ConnectorEnabledRequest(BaseModel):
    enabled: bool


class ConnectorSyncResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime


class ConnectorSyncStatusResponse(BaseModel):
    job_id: str
    status: str
    attempts: int
    max_attempts: int
    error: str | None
    updated_at: datetime


class ConnectorRemovalResponse(BaseModel):
    connector_id: str
    source_id: str
    raw_event_count: int
    evidence_count: int
    snapshot_version: int


def _service(app: FastAPI) -> ConnectorService:
    runtime = runtime_of(app)
    return ConnectorService(
        runtime["repositories"].connector_registrations,
        runtime["repositories"].jobs,
        runtime["repositories"].audit_events,
        runtime["connector_catalog"],
        privacy_mode=runtime["settings"].privacy.mode,
    )


def _credential_response(
    credential: ConnectorCredential, status: dict[str, bool]
) -> CredentialDeclarationResponse:
    return CredentialDeclarationResponse(
        key=credential.key,
        label=credential.label,
        required=credential.required,
        available=status.get(credential.key, False),
    )


def _manifest_response(
    manifest: ConnectorManifest, service: ConnectorService, *, configured: bool
) -> ConnectorManifestResponse:
    status = service.credential_status(manifest)
    return ConnectorManifestResponse(
        connector_id=manifest.connector_id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        permissions=tuple(item.value for item in manifest.permissions),
        data_access=manifest.data_access,
        network_hosts=manifest.network_hosts,
        credentials=tuple(_credential_response(item, status) for item in manifest.credentials),
        learning_mode=manifest.learning_mode,
        configured=configured,
    )


def _registration_response(
    registration: ConnectorRegistration,
) -> ConnectorRegistrationResponse:
    return ConnectorRegistrationResponse(
        connector_id=registration.connector_id,
        name=registration.name,
        enabled=registration.enabled,
        granted_permissions=tuple(item.value for item in registration.granted_permissions),
        configuration=registration.configuration,
        sync_status=registration.sync_status.value,
        last_sync_at=registration.last_sync_at,
        last_error_code=registration.last_error_code,
        created_at=registration.created_at,
        updated_at=registration.updated_at,
    )


def _sync_response(job: Job) -> ConnectorSyncResponse:
    return ConnectorSyncResponse(job_id=job.id, status=job.status.value, created_at=job.created_at)


def build_connector_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/connectors/catalog", response_model=list[ConnectorManifestResponse])
    def catalog() -> list[ConnectorManifestResponse]:
        runtime = runtime_of(app)
        service = _service(app)
        configured = {
            item.connector_id
            for item in runtime["repositories"].connector_registrations.list_for_profile(
                DEFAULT_PROFILE_ID
            )
        }
        return [
            _manifest_response(manifest, service, configured=connector_id in configured)
            for connector_id, connector in sorted(runtime["connector_catalog"].connectors.items())
            for manifest in (connector.manifest,)
        ]

    @router.get("/v1/connectors", response_model=list[ConnectorRegistrationResponse])
    def registrations() -> list[ConnectorRegistrationResponse]:
        records = runtime_of(app)["repositories"].connector_registrations.list_for_profile(
            DEFAULT_PROFILE_ID
        )
        return [_registration_response(item) for item in records]

    @router.post("/v1/connectors", response_model=ConnectorRegistrationResponse, status_code=201)
    def register(request: ConnectorRegisterRequest) -> ConnectorRegistrationResponse:
        try:
            registration = _service(app).register(
                DEFAULT_PROFILE_ID,
                request.connector_id,
                request.name,
                request.permissions,
                request.configuration,
            )
        except (ConnectorError, IntegrityError, ValueError) as exc:
            if isinstance(exc, IntegrityError):
                detail = "The connector is already configured."
            else:
                detail = str(exc)
            raise HTTPException(status_code=409, detail=detail) from exc
        return _registration_response(registration)

    @router.patch("/v1/connectors/{connector_id}", response_model=ConnectorRegistrationResponse)
    def set_enabled(
        connector_id: str, request: ConnectorEnabledRequest
    ) -> ConnectorRegistrationResponse:
        try:
            registration = _service(app).set_enabled(
                DEFAULT_PROFILE_ID, connector_id, request.enabled
            )
        except ConnectorError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _registration_response(registration)

    @router.post(
        "/v1/connectors/{connector_id}/sync",
        response_model=ConnectorSyncResponse,
        status_code=202,
    )
    def sync(connector_id: str) -> ConnectorSyncResponse:
        try:
            job = _service(app).enqueue_sync(DEFAULT_PROFILE_ID, connector_id)
        except ConnectorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _sync_response(job)

    @router.get("/v1/connectors/syncs/{job_id}", response_model=ConnectorSyncStatusResponse)
    def sync_status(job_id: str) -> ConnectorSyncStatusResponse:
        job = runtime_of(app)["repositories"].jobs.get(job_id)
        if job is None or job.job_type != "connector_sync":
            raise HTTPException(status_code=404, detail="Connector sync was not found.")
        return ConnectorSyncStatusResponse(
            job_id=job.id,
            status=job.status.value,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            error=None if job.last_error is None else "Connector synchronization failed.",
            updated_at=job.updated_at,
        )

    @router.delete("/v1/connectors/{connector_id}", response_model=ConnectorRemovalResponse)
    def remove(connector_id: str) -> ConnectorRemovalResponse:
        try:
            result = _service(app).remove(DEFAULT_PROFILE_ID, connector_id)
        except ConnectorError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        repositories = runtime_of(app)["repositories"]
        snapshot = ModelRebuilder(repositories.evidence, repositories.personal_models).rebuild(
            DEFAULT_PROFILE_ID
        )
        return ConnectorRemovalResponse(
            connector_id=result.connector_id,
            source_id=result.source_id,
            raw_event_count=result.raw_event_count,
            evidence_count=result.evidence_count,
            snapshot_version=snapshot.version,
        )

    return router
