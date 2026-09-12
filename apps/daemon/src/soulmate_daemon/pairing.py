"""Pairing orchestration that turns kernel decisions into auditable records."""

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from soulmate_core.access import DevicePairingService, IssuedDeviceCredential, PairingError
from soulmate_core.domain import AuditEvent, AuditEventRepository, PairedDevice

PAIRING_URI_SCHEME = "soulmate://pair?data="
PAIRING_PAYLOAD_VERSION = 1


@dataclass(frozen=True, slots=True)
class PairingInvitation:
    """The one-time material a phone needs to enrol, shown as text and QR data."""

    token: str
    expires_at: datetime
    service_url: str
    service_id: str
    fingerprint: str

    def as_payload(self) -> dict[str, object]:
        return {
            "v": PAIRING_PAYLOAD_VERSION,
            "service_url": self.service_url,
            "service_id": self.service_id,
            "fingerprint": self.fingerprint,
            "token": self.token,
            "expires_at": self.expires_at.isoformat(),
        }

    def as_qr_payload(self) -> str:
        """Encode the invitation as a compact deep link suitable for a QR code."""
        encoded = base64.urlsafe_b64encode(
            json.dumps(self.as_payload(), separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")
        return f"{PAIRING_URI_SCHEME}{encoded.rstrip('=')}"


class DeviceAccessService:
    """Owner-facing pairing and revocation with audit trail and clock injection."""

    def __init__(
        self,
        pairing: DevicePairingService,
        audit_events: AuditEventRepository,
        *,
        service_id: str,
    ) -> None:
        self._pairing = pairing
        self._audit = audit_events
        self._service_id = service_id

    def invite(
        self,
        profile_id: str,
        *,
        service_url: str,
        fingerprint: str,
        now: datetime | None = None,
    ) -> PairingInvitation:
        moment = now if now is not None else datetime.now(UTC)
        issued = self._pairing.issue_token(profile_id, moment)
        self._record(profile_id, "pairing_token_issued", "owner", None, moment)
        return PairingInvitation(
            token=issued.secret,
            expires_at=issued.token.expires_at,
            service_url=service_url,
            service_id=self._service_id,
            fingerprint=fingerprint,
        )

    def complete(
        self,
        profile_id: str,
        token: str,
        name: str,
        platform: str,
        *,
        now: datetime | None = None,
    ) -> IssuedDeviceCredential:
        moment = now if now is not None else datetime.now(UTC)
        issued = self._pairing.complete(profile_id, token, name, platform, moment)
        self._record(profile_id, "device_paired", "device", issued.device.id, moment)
        return issued

    def authenticate(self, credential: str, *, now: datetime | None = None) -> PairedDevice:
        moment = now if now is not None else datetime.now(UTC)
        return self._pairing.authenticate(credential, moment)

    def devices(self, profile_id: str) -> tuple[PairedDevice, ...]:
        return self._pairing.list_devices(profile_id)

    def revoke(
        self, profile_id: str, device_id: str, *, now: datetime | None = None
    ) -> PairedDevice:
        moment = now if now is not None else datetime.now(UTC)
        device = self._pairing.revoke(profile_id, device_id, moment)
        self._record(profile_id, "device_revoked", "owner", device_id, moment)
        return device

    def _record(
        self,
        profile_id: str,
        action: str,
        actor_type: str,
        actor_id: str | None,
        now: datetime,
    ) -> None:
        self._audit.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                action=action,
                actor_type=actor_type,
                created_at=now,
                profile_id=profile_id,
                actor_id=actor_id,
                metadata={"service_id": self._service_id},
            )
        )


def pairing_token_ttl(seconds: int) -> timedelta:
    return timedelta(seconds=seconds)


__all__ = [
    "DeviceAccessService",
    "PairingError",
    "PairingInvitation",
    "pairing_token_ttl",
]
