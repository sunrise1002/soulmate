"""Owner-controlled device pairing rules for access from another device."""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from soulmate_core.domain.models import PairedDevice, PairingToken
from soulmate_core.domain.ports import PairedDeviceRepository, PairingTokenRepository

DEFAULT_PAIRING_TOKEN_TTL = timedelta(minutes=5)
CREDENTIAL_SEPARATOR = "."
SECRET_BYTES = 32


class PairingError(Exception):
    """A pairing or device authentication rule rejected the request."""


def generate_secret() -> str:
    """Return a high-entropy URL-safe secret suitable for one-time transport."""
    return secrets.token_urlsafe(SECRET_BYTES)


def hash_secret(secret: str) -> str:
    """Hash a high-entropy secret so persistence never stores usable credentials."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, digest: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), digest)


def format_credential(device_id: str, secret: str) -> str:
    return f"{device_id}{CREDENTIAL_SEPARATOR}{secret}"


def parse_credential(credential: str) -> tuple[str, str]:
    """Split a device credential, raising PairingError for malformed input."""
    device_id, separator, secret = credential.partition(CREDENTIAL_SEPARATOR)
    if not separator or not device_id or not secret:
        raise PairingError("Device credential is malformed.")
    return device_id, secret


@dataclass(frozen=True, slots=True)
class IssuedPairingToken:
    """A stored pairing token together with the secret shown once to the owner."""

    token: PairingToken
    secret: str


@dataclass(frozen=True, slots=True)
class IssuedDeviceCredential:
    """A stored device together with the credential returned once to that device."""

    device: PairedDevice
    credential: str


class DevicePairingService:
    """Issue, redeem, authenticate, and revoke credentials for owner devices."""

    def __init__(
        self,
        tokens: PairingTokenRepository,
        devices: PairedDeviceRepository,
        *,
        ttl: timedelta = DEFAULT_PAIRING_TOKEN_TTL,
        secret_factory: Callable[[], str] = generate_secret,
        id_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("Pairing token lifetime must be positive.")
        self._tokens = tokens
        self._devices = devices
        self._ttl = ttl
        self._secret_factory = secret_factory
        self._id_factory = id_factory

    def issue_token(self, profile_id: str, now: datetime) -> IssuedPairingToken:
        """Create a single-use pairing secret and drop tokens that already expired."""
        self._tokens.delete_expired(now)
        secret = self._secret_factory()
        token = PairingToken(
            id=f"pairing_{self._id_factory()}",
            profile_id=profile_id,
            token_hash=hash_secret(secret),
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._tokens.add(token)
        return IssuedPairingToken(token=token, secret=secret)

    def complete(
        self, profile_id: str, secret: str, name: str, platform: str, now: datetime
    ) -> IssuedDeviceCredential:
        """Redeem a pairing secret exactly once and return a device credential."""
        if not name.strip():
            raise PairingError("Device name must not be empty.")
        token = self._tokens.get_by_hash(hash_secret(secret))
        if token is None or token.profile_id != profile_id:
            raise PairingError("Pairing token is invalid.")
        if token.consumed_at is not None:
            raise PairingError("Pairing token was already used.")
        if now >= token.expires_at:
            raise PairingError("Pairing token expired.")
        device_secret = self._secret_factory()
        device = PairedDevice(
            id=f"device_{self._id_factory()}",
            profile_id=profile_id,
            name=name.strip(),
            platform=platform,
            credential_hash=hash_secret(device_secret),
            created_at=now,
        )
        if not self._tokens.consume(token.id, device.id, now):
            raise PairingError("Pairing token was already used.")
        self._devices.add(device)
        return IssuedDeviceCredential(
            device=device, credential=format_credential(device.id, device_secret)
        )

    def authenticate(self, credential: str, now: datetime) -> PairedDevice:
        """Resolve a bearer credential to an active device and record the contact."""
        device_id, secret = parse_credential(credential)
        device = self._devices.get(device_id)
        if device is None or not verify_secret(secret, device.credential_hash):
            raise PairingError("Device credential is not recognized.")
        if not device.is_active:
            raise PairingError("Device access was revoked.")
        self._devices.touch(device.id, now)
        return device

    def list_devices(self, profile_id: str) -> tuple[PairedDevice, ...]:
        return self._devices.list_for_profile(profile_id)

    def revoke(self, profile_id: str, device_id: str, now: datetime) -> PairedDevice:
        """Revoke one device of this profile and return its updated record."""
        device = self._devices.get(device_id)
        if device is None or device.profile_id != profile_id:
            raise KeyError(device_id)
        if device.is_active and not self._devices.revoke(device_id, now):
            raise KeyError(device_id)
        stored = self._devices.get(device_id)
        if stored is None:
            raise KeyError(device_id)
        return stored
