"""Verify owner-controlled pairing, authentication, and revocation rules."""

from datetime import UTC, datetime, timedelta

import pytest
from soulmate_core.access import (
    DevicePairingService,
    PairingError,
    format_credential,
    generate_secret,
    hash_secret,
    parse_credential,
    verify_secret,
)
from soulmate_core.domain import PairedDevice, PairingToken

NOW = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
TTL = timedelta(minutes=5)


class InMemoryPairingTokens:
    def __init__(self) -> None:
        self.tokens: dict[str, PairingToken] = {}
        self.deleted_before: list[datetime] = []
        self.consume_result: bool | None = None

    def add(self, token: PairingToken) -> None:
        self.tokens[token.id] = token

    def get_by_hash(self, token_hash: str) -> PairingToken | None:
        return next((item for item in self.tokens.values() if item.token_hash == token_hash), None)

    def consume(self, token_id: str, device_id: str, consumed_at: datetime) -> bool:
        if self.consume_result is not None:
            return self.consume_result
        token = self.tokens[token_id]
        if token.consumed_at is not None:
            return False
        self.tokens[token_id] = PairingToken(
            id=token.id,
            profile_id=token.profile_id,
            token_hash=token.token_hash,
            created_at=token.created_at,
            expires_at=token.expires_at,
            consumed_at=consumed_at,
            device_id=device_id,
        )
        return True

    def delete_expired(self, before: datetime) -> int:
        self.deleted_before.append(before)
        expired = [key for key, item in self.tokens.items() if item.expires_at <= before]
        for key in expired:
            del self.tokens[key]
        return len(expired)


class InMemoryPairedDevices:
    def __init__(self) -> None:
        self.devices: dict[str, PairedDevice] = {}
        self.touched: list[tuple[str, datetime]] = []

    def add(self, device: PairedDevice) -> None:
        self.devices[device.id] = device

    def get(self, device_id: str) -> PairedDevice | None:
        return self.devices.get(device_id)

    def list_for_profile(self, profile_id: str) -> tuple[PairedDevice, ...]:
        return tuple(item for item in self.devices.values() if item.profile_id == profile_id)

    def touch(self, device_id: str, last_seen_at: datetime) -> None:
        if device_id not in self.devices:
            raise KeyError(device_id)
        self.touched.append((device_id, last_seen_at))

    def revoke(self, device_id: str, revoked_at: datetime) -> bool:
        device = self.devices.get(device_id)
        if device is None or not device.is_active:
            return False
        self.devices[device_id] = PairedDevice(
            id=device.id,
            profile_id=device.profile_id,
            name=device.name,
            platform=device.platform,
            credential_hash=device.credential_hash,
            created_at=device.created_at,
            last_seen_at=device.last_seen_at,
            revoked_at=revoked_at,
        )
        return True


@pytest.fixture
def tokens() -> InMemoryPairingTokens:
    return InMemoryPairingTokens()


@pytest.fixture
def devices() -> InMemoryPairedDevices:
    return InMemoryPairedDevices()


@pytest.fixture
def service(tokens: InMemoryPairingTokens, devices: InMemoryPairedDevices) -> DevicePairingService:
    counter = iter(f"{index:032x}" for index in range(1, 100))
    return DevicePairingService(
        tokens, devices, ttl=TTL, secret_factory=generate_secret, id_factory=lambda: next(counter)
    )


def _pair(service: DevicePairingService, now: datetime = NOW) -> tuple[str, str]:
    # Given: the owner issued a pairing token on their own machine
    issued = service.issue_token("profile_default", now)
    # When: a device redeems it
    credential = service.complete("profile_default", issued.secret, "Phone", "ios", now)
    # Then: the caller receives a usable credential
    return issued.secret, credential.credential


def test_issued_token_stores_only_a_hash_and_a_bounded_lifetime(
    service: DevicePairingService, tokens: InMemoryPairingTokens
) -> None:
    # Given: a fresh installation with no pairing tokens
    # When: the owner starts pairing
    issued = service.issue_token("profile_default", NOW)

    # Then: only the hash is persisted and the token expires after the lifetime
    stored = tokens.tokens[issued.token.id]
    assert stored.token_hash == hash_secret(issued.secret)
    assert issued.secret not in {stored.token_hash, stored.id}
    assert stored.expires_at == NOW + TTL
    assert tokens.deleted_before == [NOW]


def test_completing_pairing_creates_a_device_and_consumes_the_token(
    service: DevicePairingService, tokens: InMemoryPairingTokens
) -> None:
    # Given: an issued pairing token
    issued = service.issue_token("profile_default", NOW)

    # When: a device completes pairing
    credential = service.complete("profile_default", issued.secret, " Phone ", "android", NOW)

    # Then: the device is stored without the plaintext credential and the token is used
    device_id, secret = parse_credential(credential.credential)
    assert credential.device.name == "Phone"
    assert credential.device.platform == "android"
    assert device_id == credential.device.id
    assert verify_secret(secret, credential.device.credential_hash)
    assert tokens.tokens[issued.token.id].consumed_at == NOW


def test_pairing_token_cannot_be_used_twice(service: DevicePairingService) -> None:
    # Given: a pairing token that a device already redeemed
    issued = service.issue_token("profile_default", NOW)
    service.complete("profile_default", issued.secret, "Phone", "ios", NOW)

    # When/Then: a replay is rejected
    with pytest.raises(PairingError, match="already used"):
        service.complete("profile_default", issued.secret, "Laptop", "linux", NOW)


