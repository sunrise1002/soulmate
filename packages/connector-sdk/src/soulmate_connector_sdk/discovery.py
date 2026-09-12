"""Python entry-point discovery for independently packaged connectors."""

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points

from soulmate_connector_sdk.models import SourceConnector

ENTRY_POINT_GROUP = "soulmate.connectors"


@dataclass(frozen=True, slots=True)
class ConnectorLoadFailure:
    entry_point: str
    error_type: str


@dataclass(frozen=True, slots=True)
class ConnectorCatalog:
    connectors: dict[str, SourceConnector]
    failures: tuple[ConnectorLoadFailure, ...] = ()

    def get(self, connector_id: str) -> SourceConnector | None:
        return self.connectors.get(connector_id)


def _connector_from_loaded(value: object) -> SourceConnector:
    candidate = value() if isinstance(value, type) else value
    manifest = getattr(candidate, "manifest", None)
    sync = getattr(candidate, "sync", None)
    if manifest is None or not callable(sync):
        raise TypeError("Connector entry point does not expose the SDK contract.")
    return candidate  # type: ignore[return-value]


def discover_connectors(additional: Iterable[SourceConnector] = ()) -> ConnectorCatalog:
    """Load installed connector entry points without failing daemon startup."""
    discovered: dict[str, SourceConnector] = {}
    failures: list[ConnectorLoadFailure] = []
    for connector in additional:
        connector_id = connector.manifest.connector_id
        if connector_id in discovered:
            raise ValueError(f"Duplicate connector ID: {connector_id}")
        discovered[connector_id] = connector
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            connector = _connector_from_loaded(entry_point.load())
            connector_id = connector.manifest.connector_id
            if connector_id in discovered:
                raise ValueError(f"Duplicate connector ID: {connector_id}")
            discovered[connector_id] = connector
        except Exception as exc:
            failures.append(ConnectorLoadFailure(entry_point.name, type(exc).__name__))
    return ConnectorCatalog(discovered, tuple(failures))
