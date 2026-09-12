"""Infrastructure-neutral connector declarations and synchronization records."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

CONNECTOR_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
MAX_EVENT_CONTENT_BYTES = 2 * 1024 * 1024


def _require_utc_aware(value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Connector timestamps must be timezone-aware.")


def _json_size(value: object) -> int:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("Connector values must be JSON serializable.") from exc
    return len(encoded)


class ConnectorPermission(StrEnum):
    """Owner-visible capabilities a connector must explicitly request."""

    DATA_READ = "data:read"
    NETWORK_ACCESS = "network:access"
    CREDENTIALS_READ = "credentials:read"
    LEARNING_INGEST = "learning:ingest"


class ConnectorSyncStatus(StrEnum):
    """Persisted state of the latest synchronization attempt."""

    NEVER = "never"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConnectorCredential:
    """One secret a connector expects from the process environment."""

    key: str
    label: str
    required: bool = True

    def __post_init__(self) -> None:
        if not self.key or not self.key.replace("_", "").isalnum() or not self.label.strip():
            raise ValueError("Connector credential keys and labels must contain text.")


@dataclass(frozen=True, slots=True)
class ConnectorManifest:
    """Static identity and complete permission declaration for a connector."""

    connector_id: str
    name: str
    version: str
    description: str
    permissions: tuple[ConnectorPermission, ...]
    data_access: tuple[str, ...]
    network_hosts: tuple[str, ...] = ()
    credentials: tuple[ConnectorCredential, ...] = ()
    learning_mode: str = "raw_events"

    def __post_init__(self) -> None:
        if not CONNECTOR_ID_PATTERN.fullmatch(self.connector_id):
            raise ValueError("Connector ID must be a namespaced lowercase identifier.")
        if any(not value.strip() for value in (self.name, self.version, self.description)):
            raise ValueError("Connector name, version, and description must contain text.")
        if not self.data_access or any(not item.strip() for item in self.data_access):
            raise ValueError("A connector must declare the data it reads.")
        if self.learning_mode != "raw_events":
            raise ValueError("Connectors may currently learn only by emitting RawEvents.")
        normalized = tuple(sorted(set(self.permissions), key=str))
        if normalized != self.permissions:
            raise ValueError("Connector permissions must be unique and sorted.")
        required = {
            ConnectorPermission.DATA_READ,
            ConnectorPermission.LEARNING_INGEST,
        }
        if self.network_hosts:
            required.add(ConnectorPermission.NETWORK_ACCESS)
        if self.credentials:
            required.add(ConnectorPermission.CREDENTIALS_READ)
        if set(self.permissions) != required:
            raise ValueError("Connector permissions must exactly match its declared capabilities.")
        if any(not host.strip() or "://" in host or "/" in host for host in self.network_hosts):
            raise ValueError("Connector network hosts must be bare host names.")
        credential_keys = tuple(item.key for item in self.credentials)
        if len(set(credential_keys)) != len(credential_keys):
            raise ValueError("Connector credential keys must be unique.")


@dataclass(frozen=True, slots=True)
class ConnectorEvent:
    """A validated external item that the daemon will envelope as one RawEvent."""

    external_id: str
    event_type: str
    content: dict[str, object]
    created_at: datetime
    sensitivity: str = "normal"

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        if not self.external_id.strip() or len(self.external_id) > 500:
            raise ValueError("Connector event external IDs must contain at most 500 characters.")
        if not self.event_type.strip() or len(self.event_type) > 200:
            raise ValueError("Connector event types must contain at most 200 characters.")
        if self.sensitivity not in {"normal", "sensitive", "highly_sensitive"}:
            raise ValueError("Connector event sensitivity is invalid.")
        if _json_size(self.content) > MAX_EVENT_CONTENT_BYTES:
            raise ValueError("A connector event must not exceed 2 MiB.")


@dataclass(frozen=True, slots=True)
class ConnectorSyncRequest:
    configuration: Mapping[str, object]
    cursor: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class ConnectorSyncResult:
    events: tuple[ConnectorEvent, ...]
    cursor: dict[str, object] | None

    def __post_init__(self) -> None:
        if len(self.events) > 10_000:
            raise ValueError("A connector sync must not emit more than 10,000 events.")
        if self.cursor is not None and _json_size(self.cursor) > 64 * 1024:
            raise ValueError("A connector cursor must not exceed 64 KiB.")


@dataclass(frozen=True, slots=True)
class NetworkResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class ConnectorNetworkClient(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> NetworkResponse: ...


@dataclass(frozen=True, slots=True)
class ConnectorContext:
    credentials: Mapping[str, str]
    network: ConnectorNetworkClient


class SourceConnector(Protocol):
    manifest: ConnectorManifest

    async def sync(
        self, request: ConnectorSyncRequest, context: ConnectorContext
    ) -> ConnectorSyncResult: ...


@dataclass(frozen=True, slots=True)
class ConnectorRegistration:
    id: str
    profile_id: str
    connector_id: str
    name: str
    source_id: str
    enabled: bool
    granted_permissions: tuple[ConnectorPermission, ...]
    configuration: dict[str, object]
    cursor: dict[str, object] | None
    sync_status: ConnectorSyncStatus
    created_at: datetime
    updated_at: datetime
    last_sync_at: datetime | None = None
    last_error_code: str | None = None

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        _require_utc_aware(self.updated_at)
        _require_utc_aware(self.last_sync_at)
        if not self.id or not self.profile_id or not self.source_id or not self.name.strip():
            raise ValueError("Connector registration identity fields must contain text.")
        if not CONNECTOR_ID_PATTERN.fullmatch(self.connector_id):
            raise ValueError("Connector registration has an invalid connector ID.")
        if tuple(sorted(set(self.granted_permissions), key=str)) != self.granted_permissions:
            raise ValueError("Granted connector permissions must be unique and sorted.")
        _json_size(self.configuration)
        if self.cursor is not None:
            _json_size(self.cursor)


@dataclass(frozen=True, slots=True)
class PersistedConnectorEvent:
    raw_event_id: str
    external_id: str
    event_type: str
    content: dict[str, object]
    created_at: datetime
    ingested_at: datetime
    sensitivity: str

    def __post_init__(self) -> None:
        _require_utc_aware(self.created_at)
        _require_utc_aware(self.ingested_at)


@dataclass(frozen=True, slots=True)
class StoredSyncResult:
    accepted_count: int
    duplicate_count: int


@dataclass(frozen=True, slots=True)
class ConnectorRemoval:
    connector_id: str
    source_id: str
    raw_event_count: int
    evidence_count: int


class ConnectorRegistrationRepository(Protocol):
    def add(self, registration: ConnectorRegistration) -> None: ...

    def get(self, profile_id: str, connector_id: str) -> ConnectorRegistration | None: ...

    def list_for_profile(self, profile_id: str) -> tuple[ConnectorRegistration, ...]: ...

    def set_enabled(
        self, profile_id: str, connector_id: str, enabled: bool, updated_at: datetime
    ) -> bool: ...

    def mark_running(self, registration_id: str, updated_at: datetime) -> bool: ...

    def apply_sync(
        self,
        registration_id: str,
        events: tuple[PersistedConnectorEvent, ...],
        cursor: dict[str, object] | None,
        completed_at: datetime,
    ) -> StoredSyncResult: ...

    def mark_failed(self, registration_id: str, error_code: str, failed_at: datetime) -> None: ...

    def remove(self, profile_id: str, connector_id: str) -> ConnectorRemoval | None: ...
