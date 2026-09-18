"""Owner-only API for the owner-language names of target keys."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field
from soulmate_core.domain import AuditEvent, EvidenceTargetType, TargetKeyLabel

from soulmate_daemon.extraction import ALIAS_MAX_COUNT, LABEL_MAX_LENGTH
from soulmate_daemon.key_labels import KeyLabelError, KeyLabelService
from soulmate_daemon.runtime import runtime_of
from soulmate_daemon.system import DEFAULT_PROFILE_ID

KEY_NOT_FOUND = "The key has no evidence."
LABEL_NOT_FOUND = "The key has no label."


class KeyLabelResponse(BaseModel):
    target_type: str
    key: str
    label: str | None
    aliases: list[str]
    source: str
    created_at: datetime
    updated_at: datetime


class KeyLabelListResponse(BaseModel):
    labels: list[KeyLabelResponse]


class KeyLabelTargetRequest(BaseModel):
    target_type: EvidenceTargetType
    key: str = Field(min_length=1, max_length=200)


class KeyLabelRequest(KeyLabelTargetRequest):
    """An owner name for one key; aliases are other wordings the owner uses for it."""

    label: str | None = Field(default=None, max_length=LABEL_MAX_LENGTH)
    aliases: list[Annotated[str, Field(max_length=LABEL_MAX_LENGTH)]] = Field(
        default_factory=list, max_length=ALIAS_MAX_COUNT
    )


def _label_response(label: TargetKeyLabel) -> KeyLabelResponse:
    return KeyLabelResponse(
        target_type=label.target_type.value,
        key=label.key,
        label=label.label,
        aliases=list(label.aliases),
        source=label.source.value,
        created_at=label.created_at,
        updated_at=label.updated_at,
    )


def build_key_label_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    def service() -> KeyLabelService:
        repositories = runtime_of(app)["repositories"]
        return KeyLabelService(repositories.evidence, repositories.key_catalog)

    def audit(action: str, target_type: EvidenceTargetType, alias_count: int) -> None:
        # A label is the owner's own wording, so only its shape is recorded.
        runtime_of(app)["repositories"].audit_events.add(
            AuditEvent(
                id=f"audit_{uuid4().hex}",
                profile_id=DEFAULT_PROFILE_ID,
                action=action,
                actor_type="owner",
                actor_id=None,
                metadata={"target_type": target_type.value, "alias_count": alias_count},
                created_at=datetime.now(UTC),
            )
        )

    @router.get("/v1/key-labels", response_model=KeyLabelListResponse)
    def list_labels() -> KeyLabelListResponse:
        return KeyLabelListResponse(
            labels=[
                _label_response(item) for item in service().list_for_profile(DEFAULT_PROFILE_ID)
            ]
        )

    @router.post("/v1/key-labels", response_model=KeyLabelResponse)
    def set_label(request: KeyLabelRequest) -> KeyLabelResponse:
        try:
            label = service().set_label(
                profile_id=DEFAULT_PROFILE_ID,
                target_type=request.target_type,
                key=request.key,
                label=request.label,
                aliases=tuple(request.aliases),
                now=datetime.now(UTC),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=KEY_NOT_FOUND) from exc
        except KeyLabelError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit("model.key_label_set", label.target_type, len(label.aliases))
        return _label_response(label)

    @router.post("/v1/key-labels/remove", status_code=204)
    def remove_label(request: KeyLabelTargetRequest) -> None:
        try:
            service().remove(DEFAULT_PROFILE_ID, request.target_type, request.key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=LABEL_NOT_FOUND) from exc
        audit("model.key_label_remove", request.target_type, 0)

    return router
