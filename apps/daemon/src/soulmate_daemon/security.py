"""Single authorization boundary for owner, paired device, and public access."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from soulmate_core.access import PairingError
from soulmate_core.domain import PairedDevice

from soulmate_daemon.network import is_loopback_client

BEARER_PREFIX = "Bearer "
API_PREFIX = "/v1"


class Requirement(StrEnum):
    """How much authority a request path needs."""

    PUBLIC = "public"
    DEVICE = "device"
    OWNER = "owner"


class ActorKind(StrEnum):
    """Who the authorization boundary believes is calling."""

    OWNER = "owner"
    DEVICE = "device"
    ANONYMOUS = "anonymous"


OWNER_ONLY_RULES: tuple[tuple[str | None, str], ...] = (
    ("POST", "/v1/pairing/start"),
    (None, "/v1/devices"),
    (None, "/v1/network"),
    ("DELETE", "/v1/evidence"),
)

PUBLIC_RULES: tuple[tuple[str | None, str], ...] = (
    ("GET", "/v1/health"),
    ("POST", "/v1/pairing/complete"),
)


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated caller attached to a request."""

    kind: ActorKind
    device_id: str | None = None
    device_name: str | None = None

    @property
    def is_owner(self) -> bool:
        return self.kind is ActorKind.OWNER


class AccessDeniedError(Exception):
    """A request failed the authorization boundary."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _matches(rules: tuple[tuple[str | None, str], ...], method: str, path: str) -> bool:
    return any(
        (rule_method is None or rule_method == method)
        and (path == rule_path or path.startswith(f"{rule_path}/"))
        for rule_method, rule_path in rules
    )


def path_requirement(method: str, path: str) -> Requirement:
    """Classify a request path; anything outside the API is the web client."""
    if not path.startswith(API_PREFIX):
        return Requirement.PUBLIC
    if _matches(OWNER_ONLY_RULES, method, path):
        return Requirement.OWNER
    if _matches(PUBLIC_RULES, method, path):
        return Requirement.PUBLIC
    return Requirement.DEVICE


def bearer_credential(header: str | None) -> str | None:
    if header is None or not header.startswith(BEARER_PREFIX):
        return None
    credential = header.removeprefix(BEARER_PREFIX).strip()
    return credential or None


def authorize(
    *,
    method: str,
    path: str,
    client_host: str | None,
    lan_enabled: bool,
    authorization: str | None,
    authenticate: Callable[[str], PairedDevice],
) -> Actor:
    """Authorize one request and return the actor the handlers may trust.

    Loopback callers are the owner. Every other caller needs LAN access enabled
    and a valid device credential, and can never reach owner-only paths.
    """
    if is_loopback_client(client_host):
        return Actor(kind=ActorKind.OWNER)
    if not lan_enabled:
        raise AccessDeniedError(403, "Access from other devices is disabled.")
    requirement = path_requirement(method, path)
    if requirement is Requirement.OWNER:
        raise AccessDeniedError(403, "This action is only available on the owner's device.")
    credential = bearer_credential(authorization)
    if credential is None:
        if requirement is Requirement.PUBLIC:
            return Actor(kind=ActorKind.ANONYMOUS)
        raise AccessDeniedError(401, "A paired device credential is required.")
    try:
        device = authenticate(credential)
    except PairingError as exc:
        raise AccessDeniedError(401, "A paired device credential is required.") from exc
    return Actor(kind=ActorKind.DEVICE, device_id=device.id, device_name=device.name)
