"""Connector orchestration, consent enforcement, egress, and RawEvent ingestion."""

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import NoReturn
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from soulmate_connector_sdk import (
    ConnectorCatalog,
    ConnectorContext,
    ConnectorManifest,
    ConnectorNetworkClient,
    ConnectorPermission,
    ConnectorRegistration,
    ConnectorRegistrationRepository,
    ConnectorRemoval,
    ConnectorSyncRequest,
    ConnectorSyncResult,
    ConnectorSyncStatus,
    NetworkResponse,
    PersistedConnectorEvent,
    StoredSyncResult,
)
from soulmate_core.domain import AuditEvent, AuditEventRepository, Job, JobRepository, JobStatus
from soulmate_llm_providers import EgressDeniedError, EgressPolicy, PrivacyMode

CONNECTOR_SYNC_JOB = "connector_sync"
MAX_NETWORK_RESPONSE_BYTES = 5 * 1024 * 1024


class ConnectorError(Exception):
    """A safe owner-visible connector operation error."""


class ConnectorSyncError(Exception):
    """A sanitized synchronization failure recorded without private values."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def credential_environment_name(connector_id: str, key: str) -> str:
    """Return a stable environment key without embedding secret material."""

    def normalize(value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "_", value.upper())

    return f"DECISION_TWIN_CONNECTOR__{normalize(connector_id)}__{normalize(key)}"


class ConnectorHttpClient(ConnectorNetworkClient):
    """Bounded HTTP client enforcing manifest hosts and the central privacy policy."""

    def __init__(self, manifest: ConnectorManifest, privacy_mode: PrivacyMode) -> None:
        self._manifest = manifest
        self._privacy_mode = privacy_mode

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> NetworkResponse:
        if ConnectorPermission.NETWORK_ACCESS not in self._manifest.permissions:
            raise EgressDeniedError("The connector did not declare network access.")
        parsed = urlparse(url)
        hostname = "" if parsed.hostname is None else parsed.hostname.casefold()
        allowed = {item.casefold() for item in self._manifest.network_hosts}
        if hostname not in allowed:
            raise EgressDeniedError("The connector endpoint is outside its declared hosts.")
        if self._privacy_mode == "offline":
            raise EgressDeniedError("Offline mode denied connector network access.")
        EgressPolicy(self._privacy_mode).require(
            provider=f"connector:{self._manifest.connector_id}",
            endpoint=url,
            data_classification="personal",
        )
        async with (
            httpx.AsyncClient(follow_redirects=False, timeout=30) as client,
            client.stream(method, url, headers=headers, content=body) as response,
        ):
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_NETWORK_RESPONSE_BYTES:
                    raise ConnectorError("Connector network responses must not exceed 5 MiB.")
                chunks.append(chunk)
            return NetworkResponse(response.status_code, dict(response.headers), b"".join(chunks))


class ConnectorService:
    """Keep optional plugins outside the kernel and behind explicit owner consent."""

    def __init__(
        self,
        registrations: ConnectorRegistrationRepository,
        jobs: JobRepository,
        audits: AuditEventRepository,
        catalog: ConnectorCatalog,
        *,
        privacy_mode: PrivacyMode,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._registrations = registrations
        self._jobs = jobs
        self._audits = audits
        self._catalog = catalog
        self._privacy_mode = privacy_mode
        self._environ = os.environ if environ is None else environ

    def register(
        self,
        profile_id: str,
        connector_id: str,
        name: str | None,
        permissions: tuple[ConnectorPermission, ...],
        configuration: dict[str, object],
        now: datetime | None = None,
    ) -> ConnectorRegistration:
        connector = self._catalog.get(connector_id)
        if connector is None:
            raise ConnectorError("The connector is not installed or failed to load.")
        if self._registrations.get(profile_id, connector_id) is not None:
            raise ConnectorError("The connector is already configured.")
        granted = tuple(sorted(set(permissions), key=str))
        if len(set(permissions)) != len(permissions) or granted != connector.manifest.permissions:
            raise ConnectorError("All and only the connector's declared permissions are required.")
        secret_keys = {item.key.casefold() for item in connector.manifest.credentials}
        if any(key.casefold() in secret_keys for key in configuration):
            raise ConnectorError("Connector credentials must not be stored in configuration.")
        created_at = datetime.now(UTC) if now is None else now
        registration = ConnectorRegistration(
            id=f"connector_registration_{uuid4().hex}",
            profile_id=profile_id,
            connector_id=connector_id,
            name=(name or connector.manifest.name).strip(),
            source_id=f"source_{uuid4().hex}",
            enabled=True,
            granted_permissions=granted,
            configuration=configuration,
            cursor=None,
            sync_status=ConnectorSyncStatus.NEVER,
            created_at=created_at,
            updated_at=created_at,
        )
        self._registrations.add(registration)
        self._audit(
            profile_id,
            "connector.register",
            {"connector_id": connector_id, "permissions": [item.value for item in granted]},
            created_at,
        )
        return registration

    def set_enabled(
        self, profile_id: str, connector_id: str, enabled: bool, now: datetime | None = None
    ) -> ConnectorRegistration:
        updated_at = datetime.now(UTC) if now is None else now
        if not self._registrations.set_enabled(profile_id, connector_id, enabled, updated_at):
            raise ConnectorError("The connector registration was not found.")
        self._audit(
            profile_id,
            "connector.enable" if enabled else "connector.disable",
            {"connector_id": connector_id},
            updated_at,
        )
        registration = self._registrations.get(profile_id, connector_id)
        if registration is None:
            raise RuntimeError("Updated connector registration disappeared.")
        return registration

    def enqueue_sync(self, profile_id: str, connector_id: str, now: datetime | None = None) -> Job:
        registration = self._registrations.get(profile_id, connector_id)
        if registration is None:
            raise ConnectorError("The connector registration was not found.")
        if not registration.enabled:
            raise ConnectorError("The connector is disabled.")
        if self._catalog.get(connector_id) is None:
            raise ConnectorError("The connector is not installed or failed to load.")
        created_at = datetime.now(UTC) if now is None else now
        job = Job(
            id=f"job_{uuid4().hex}",
            job_type=CONNECTOR_SYNC_JOB,
            payload={"profile_id": profile_id, "connector_id": connector_id},
            status=JobStatus.QUEUED,
            attempts=0,
            max_attempts=3,
            available_at=created_at,
            created_at=created_at,
            updated_at=created_at,
        )
        self._jobs.enqueue(job)
        self._audit(
            profile_id,
            "connector.sync_enqueue",
            {"connector_id": connector_id, "job_id": job.id},
            created_at,
        )
        return job

    async def sync(self, profile_id: str, connector_id: str) -> StoredSyncResult:
        registration = self._registrations.get(profile_id, connector_id)
        connector = self._catalog.get(connector_id)
        if registration is None or connector is None:
            self._fail(registration, "connector_unavailable")
        now = datetime.now(UTC)
        if not self._registrations.mark_running(registration.id, now):
            self._fail(registration, "connector_disabled")
        if registration.granted_permissions != connector.manifest.permissions:
            self._fail(registration, "permissions_changed")
        credentials: dict[str, str] = {}
        for requirement in connector.manifest.credentials:
            value = self._environ.get(
                credential_environment_name(connector_id, requirement.key), ""
            )
            if requirement.required and not value:
                self._fail(registration, "credentials_missing")
            if value:
                credentials[requirement.key] = value
        try:
            result = await connector.sync(
                ConnectorSyncRequest(registration.configuration, registration.cursor),
                ConnectorContext(
                    credentials=credentials,
                    network=ConnectorHttpClient(connector.manifest, self._privacy_mode),
                ),
            )
            if not isinstance(result, ConnectorSyncResult):
                raise TypeError("Connector returned an invalid result type.")
            completed_at = datetime.now(UTC)
            stored = self._registrations.apply_sync(
                registration.id,
                tuple(
                    PersistedConnectorEvent(
                        raw_event_id=f"event_{uuid4().hex}",
                        external_id=item.external_id,
                        event_type=item.event_type,
                        content=item.content,
                        created_at=item.created_at,
                        ingested_at=completed_at,
                        sensitivity=item.sensitivity,
                    )
                    for item in result.events
                ),
                result.cursor,
                completed_at,
            )
        except ConnectorSyncError:
            raise
        except EgressDeniedError as exc:
            self._fail(registration, "egress_denied", cause=exc)
        except Exception as exc:
            self._fail(registration, "sync_failed", cause=exc)
        self._audit(
            profile_id,
            "connector.sync_complete",
            {
                "connector_id": connector_id,
                "accepted_count": stored.accepted_count,
                "duplicate_count": stored.duplicate_count,
            },
            completed_at,
            actor_type="connector",
            actor_id=registration.id,
        )
        return stored

    def remove(
        self, profile_id: str, connector_id: str, now: datetime | None = None
    ) -> ConnectorRemoval:
        removed = self._registrations.remove(profile_id, connector_id)
        if removed is None:
            raise ConnectorError("The connector registration was not found.")
        self._audit(
            profile_id,
            "connector.remove",
            {
                "connector_id": connector_id,
                "raw_event_count": removed.raw_event_count,
                "evidence_count": removed.evidence_count,
            },
            datetime.now(UTC) if now is None else now,
        )
        return removed

    def credential_status(self, manifest: ConnectorManifest) -> dict[str, bool]:
        return {
            requirement.key: bool(
                self._environ.get(
                    credential_environment_name(manifest.connector_id, requirement.key), ""
                )
            )
            for requirement in manifest.credentials
        }

    def _fail(
        self,
        registration: ConnectorRegistration | None,
        code: str,
        *,
        cause: Exception | None = None,
    ) -> NoReturn:
        now = datetime.now(UTC)
        if registration is not None:
            self._registrations.mark_failed(registration.id, code, now)
            self._audit(
                registration.profile_id,
                "connector.sync_failed",
                {"connector_id": registration.connector_id, "error_code": code},
                now,
                actor_type="connector",
                actor_id=registration.id,
            )
        error = ConnectorSyncError(code)
        if cause is None:
            raise error
        raise error from cause

    def _audit(
        self,
        profile_id: str,
        action: str,
        metadata: dict[str, object],
        created_at: datetime,
        *,
        actor_type: str = "owner",
        actor_id: str | None = None,
    ) -> None:
        self._audits.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                profile_id=profile_id,
                action=action,
                actor_type=actor_type,
                actor_id=actor_id,
                metadata=metadata,
                created_at=created_at,
            )
        )
