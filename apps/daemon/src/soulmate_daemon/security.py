"""Single authorization boundary for owner, paired device, and public access."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from soulmate_core.access import (
    AGENT_DELEGATE,
    DECISION_PREDICT,
    DECISION_RECORD,
    MODEL_SUMMARY_READ,
    OUTCOME_RECORD,
    PREFERENCE_SUMMARY_READ,
    ExternalAccessError,
    ExternalPrincipal,
    PairingError,
)
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
    SERVICE = "service"
    ANONYMOUS = "anonymous"


OWNER_ONLY_RULES: tuple[tuple[str | None, str], ...] = (
    ("POST", "/v1/pairing/start"),
    (None, "/v1/devices"),
    (None, "/v1/network"),
    ("DELETE", "/v1/evidence"),
    ("DELETE", "/v1/decisions"),
    (None, "/v1/service-identities"),
    (None, "/v1/audit/events"),
    (None, "/v1/data"),
    (None, "/v1/connectors"),
    (None, "/v1/delegation-policies"),
    (None, "/v1/delegation-requests"),
)

PUBLIC_RULES: tuple[tuple[str | None, str], ...] = (
    ("GET", "/v1/health"),
    ("POST", "/v1/pairing/complete"),
)

EXTERNAL_SCOPE_RULES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/v1/external/predict-choice", DECISION_PREDICT),
    ("POST", "/v1/external/rank-options", DECISION_PREDICT),
    ("GET", "/v1/external/preference-summary", PREFERENCE_SUMMARY_READ),
    ("GET", "/v1/external/model-summary", MODEL_SUMMARY_READ),
    ("POST", "/v1/external/find-similar-decisions", DECISION_PREDICT),
    ("POST", "/v1/external/record-decision", DECISION_RECORD),
    ("POST", "/v1/external/record-outcome", OUTCOME_RECORD),
)


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated caller attached to a request."""

    kind: ActorKind
    device_id: str | None = None
    device_name: str | None = None
    service_identity_id: str | None = None
    service_identity_name: str | None = None
    credential_id: str | None = None

    @property
    def is_owner(self) -> bool:
        return self.kind is ActorKind.OWNER


class AccessDeniedError(Exception):
    """A request failed the authorization boundary."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        service_identity_id: str | None = None,
        credential_id: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.service_identity_id = service_identity_id
        self.credential_id = credential_id


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


def external_scope(method: str, path: str) -> str | None:
    """Return the exact least-privilege scope for an external API operation."""
    delegation_path = "/v1/external/delegation-requests"
    if (method == "POST" and path == delegation_path) or (
        method in ("GET", "POST") and path.startswith(f"{delegation_path}/")
    ):
        return AGENT_DELEGATE
    return next(
        (
            scope
            for rule_method, rule_path, scope in EXTERNAL_SCOPE_RULES
            if method == rule_method and path == rule_path
        ),
        None,
    )


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
    authenticate_service: Callable[[str], ExternalPrincipal] | None = None,
) -> Actor:
    """Authorize one request and return the actor the handlers may trust.

    Loopback callers are the owner. Every other caller needs LAN access enabled
    and a valid device credential, and can never reach owner-only paths.
    """
    required_scope = external_scope(method, path)
    if path.startswith("/v1/external/"):
        if not is_loopback_client(client_host) and not lan_enabled:
            raise AccessDeniedError(403, "Access from other devices is disabled.")
        credential = bearer_credential(authorization)
        if credential is None or authenticate_service is None:
            raise AccessDeniedError(401, "An external service API key is required.")
        try:
            principal = authenticate_service(credential)
        except ExternalAccessError as exc:
            raise AccessDeniedError(401, "An external service API key is required.") from exc
        if required_scope is None:
            raise AccessDeniedError(
                404,
                "The external API operation was not found.",
                service_identity_id=principal.identity.id,
                credential_id=principal.credential.id,
            )
        if required_scope not in principal.identity.scopes:
            raise AccessDeniedError(
                403,
                f"The service identity lacks the '{required_scope}' scope.",
                service_identity_id=principal.identity.id,
                credential_id=principal.credential.id,
            )
        return Actor(
            kind=ActorKind.SERVICE,
            service_identity_id=principal.identity.id,
            service_identity_name=principal.identity.name,
            credential_id=principal.credential.id,
        )
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
