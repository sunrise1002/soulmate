"""Stable contracts for optional Soulmate source connectors."""

from soulmate_connector_sdk.discovery import (
    ENTRY_POINT_GROUP,
    ConnectorCatalog,
    ConnectorLoadFailure,
    discover_connectors,
)
from soulmate_connector_sdk.models import (
    ConnectorContext,
    ConnectorCredential,
    ConnectorEvent,
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
    SourceConnector,
    StoredSyncResult,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "ConnectorCatalog",
    "ConnectorContext",
    "ConnectorCredential",
    "ConnectorEvent",
    "ConnectorLoadFailure",
    "ConnectorManifest",
    "ConnectorNetworkClient",
    "ConnectorPermission",
    "ConnectorRegistration",
    "ConnectorRegistrationRepository",
    "ConnectorRemoval",
    "ConnectorSyncRequest",
    "ConnectorSyncResult",
    "ConnectorSyncStatus",
    "NetworkResponse",
    "PersistedConnectorEvent",
    "SourceConnector",
    "StoredSyncResult",
    "discover_connectors",
]
