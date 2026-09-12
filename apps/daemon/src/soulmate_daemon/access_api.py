"""Owner-controlled pairing, device management, and LAN status endpoints."""

from datetime import datetime

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from soulmate_core.access import PairingError
from soulmate_core.domain import PairedDevice

from soulmate_daemon.runtime import build_access_service, runtime_of
from soulmate_daemon.security import Actor, ActorKind
from soulmate_daemon.system import DEFAULT_PROFILE_ID


class PairingStartResponse(BaseModel):
    token: str
    expires_at: datetime
    service_url: str
    service_id: str
    fingerprint: str
    qr_payload: str


class PairingCompleteRequest(BaseModel):
    token: str = Field(min_length=8, max_length=500)
    device_name: str = Field(min_length=1, max_length=100)
    platform: str = Field(default="unknown", min_length=1, max_length=50)


class PairingCompleteResponse(BaseModel):
    device_id: str
    device_name: str
    platform: str
    credential: str
    service_id: str
    fingerprint: str
    created_at: datetime


class DeviceResponse(BaseModel):
    id: str
    name: str
    platform: str
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None
    active: bool


class NetworkStateResponse(BaseModel):
    lan_enabled: bool
    lan_url: str | None
    fingerprint: str | None
    certificate_expires_at: datetime | None
    paired_device_count: int
    active_device_count: int
    web_client_available: bool
    error: str | None


class SessionResponse(BaseModel):
    actor: str
    device_id: str | None
    device_name: str | None
    service_id: str
    profile_id: str


def _device_response(device: PairedDevice) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        platform=device.platform,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
        active=device.is_active,
    )


def _actor(request: Request) -> Actor:
    actor = getattr(request.state, "actor", None)
    if not isinstance(actor, Actor):
        raise HTTPException(status_code=401, detail="The request was not authorized.")
    return actor


def build_access_router(app: FastAPI) -> APIRouter:
    """Create the device access routes bound to the daemon runtime of this app."""
    router = APIRouter()

    @router.post("/v1/pairing/start", response_model=PairingStartResponse, status_code=201)
    def start_pairing() -> PairingStartResponse:
        runtime = runtime_of(app)
        lan = runtime["lan"]
        if lan is None:
            raise HTTPException(
                status_code=409,
                detail="Enable access from other devices before pairing a device.",
            )
        invitation = build_access_service(runtime).invite(
            DEFAULT_PROFILE_ID, service_url=lan.url, fingerprint=lan.fingerprint
        )
        return PairingStartResponse(
            token=invitation.token,
            expires_at=invitation.expires_at,
            service_url=invitation.service_url,
            service_id=invitation.service_id,
            fingerprint=invitation.fingerprint,
            qr_payload=invitation.as_qr_payload(),
        )

    @router.post("/v1/pairing/complete", response_model=PairingCompleteResponse, status_code=201)
    def complete_pairing(request: PairingCompleteRequest) -> PairingCompleteResponse:
        runtime = runtime_of(app)
        lan = runtime["lan"]
        if lan is None:
            raise HTTPException(status_code=409, detail="Access from other devices is disabled.")
        try:
            issued = build_access_service(runtime).complete(
                DEFAULT_PROFILE_ID, request.token, request.device_name, request.platform
            )
        except PairingError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return PairingCompleteResponse(
            device_id=issued.device.id,
            device_name=issued.device.name,
            platform=issued.device.platform,
            credential=issued.credential,
            service_id=runtime["installation_id"],
            fingerprint=lan.fingerprint,
            created_at=issued.device.created_at,
        )

    @router.get("/v1/devices", response_model=list[DeviceResponse])
    def list_devices() -> list[DeviceResponse]:
        runtime = runtime_of(app)
        devices = build_access_service(runtime).devices(DEFAULT_PROFILE_ID)
        return [_device_response(device) for device in devices]

    @router.delete("/v1/devices/{device_id}", response_model=DeviceResponse)
    def revoke_device(device_id: str) -> DeviceResponse:
        runtime = runtime_of(app)
        try:
            device = build_access_service(runtime).revoke(DEFAULT_PROFILE_ID, device_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Device was not found.") from exc
        return _device_response(device)

    @router.get("/v1/network/state", response_model=NetworkStateResponse)
    def network_state() -> NetworkStateResponse:
        runtime = runtime_of(app)
        lan = runtime["lan"]
        devices = build_access_service(runtime).devices(DEFAULT_PROFILE_ID)
        return NetworkStateResponse(
            lan_enabled=lan is not None,
            lan_url=None if lan is None else lan.url,
            fingerprint=None if lan is None else lan.fingerprint,
            certificate_expires_at=(None if lan is None else lan.certificate.not_valid_after),
            paired_device_count=len(devices),
            active_device_count=sum(1 for device in devices if device.is_active),
            web_client_available=runtime["settings"].web_client_directory is not None,
            error=runtime["lan_error"],
        )

    @router.get("/v1/session", response_model=SessionResponse)
    def session(request: Request) -> SessionResponse:
        runtime = runtime_of(app)
        actor = _actor(request)
        if actor.kind is ActorKind.ANONYMOUS:
            raise HTTPException(status_code=401, detail="The request was not authorized.")
        return SessionResponse(
            actor=actor.kind.value,
            device_id=actor.device_id,
            device_name=actor.device_name,
            service_id=runtime["installation_id"],
            profile_id=DEFAULT_PROFILE_ID,
        )

    return router
