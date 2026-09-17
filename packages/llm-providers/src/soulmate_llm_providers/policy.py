"""Central privacy boundary for model-provider network egress."""

import ipaddress
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

PrivacyMode = Literal["strict_local", "hybrid", "offline"]

MODEL_ARTIFACT_CLASSIFICATION = "model_artifact"
"""An owner-initiated download of a pinned model file; it carries no personal data."""


class EgressDeniedError(PermissionError):
    """The configured privacy policy denied a provider request."""


def _is_loopback(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    mode: PrivacyMode

    def can_send(self, *, provider: str, endpoint: str, data_classification: str) -> bool:
        """Return whether a provider may receive the classified payload."""
        del provider
        parsed = urlparse(endpoint)
        local = _is_loopback(parsed.hostname)
        if parsed.scheme not in {"http", "https"}:
            return False
        if data_classification == MODEL_ARTIFACT_CLASSIFICATION:
            # Nothing personal leaves the device, so only offline mode refuses a
            # download the owner started; the endpoint still needs transport security.
            return self.mode != "offline" and (local or parsed.scheme == "https")
        if self.mode in {"strict_local", "offline"}:
            return local
        return local or parsed.scheme == "https"

    def require(self, *, provider: str, endpoint: str, data_classification: str) -> None:
        if not self.can_send(
            provider=provider, endpoint=endpoint, data_classification=data_classification
        ):
            raise EgressDeniedError("Provider request denied by the configured privacy policy.")
