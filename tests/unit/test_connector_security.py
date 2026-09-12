"""Verify connector consent, credential, and network privacy boundaries."""

import asyncio

import pytest
from soulmate_connector_sdk import (
    ConnectorCredential,
    ConnectorManifest,
    ConnectorPermission,
)
from soulmate_daemon.connectors import ConnectorHttpClient, credential_environment_name
from soulmate_llm_providers import EgressDeniedError


def _network_manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector_id="example.remote",
        name="Remote example",
        version="1.0.0",
        description="Synthetic remote connector.",
        permissions=(
            ConnectorPermission.CREDENTIALS_READ,
            ConnectorPermission.DATA_READ,
            ConnectorPermission.LEARNING_INGEST,
            ConnectorPermission.NETWORK_ACCESS,
        ),
        data_access=("Synthetic records",),
        network_hosts=("api.example.test",),
        credentials=(ConnectorCredential("token", "API token"),),
    )


def test_connector_credentials_have_stable_separate_environment_names() -> None:
    assert (
        credential_environment_name("example.remote", "api_token")
        == "DECISION_TWIN_CONNECTOR__EXAMPLE_REMOTE__API_TOKEN"
    )


def test_network_client_rejects_undeclared_hosts_before_any_request() -> None:
    client = ConnectorHttpClient(_network_manifest(), "hybrid")
    with pytest.raises(EgressDeniedError, match="declared hosts"):
        asyncio.run(client.request("GET", "https://other.example.test/private"))


def test_offline_mode_rejects_even_declared_connector_network_access() -> None:
    client = ConnectorHttpClient(_network_manifest(), "offline")
    with pytest.raises(EgressDeniedError, match="Offline mode"):
        asyncio.run(client.request("GET", "https://api.example.test/private"))