def test_pairing_token_race_is_rejected_when_storage_cannot_claim_it(
    service: DevicePairingService, tokens: InMemoryPairingTokens, devices: InMemoryPairedDevices
) -> None:
    # Given: storage reports that another request claimed the token first
    issued = service.issue_token("profile_default", NOW)
    tokens.consume_result = False

    # When/Then: pairing fails and no device is created
    with pytest.raises(PairingError, match="already used"):
        service.complete("profile_default", issued.secret, "Phone", "ios", NOW)
    assert devices.devices == {}


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(TTL - timedelta(microseconds=1), True), (TTL, False), (TTL + timedelta(seconds=1), False)],
)
def test_pairing_token_expiry_boundary(
    service: DevicePairingService, offset: timedelta, expected: bool
) -> None:
    # Given: a pairing token issued at a known time
    issued = service.issue_token("profile_default", NOW)

    # When: a device redeems it at the boundary of the lifetime
    if expected:
        assert service.complete("profile_default", issued.secret, "Phone", "ios", NOW + offset)
        return

    # Then: expired tokens are refused
    with pytest.raises(PairingError, match="expired"):
        service.complete("profile_default", issued.secret, "Phone", "ios", NOW + offset)


@pytest.mark.parametrize("secret", ["", "not-a-real-token", "x" * 200])
def test_unknown_pairing_tokens_are_rejected(service: DevicePairingService, secret: str) -> None:
    # Given: an installation with one valid token
    service.issue_token("profile_default", NOW)

    # When/Then: a different secret never pairs
    with pytest.raises(PairingError, match="invalid"):
        service.complete("profile_default", secret, "Phone", "ios", NOW)


def test_pairing_token_of_another_profile_is_rejected(service: DevicePairingService) -> None:
    # Given: a token that belongs to another profile
    issued = service.issue_token("profile_other", NOW)

    # When/Then: it cannot enrol a device into this profile
    with pytest.raises(PairingError, match="invalid"):
        service.complete("profile_default", issued.secret, "Phone", "ios", NOW)


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_device_names_are_rejected(service: DevicePairingService, name: str) -> None:
    # Given: a valid pairing token
    issued = service.issue_token("profile_default", NOW)

    # When/Then: the device must identify itself
    with pytest.raises(PairingError, match="name"):
        service.complete("profile_default", issued.secret, name, "ios", NOW)


def test_authentication_accepts_the_issued_credential_and_records_contact(
    service: DevicePairingService, devices: InMemoryPairedDevices
) -> None:
    # Given: a paired device
    _, credential = _pair(service)

    # When: it calls the service later
    later = NOW + timedelta(hours=3)
    device = service.authenticate(credential, later)

    # Then: the device is recognized and its last contact is recorded
    assert device.name == "Phone"
    assert devices.touched == [(device.id, later)]


@pytest.mark.parametrize("credential", ["", "no-separator", ".secret", "device.", "."])
def test_malformed_credentials_are_rejected(service: DevicePairingService, credential: str) -> None:
    # Given: a paired device exists
    _pair(service)

    # When/Then: malformed credentials never authenticate
    with pytest.raises(PairingError, match=r"malformed|not recognized"):
        service.authenticate(credential, NOW)


def test_unknown_and_wrong_credentials_are_rejected(service: DevicePairingService) -> None:
    # Given: a paired device
    _, credential = _pair(service)
    device_id, _ = parse_credential(credential)

    # When/Then: neither an unknown device nor a wrong secret is accepted
    with pytest.raises(PairingError, match="not recognized"):
        service.authenticate(format_credential("device_missing", "secret"), NOW)
    with pytest.raises(PairingError, match="not recognized"):
        service.authenticate(format_credential(device_id, generate_secret()), NOW)


def test_revoked_devices_lose_access_and_revocation_is_idempotent(
    service: DevicePairingService,
) -> None:
    # Given: a paired device
    _, credential = _pair(service)
    device_id, _ = parse_credential(credential)

    # When: the owner revokes it twice
    first = service.revoke("profile_default", device_id, NOW + timedelta(minutes=1))
    second = service.revoke("profile_default", device_id, NOW + timedelta(minutes=2))

    # Then: the device is revoked once and can no longer authenticate
    assert first.revoked_at == NOW + timedelta(minutes=1)
    assert second.revoked_at == first.revoked_at
    with pytest.raises(PairingError, match="revoked"):
        service.authenticate(credential, NOW + timedelta(minutes=3))


def test_revoking_an_unknown_or_foreign_device_raises_key_error(
    service: DevicePairingService,
) -> None:
    # Given: a device paired to this profile
    _, credential = _pair(service)
    device_id, _ = parse_credential(credential)

    # When/Then: only this profile's existing devices can be revoked
    with pytest.raises(KeyError):
        service.revoke("profile_default", "device_missing", NOW)
    with pytest.raises(KeyError):
        service.revoke("profile_other", device_id, NOW)


def test_listing_devices_is_scoped_to_the_profile(service: DevicePairingService) -> None:
    # Given: one paired device
    _pair(service)

    # When/Then: listings never leak across profiles
    assert len(service.list_devices("profile_default")) == 1
    assert service.list_devices("profile_other") == ()


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
def test_non_positive_token_lifetime_is_rejected(
    tokens: InMemoryPairingTokens, devices: InMemoryPairedDevices, ttl: timedelta
) -> None:
    # Given/When/Then: a pairing service must expire tokens
    with pytest.raises(ValueError, match="positive"):
        DevicePairingService(tokens, devices, ttl=ttl)


def test_secret_hashing_never_stores_or_compares_plaintext() -> None:
    # Given: a generated secret that is then hashed
    secret = generate_secret()
    digest = hash_secret(secret)

    # Then: the digest hides the secret and only the matching secret verifies
    assert secret not in digest
    assert len(digest) == 64
    assert verify_secret(secret, digest)
    assert not verify_secret(f"{secret}x", digest)
