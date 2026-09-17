"""Owner-only API to review and change canonical target key aliases."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from soulmate_core.domain import AuditEvent, EvidenceTargetType, TargetKeyAlias

from soulmate_daemon.key_aliases import (
    KeyAliasError,
    KeyAliasReviewAction,
    KeyAliasService,
    model_rebuilder,
)
from soulmate_daemon.runtime import runtime_of
from soulmate_daemon.system import DEFAULT_PROFILE_ID

KEY_ALIASES_DISABLED = "Key aliases are disabled in the configuration."


class KeyAliasResponse(BaseModel):
    target_type: str
    alias_key: str
    canonical_key: str
    polarity: int
    method: str
    status: str
    similarity: float | None
    algorithm_version: str
    created_at: datetime
    updated_at: datetime


class KeyAliasListResponse(BaseModel):
    enabled: bool
    aliases: list[KeyAliasResponse]


class KeyAliasTargetRequest(BaseModel):
    target_type: EvidenceTargetType
    alias_key: str = Field(min_length=1, max_length=200)

    @field_validator("alias_key")
    @classmethod
    def reject_blank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Target keys must not be blank.")
        return value.strip()


class KeyAliasCreateRequest(KeyAliasTargetRequest):
    canonical_key: str = Field(min_length=1, max_length=200)
    polarity: Literal[1, -1] = 1

    @field_validator("canonical_key")
    @classmethod
    def reject_blank_canonical_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Target keys must not be blank.")
        return value.strip()


class KeyAliasReviewRequest(KeyAliasTargetRequest):
    action: KeyAliasReviewAction


class KeyAliasChangeResponse(BaseModel):
    alias: KeyAliasResponse
    snapshot_version: int


class KeyAliasRemovalResponse(BaseModel):
    target_type: str
    alias_key: str
    snapshot_version: int


def _alias_response(alias: TargetKeyAlias) -> KeyAliasResponse:
    return KeyAliasResponse(
        target_type=alias.target_type.value,
        alias_key=alias.alias_key,
        canonical_key=alias.canonical_key,
        polarity=alias.polarity,
        method=alias.method.value,
        status=alias.status.value,
        similarity=alias.similarity,
        algorithm_version=alias.algorithm_version,
        created_at=alias.created_at,
        updated_at=alias.updated_at,
    )


def build_key_alias_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    def service() -> KeyAliasService:
        repositories = runtime_of(app)["repositories"]
        return KeyAliasService(repositories.evidence, repositories.key_aliases)

    def require_enabled() -> None:
        if not runtime_of(app)["settings"].key_aliases.enabled:
            raise HTTPException(status_code=409, detail=KEY_ALIASES_DISABLED)

    def rebuild() -> int:
        runtime = runtime_of(app)
        rebuilder = model_rebuilder(runtime["repositories"], runtime["settings"])
        return rebuilder.rebuild(DEFAULT_PROFILE_ID).version

    def audit(action: str, metadata: dict[str, object]) -> None:
        # Key names can reveal personal topics, so the audit keeps only their shape.
        runtime_of(app)["repositories"].audit_events.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                profile_id=DEFAULT_PROFILE_ID,
                action=action,
                actor_type="owner",
                actor_id=None,
                metadata=metadata,
                created_at=datetime.now(UTC),
            )
        )

    def changed(alias: TargetKeyAlias, action: str) -> KeyAliasChangeResponse:
        snapshot_version = rebuild()
        audit(
            action,
            {
                "target_type": alias.target_type.value,
                "method": alias.method.value,
                "status": alias.status.value,
                "polarity": alias.polarity,
                "snapshot_version": snapshot_version,
            },
        )
        return KeyAliasChangeResponse(
            alias=_alias_response(alias), snapshot_version=snapshot_version
        )

    @router.get("/v1/key-aliases", response_model=KeyAliasListResponse)
    def list_aliases() -> KeyAliasListResponse:
        return KeyAliasListResponse(
            enabled=runtime_of(app)["settings"].key_aliases.enabled,
            aliases=[
                _alias_response(item) for item in service().list_for_profile(DEFAULT_PROFILE_ID)
            ],
        )

    @router.post("/v1/key-aliases", response_model=KeyAliasChangeResponse, status_code=201)
    def create_alias(request: KeyAliasCreateRequest) -> KeyAliasChangeResponse:
        require_enabled()
        try:
            alias = service().create(
                profile_id=DEFAULT_PROFILE_ID,
                target_type=request.target_type,
                alias_key=request.alias_key,
                canonical_key=request.canonical_key,
                polarity=request.polarity,
                now=datetime.now(UTC),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="The key has no evidence.") from exc
        except KeyAliasError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return changed(alias, "model.key_alias_create")

    @router.post("/v1/key-aliases/review", response_model=KeyAliasChangeResponse)
    def review_alias(request: KeyAliasReviewRequest) -> KeyAliasChangeResponse:
        require_enabled()
        try:
            alias = service().review(
                profile_id=DEFAULT_PROFILE_ID,
                target_type=request.target_type,
                alias_key=request.alias_key,
                action=request.action,
                now=datetime.now(UTC),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Key alias was not found.") from exc
        except KeyAliasError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return changed(alias, f"model.key_alias_{request.action.value}")

    @router.post("/v1/key-aliases/remove", response_model=KeyAliasRemovalResponse)
    def remove_alias(request: KeyAliasTargetRequest) -> KeyAliasRemovalResponse:
        require_enabled()
        try:
            service().remove(DEFAULT_PROFILE_ID, request.target_type, request.alias_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Key alias was not found.") from exc
        snapshot_version = rebuild()
        audit(
            "model.key_alias_remove",
            {"target_type": request.target_type.value, "snapshot_version": snapshot_version},
        )
        return KeyAliasRemovalResponse(
            target_type=request.target_type.value,
            alias_key=request.alias_key,
            snapshot_version=snapshot_version,
        )

    return router
