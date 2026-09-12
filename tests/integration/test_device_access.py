"""Exercise LAN pairing, device access, revocation, and the served web client."""

import base64
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.network import LanEndpoint
from soulmate_daemon.pairing import PAIRING_URI_SCHEME
from soulmate_daemon.tls import ensure_service_certificate

pytestmark = pytest.mark.integration

OWNER_CLIENT = ("127.0.0.1", 50000)
PHONE_CLIENT = ("192.168.1.50", 51000)
LAN_ADDRESS = "192.168.1.20"


def _settings(tmp_path: Path, *, lan_enabled: bool = True) -> Settings:
    return Settings.model_validate(
        {
            "data_dir": str(tmp_path / "owner-data"),
            "network": {"lan_enabled": lan_enabled, "lan_host": LAN_ADDRESS},
        }
    )


def _endpoint(tmp_path: Path) -> LanEndpoint:
    certificate = ensure_service_certificate(tmp_path / "tls", (LAN_ADDRESS,))
    return LanEndpoint(host=LAN_ADDRESS, port=7433, certificate=certificate)


def _app(tmp_path: Path, *, lan_enabled: bool = True) -> FastAPI:
    settings = _settings(tmp_path, lan_enabled=lan_enabled)
    return create_app(settings, lan=_endpoint(tmp_path) if lan_enabled else None)


def _owner(app: FastAPI) -> TestClient:
    return TestClient(app, client=OWNER_CLIENT)


def _phone(app: FastAPI, credential: str | None = None) -> TestClient:
    headers = {} if credential is None else {"Authorization": f"Bearer {credential}"}
    return TestClient(app, client=PHONE_CLIENT, headers=headers)


@pytest.fixture
def paired(tmp_path: Path) -> Iterator[tuple[FastAPI, str, str]]:
    """Provide an application with one paired phone and its credential."""
    app = _app(tmp_path)
    with _owner(app) as owner:
        invitation = owner.post("/v1/pairing/start").json()
        with _phone(app) as phone:
            paired_device = phone.post(
                "/v1/pairing/complete",
                json={
                    "token": invitation["token"],
                    "device_name": "Phone",
                    "platform": "ios",
                },
            ).json()
        yield app, paired_device["credential"], paired_device["device_id"]


def test_owner_pairs_a_phone_that_can_then_use_the_personal_model(
    paired: tuple[FastAPI, str, str],
) -> None:
    # Given: the owner paired a phone over the LAN
    app, credential, device_id = paired

    # When: the phone reads the Personal Model and identifies itself
    with _phone(app, credential) as phone:
        summary = phone.get("/v1/model/summary")
        session = phone.get("/v1/session")

    # Then: the phone is served as a known device
    assert summary.status_code == 200
    assert session.status_code == 200
    assert session.json()["actor"] == "device"
    assert session.json()["device_id"] == device_id
    assert session.json()["device_name"] == "Phone"


def test_pairing_invitation_carries_the_service_url_and_pinned_fingerprint(
    tmp_path: Path,
) -> None:
    # Given: an installation with LAN access enabled
    app = _app(tmp_path)

    # When: the owner starts pairing
    with _owner(app) as owner:
        response = owner.post("/v1/pairing/start")
    invitation = response.json()
    encoded = invitation["qr_payload"].removeprefix(PAIRING_URI_SCHEME)
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

    # Then: the QR payload contains everything a phone needs to pin the service
    assert response.status_code == 201
    assert invitation["service_url"] == f"https://{LAN_ADDRESS}:7433"
    assert invitation["fingerprint"].startswith("sha256:")
    assert payload["token"] == invitation["token"]
    assert payload["fingerprint"] == invitation["fingerprint"]
    assert payload["service_id"] == invitation["service_id"]


