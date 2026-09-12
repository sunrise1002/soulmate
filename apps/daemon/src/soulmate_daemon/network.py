"""Local network binding rules for optional access from other devices."""

import socket
from dataclasses import dataclass
from pathlib import Path

from soulmate_daemon.config import UNSPECIFIED_BIND_ADDRESSES, Settings
from soulmate_daemon.tls import ServiceCertificate, ensure_service_certificate

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_ROUTE_PROBE_ADDRESS = ("198.51.100.1", 9)


class NetworkConfigurationError(ValueError):
    """LAN access was requested but cannot be configured safely."""


def is_loopback_client(host: str | None) -> bool:
    """Treat only real loopback peers as the owner of this installation."""
    if host is None:
        return False
    normalized = host.strip().strip("[]").lower()
    return normalized in LOOPBACK_HOSTS or normalized == "::ffff:127.0.0.1"


def detect_lan_address() -> str | None:
    """Report the local address used for the default route, if one exists."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(_ROUTE_PROBE_ADDRESS)
            address = probe.getsockname()[0]
        except OSError:
            return None
    return None if not isinstance(address, str) or is_loopback_client(address) else address


def resolve_lan_host(configured: str) -> str:
    """Return the explicit LAN address to bind, never a wildcard or loopback."""
    if configured:
        if configured in UNSPECIFIED_BIND_ADDRESSES:
            raise NetworkConfigurationError("LAN host must be an explicit address.")
        if is_loopback_client(configured):
            raise NetworkConfigurationError("LAN host must not be a loopback address.")
        return configured
    detected = detect_lan_address()
    if detected is None:
        raise NetworkConfigurationError("No local network address is available for LAN access.")
    return detected


@dataclass(frozen=True, slots=True)
class LanEndpoint:
    """Everything a paired device needs to reach this service over the LAN."""

    host: str
    port: int
    certificate: ServiceCertificate

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"https://{host}:{self.port}"

    @property
    def fingerprint(self) -> str:
        return self.certificate.fingerprint


def prepare_lan_endpoint(settings: Settings, *, tls_dir: Path | None = None) -> LanEndpoint:
    """Resolve the LAN address and ensure a certificate that covers it exists."""
    host = resolve_lan_host(settings.network.lan_host)
    certificate = ensure_service_certificate(
        tls_dir if tls_dir is not None else settings.tls_directory, (host,)
    )
    return LanEndpoint(host=host, port=settings.network.lan_port, certificate=certificate)
