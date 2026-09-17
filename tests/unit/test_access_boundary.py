"""Verify the authorization boundary between the owner and paired devices."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from soulmate_core.access import ExternalAccessError, ExternalPrincipal, PairingError
from soulmate_core.domain import ApiCredential, PairedDevice, ServiceIdentity
from soulmate_daemon.network import (
    NetworkConfigurationError,
    is_loopback_client,
    resolve_lan_host,
)
from soulmate_daemon.security import (
    AccessDeniedError,
    Actor,
    ActorKind,
    Requirement,
    authorize,
    bearer_credential,
    path_requirement,
)

NOW = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
DEVICE = PairedDevice(
    id="device_1",
    profile_id="profile_default",
    name="Phone",
    platform="ios",
    credential_hash="a" * 64,
    created_at=NOW,
)
SERVICE_IDENTITY = ServiceIdentity(
    id="service_1",
    profile_id="profile_default",
    name="Shopping agent",
    description=None,
    scopes=("decision:predict",),
    created_at=NOW,
)
API_CREDENTIAL = ApiCredential(
    id="credential_1",
    service_identity_id=SERVICE_IDENTITY.id,
    secret_hash="b" * 64,
    created_at=NOW,
)
REMOTE = "192.168.1.50"


def _accept(_credential: str) -> PairedDevice:
    return DEVICE


def _reject(_credential: str) -> PairedDevice:
    raise PairingError("Device credential is not recognized.")


def _accept_service(_credential: str) -> ExternalPrincipal:
    return ExternalPrincipal(SERVICE_IDENTITY, API_CREDENTIAL)


def _reject_service(_credential: str) -> ExternalPrincipal:
    raise ExternalAccessError("API credential is not recognized.")


def _authorize(
    *,
    method: str = "GET",
    path: str = "/v1/model/summary",
    client_host: str | None = REMOTE,
    lan_enabled: bool = True,
    authorization: str | None = "Bearer device_1.secret",
    authenticate: Callable[[str], PairedDevice] = _accept,
) -> Actor:
    """Authorize a request that is remote and fully credentialed by default."""
    return authorize(
        method=method,
        path=path,
        client_host=client_host,
        lan_enabled=lan_enabled,
        authorization=authorization,
        authenticate=authenticate,
    )


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "::1", "[::1]", "localhost", "::ffff:127.0.0.1", "LOCALHOST"]
)
def test_loopback_hosts_are_recognized_as_the_owner(host: str) -> None:
    # Given/When/Then: only real loopback peers are the owner
    assert is_loopback_client(host)


@pytest.mark.parametrize("host", [None, "", "192.168.1.50", "10.0.0.1", "example.test"])
def test_non_loopback_hosts_are_not_the_owner(host: str | None) -> None:
    # Given/When/Then: unknown and remote peers are never the owner
    assert not is_loopback_client(host)


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/v1/health", Requirement.PUBLIC),
        ("POST", "/v1/pairing/complete", Requirement.PUBLIC),
        ("GET", "/index.html", Requirement.PUBLIC),
        ("POST", "/v1/pairing/start", Requirement.OWNER),
        ("GET", "/v1/devices", Requirement.OWNER),
        ("DELETE", "/v1/devices/device_1", Requirement.OWNER),
        ("GET", "/v1/network/state", Requirement.OWNER),
        ("GET", "/v1/service-identities", Requirement.OWNER),
        ("GET", "/v1/audit/events", Requirement.OWNER),
        ("POST", "/v1/data/backups", Requirement.OWNER),
        ("POST", "/v1/data/remote-backups", Requirement.OWNER),
        ("POST", "/v1/data/remote-restores/latest", Requirement.OWNER),
        ("DELETE", "/v1/evidence/evidence_1", Requirement.OWNER),
        ("DELETE", "/v1/decisions/decision_1/outcome", Requirement.OWNER),
        ("GET", "/v1/key-aliases", Requirement.OWNER),
        ("POST", "/v1/key-aliases/review", Requirement.OWNER),
        ("POST", "/v1/key-aliases/remove", Requirement.OWNER),
        ("GET", "/v1/embedding-model", Requirement.OWNER),
        ("POST", "/v1/embedding-model/download", Requirement.OWNER),
        ("POST", "/v1/embedding-model/remove", Requirement.OWNER),
        ("GET", "/v1/key-aliases-other", Requirement.DEVICE),
        ("GET", "/v1/embedding-models", Requirement.DEVICE),
        ("GET", "/v1/evidence/evidence_1", Requirement.DEVICE),
        ("POST", "/v1/chat", Requirement.DEVICE),
        ("GET", "/v1/model/summary", Requirement.DEVICE),
        ("POST", "/v1/preferences/corrections", Requirement.DEVICE),
    ],
)
def test_path_requirements_classify_owner_public_and_device_routes(
    method: str, path: str, expected: Requirement
) -> None:
    # Given/When/Then: the boundary classifies every route explicitly
    assert path_requirement(method, path) is expected


def test_paths_that_only_share_a_prefix_are_not_owner_only() -> None:
    # Given/When/Then: prefix matching must not capture unrelated routes
    assert path_requirement("GET", "/v1/devices-summary") is Requirement.DEVICE


@pytest.mark.parametrize("path", ["/v1/devices", "/v1/chat", "/v1/health"])
def test_the_owner_reaches_every_route_over_loopback(path: str) -> None:
    # Given: a request from the owner's own machine, when authorized,
    actor = _authorize(path=path, client_host="127.0.0.1", authorization=None)

    # Then: the owner is trusted without a device credential
    assert actor.kind is ActorKind.OWNER


def test_remote_requests_are_refused_while_lan_access_is_disabled() -> None:
    # Given: LAN access has not been enabled by the owner
    # When/Then: no remote request is served, even with a credential
    with pytest.raises(AccessDeniedError) as error:
        _authorize(lan_enabled=False)
    assert error.value.status_code == 403
    assert error.value.detail == "Access from other devices is disabled."


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/pairing/start"),
        ("GET", "/v1/devices"),
        ("DELETE", "/v1/evidence/e1"),
        ("DELETE", "/v1/decisions/d1/outcome"),
        ("GET", "/v1/service-identities"),
        ("GET", "/v1/audit/events"),
        ("POST", "/v1/data/backups"),
        ("POST", "/v1/data/remote-backups"),
        ("POST", "/v1/data/remote-restores/latest"),
    ],
)
def test_paired_devices_cannot_reach_owner_only_routes(method: str, path: str) -> None:
    # Given: a fully authorized paired device
    # When/Then: owner-only routes stay on the owner's machine
    with pytest.raises(AccessDeniedError) as error:
        _authorize(method=method, path=path)
    assert error.value.status_code == 403


def test_remote_pairing_completion_is_allowed_without_a_credential() -> None:
    # Given: a phone that scanned a pairing code but holds no credential yet,
    # when it completes pairing,
    actor = _authorize(method="POST", path="/v1/pairing/complete", authorization=None)

    # Then: it is anonymous, and the pairing token is the only secret it holds
    assert actor.kind is ActorKind.ANONYMOUS


@pytest.mark.parametrize("header", [None, "", "Token abc", "Bearer", "Bearer    "])
def test_device_routes_require_a_bearer_credential(header: str | None) -> None:
    # Given: a remote request without a usable credential header
    # When/Then: the service answers unauthorized
    with pytest.raises(AccessDeniedError) as error:
        _authorize(authorization=header)
    assert error.value.status_code == 401


def test_invalid_device_credentials_are_refused() -> None:
    # Given: a credential the pairing service does not recognize
    # When/Then: the request is unauthorized and the reason stays generic
    with pytest.raises(AccessDeniedError) as error:
        _authorize(authenticate=_reject)
    assert error.value.status_code == 401
    assert error.value.detail == "A paired device credential is required."


def test_valid_device_credentials_identify_the_calling_device() -> None:
    # Given: a remote request from a paired device, when it is authorized,
    actor = _authorize()

    # Then: handlers can see which device is calling
    assert actor.kind is ActorKind.DEVICE
    assert actor.device_id == "device_1"
    assert actor.device_name == "Phone"


def test_external_routes_require_a_scoped_service_key_even_on_loopback() -> None:
    with pytest.raises(AccessDeniedError) as missing:
        authorize(
            method="POST",
            path="/v1/external/predict-choice",
            client_host="127.0.0.1",
            lan_enabled=False,
            authorization=None,
            authenticate=_accept,
            authenticate_service=_accept_service,
        )
    assert missing.value.status_code == 401

    actor = authorize(
        method="POST",
        path="/v1/external/predict-choice",
        client_host="127.0.0.1",
        lan_enabled=False,
        authorization="Bearer sk_soulmate.credential_1.secret",
        authenticate=_accept,
        authenticate_service=_accept_service,
    )
    assert actor.kind is ActorKind.SERVICE
    assert actor.service_identity_id == SERVICE_IDENTITY.id
    assert actor.credential_id == API_CREDENTIAL.id


def test_external_keys_cannot_exceed_their_scope() -> None:
    with pytest.raises(AccessDeniedError) as denied:
        authorize(
            method="GET",
            path="/v1/external/preference-summary",
            client_host="127.0.0.1",
            lan_enabled=False,
            authorization="Bearer sk_soulmate.credential_1.secret",
            authenticate=_accept,
            authenticate_service=_accept_service,
        )
    assert denied.value.status_code == 403
    assert denied.value.service_identity_id == SERVICE_IDENTITY.id


def test_invalid_service_keys_receive_a_generic_error() -> None:
    with pytest.raises(AccessDeniedError) as denied:
        authorize(
            method="POST",
            path="/v1/external/predict-choice",
            client_host="127.0.0.1",
            lan_enabled=False,
            authorization="Bearer invalid",
            authenticate=_accept,
            authenticate_service=_reject_service,
        )
    assert denied.value.status_code == 401
    assert denied.value.detail == "An external service API key is required."


@pytest.mark.parametrize(
    ("header", "expected"),
    [("Bearer abc", "abc"), ("Bearer  abc ", "abc"), ("bearer abc", None), (None, None)],
)
def test_bearer_credentials_are_parsed_strictly(header: str | None, expected: str | None) -> None:
    # Given/When/Then: only a correctly formed bearer header carries a credential
    assert bearer_credential(header) == expected


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "*", "127.0.0.1", "::1", "localhost"])
def test_wildcard_and_loopback_lan_hosts_are_refused(host: str) -> None:
    # Given/When/Then: LAN exposure is always an explicit, non-loopback address
    with pytest.raises(NetworkConfigurationError):
        resolve_lan_host(host)


def test_configured_lan_host_is_used_verbatim() -> None:
    # Given/When/Then: an explicit address is honored without detection
    assert resolve_lan_host("192.168.1.20") == "192.168.1.20"
