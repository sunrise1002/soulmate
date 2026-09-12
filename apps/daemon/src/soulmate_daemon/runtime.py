"""Shared runtime state and service construction for the daemon composition root."""

from typing import TypedDict, cast

from fastapi import FastAPI
from soulmate_core.access import DevicePairingService
from soulmate_llm_providers import LLMProvider
from soulmate_storage_sqlite import Database, Repositories

from soulmate_daemon.config import Settings
from soulmate_daemon.network import LanEndpoint
from soulmate_daemon.pairing import DeviceAccessService, pairing_token_ttl


class AppState(TypedDict):
    settings: Settings
    database: Database
    repositories: Repositories
    installation_id: str
    provider: LLMProvider | None
    lan: LanEndpoint | None
    lan_error: str | None


def runtime_of(app: FastAPI) -> AppState:
    return cast(AppState, app.state.runtime)


def build_access_service(runtime: AppState) -> DeviceAccessService:
    """Compose the pairing service from stored repositories and current settings."""
    repositories = runtime["repositories"]
    return DeviceAccessService(
        DevicePairingService(
            repositories.pairing_tokens,
            repositories.paired_devices,
            ttl=pairing_token_ttl(runtime["settings"].network.pairing_ttl_seconds),
        ),
        repositories.audit_events,
        service_id=runtime["installation_id"],
    )