def test_pairing_tokens_are_single_use_and_never_stored_in_plaintext(
    tmp_path: Path,
) -> None:
    # Given: a pairing token that one phone already redeemed
    app = _app(tmp_path)
    with _owner(app) as owner:
        token = owner.post("/v1/pairing/start").json()["token"]
    with _phone(app) as phone:
        first = phone.post(
            "/v1/pairing/complete",
            json={"token": token, "device_name": "Phone", "platform": "ios"},
        )
        second = phone.post(
            "/v1/pairing/complete",
            json={"token": token, "device_name": "Other", "platform": "android"},
        )

    # Then: the replay fails and the database never holds the secret
    assert first.status_code == 201
    assert second.status_code == 401
    stored = (tmp_path / "owner-data" / "decision-twin.db").read_bytes()
    assert token.encode("utf-8") not in stored
    assert first.json()["credential"].encode("utf-8") not in stored


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "wrong-token-value", "device_name": "Phone", "platform": "ios"},
        {"token": "short", "device_name": "Phone", "platform": "ios"},
        {"token": "a-valid-looking-token", "device_name": "", "platform": "ios"},
        {"device_name": "Phone", "platform": "ios"},
    ],
)
def test_invalid_pairing_requests_are_rejected(tmp_path: Path, payload: dict[str, str]) -> None:
    # Given: an installation with an outstanding pairing token
    app = _app(tmp_path)
    with _owner(app) as owner:
        owner.post("/v1/pairing/start")

    # When: a phone sends malformed or wrong pairing input
    with _phone(app) as phone:
        response = phone.post("/v1/pairing/complete", json=payload)

    # Then: no device is enrolled
    assert response.status_code in {401, 422}
    with _owner(app) as owner:
        assert owner.get("/v1/devices").json() == []


def test_owner_revokes_a_phone_and_it_immediately_loses_access(
    paired: tuple[FastAPI, str, str],
) -> None:
    # Given: a paired phone with working access
    app, credential, device_id = paired
    with _phone(app, credential) as phone:
        assert phone.get("/v1/model/summary").status_code == 200

    # When: the owner revokes the device from their own machine
    with _owner(app) as owner:
        revoked = owner.delete(f"/v1/devices/{device_id}")
        listed = owner.get("/v1/devices").json()

    # Then: the device is recorded as revoked and can no longer read anything
    assert revoked.status_code == 200
    assert revoked.json()["active"] is False
    assert listed[0]["active"] is False
    with _phone(app, credential) as phone:
        assert phone.get("/v1/model/summary").status_code == 401


def test_revoking_an_unknown_device_is_reported_as_not_found(tmp_path: Path) -> None:
    # Given: an installation with no paired devices
    app = _app(tmp_path)

    # When/Then: revocation of an unknown device fails cleanly
    with _owner(app) as owner:
        assert owner.delete("/v1/devices/device_missing").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/v1/pairing/start"), ("GET", "/v1/devices"), ("GET", "/v1/network/state")],
)
def test_paired_devices_cannot_manage_devices_or_network_access(
    paired: tuple[FastAPI, str, str], method: str, path: str
) -> None:
    # Given: a fully paired phone
    app, credential, _ = paired

    # When/Then: device management stays on the owner's machine
    with _phone(app, credential) as phone:
        assert phone.request(method, path).status_code == 403


def test_paired_devices_cannot_delete_evidence(paired: tuple[FastAPI, str, str]) -> None:
    # Given: a paired phone and evidence created by the owner
    app, credential, _ = paired
    with _owner(app) as owner:
        created = owner.post(
            "/v1/preferences/corrections", json={"target_key": "quiet", "value": 0.8}
        ).json()

    # When: the phone tries to delete that evidence
    with _phone(app, credential) as phone:
        response = phone.delete(f"/v1/evidence/{created['evidence']['id']}")

    # Then: deletion is refused and the evidence is still readable by the owner
    assert response.status_code == 403
    with _owner(app) as owner:
        assert owner.get(f"/v1/evidence/{created['evidence']['id']}").status_code == 200


def test_paired_devices_may_record_feedback_as_evidence(
    paired: tuple[FastAPI, str, str],
) -> None:
    # Given: a paired phone
    app, credential, _ = paired

    # When: the phone corrects a preference
    with _phone(app, credential) as phone:
        response = phone.post(
            "/v1/preferences/corrections", json={"target_key": "outdoor", "value": -0.4}
        )

    # Then: the correction is stored with full provenance
    assert response.status_code == 201
    assert response.json()["evidence"]["source_type"] == "user_correction"


def test_unpaired_devices_on_the_network_receive_no_personal_data(tmp_path: Path) -> None:
    # Given: an installation with LAN access enabled but no paired device
    app = _app(tmp_path)

    # When: an unknown device on the network calls the service
    with _phone(app) as phone:
        model = phone.get("/v1/model/summary")
        conversations = phone.get("/v1/conversations")
        health = phone.get("/v1/health")

    # Then: only the health probe answers
    assert model.status_code == 401
    assert conversations.status_code == 401
    assert health.status_code == 200


def test_remote_access_is_refused_while_lan_mode_is_disabled(tmp_path: Path) -> None:
    # Given: an installation that never enabled access from other devices
    app = _app(tmp_path, lan_enabled=False)

    # When: a device on the network calls the service
    with _phone(app) as phone:
        health = phone.get("/v1/health")
        pairing = phone.post(
            "/v1/pairing/complete",
            json={"token": "any-token-value", "device_name": "Phone", "platform": "ios"},
        )

    # Then: every remote request is refused, including pairing
    assert health.status_code == 403
    assert pairing.status_code == 403


def test_pairing_cannot_start_while_lan_mode_is_disabled(tmp_path: Path) -> None:
    # Given: an installation with LAN access disabled
    app = _app(tmp_path, lan_enabled=False)

    # When: the owner starts pairing anyway
    with _owner(app) as owner:
        response = owner.post("/v1/pairing/start")
        state = owner.get("/v1/network/state").json()

    # Then: the owner is told to enable LAN access first
    assert response.status_code == 409
    assert state["lan_enabled"] is False
    assert state["lan_url"] is None


def test_network_state_reports_the_pinned_fingerprint_and_device_counts(
    paired: tuple[FastAPI, str, str],
) -> None:
    # Given: an installation with one paired device
    app, _, device_id = paired

    # When: the owner inspects LAN access
    with _owner(app) as owner:
        before = owner.get("/v1/network/state").json()
        owner.delete(f"/v1/devices/{device_id}")
        after = owner.get("/v1/network/state").json()

    # Then: the reported state follows revocation
    assert before["lan_enabled"] is True
    assert before["lan_url"] == f"https://{LAN_ADDRESS}:7433"
    assert before["fingerprint"].startswith("sha256:")
    assert (before["paired_device_count"], before["active_device_count"]) == (1, 1)
    assert (after["paired_device_count"], after["active_device_count"]) == (1, 0)


def test_device_credentials_survive_a_service_restart(tmp_path: Path) -> None:
    # Given: a phone paired with a running service
    app = _app(tmp_path)
    with _owner(app) as owner:
        token = owner.post("/v1/pairing/start").json()["token"]
    with _phone(app) as phone:
        credential = phone.post(
            "/v1/pairing/complete",
            json={"token": token, "device_name": "Phone", "platform": "ios"},
        ).json()["credential"]

    # When: the service restarts against the same local database
    restarted = _app(tmp_path)

    # Then: the phone keeps access without pairing again
    with _phone(restarted, credential) as phone:
        assert phone.get("/v1/session").json()["device_name"] == "Phone"


def test_web_client_is_served_from_the_daemon_when_a_bundle_is_present(
    tmp_path: Path,
) -> None:
    # Given: a built web client bundle
    bundle = tmp_path / "web"
    bundle.mkdir()
    (bundle / "index.html").write_text("<!doctype html><title>Soulmate</title>", encoding="utf-8")
    settings = Settings.model_validate(
        {
            "data_dir": str(tmp_path / "owner-data"),
            "network": {"lan_enabled": True, "lan_host": LAN_ADDRESS},
            "web": {"client_dir": str(bundle)},
        }
    )
    app = create_app(settings, lan=_endpoint(tmp_path))

    # When: the owner and an unpaired phone open the service root
    with _owner(app) as owner, _phone(app) as phone:
        owner_page = owner.get("/")
        phone_page = phone.get("/")
        state = owner.get("/v1/network/state").json()

    # Then: the client loads so that pairing can be completed in a browser
    assert owner_page.status_code == 200
    assert phone_page.status_code == 200
    assert "Soulmate" in phone_page.text
    assert state["web_client_available"] is True


def test_missing_web_client_leaves_the_api_reachable(tmp_path: Path) -> None:
    # Given: an installation without a built web client
    settings = Settings.model_validate(
        {
            "data_dir": str(tmp_path / "owner-data"),
            "network": {"lan_enabled": True, "lan_host": LAN_ADDRESS},
            "web": {"enabled": False},
        }
    )
    app = create_app(settings, lan=_endpoint(tmp_path))

    # When: the owner opens the service root and the API
    with _owner(app) as owner:
        root = owner.get("/")
        health = owner.get("/v1/health")
        state = owner.get("/v1/network/state").json()

    # Then: the API keeps working and the missing bundle is reported
    assert root.status_code == 404
    assert health.status_code == 200
    assert state["web_client_available"] is False
