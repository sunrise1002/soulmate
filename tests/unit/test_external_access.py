"""Verify least-privilege external identity rules without infrastructure."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from soulmate_core.access import (
    DECISION_PREDICT,
    PREFERENCE_SUMMARY_READ,
    ExternalAccessError,
    ExternalIdentityService,
)
from soulmate_core.domain import ApiCredential, ServiceIdentity

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


class MemoryIdentities:
    def __init__(self) -> None:
        self.items: dict[str, ServiceIdentity] = {}

    def add(self, identity: ServiceIdentity) -> None:
        self.items[identity.id] = identity

    def get(self, identity_id: str) -> ServiceIdentity | None:
        return self.items.get(identity_id)

    def list_for_profile(self, profile_id: str) -> tuple[ServiceIdentity, ...]:
        return tuple(item for item in self.items.values() if item.profile_id == profile_id)

    def replace_scopes(self, identity_id: str, scopes: tuple[str, ...]) -> bool:
        identity = self.items.get(identity_id)
        if identity is None:
            return False
        self.items[identity_id] = replace(identity, scopes=scopes)
        return True

    def revoke(self, identity_id: str, revoked_at: datetime) -> bool:
        identity = self.items.get(identity_id)
        if identity is None or not identity.is_active:
            return False
        self.items[identity_id] = replace(identity, revoked_at=revoked_at)
        return True


class MemoryCredentials:
    def __init__(self) -> None:
        self.items: dict[str, ApiCredential] = {}

    def add(self, credential: ApiCredential) -> None:
        self.items[credential.id] = credential

    def get(self, credential_id: str) -> ApiCredential | None:
        return self.items.get(credential_id)

    def list_for_identity(self, identity_id: str) -> tuple[ApiCredential, ...]:
        return tuple(
            item for item in self.items.values() if item.service_identity_id == identity_id
        )

    def touch(self, credential_id: str, last_used_at: datetime) -> None:
        self.items[credential_id] = replace(self.items[credential_id], last_used_at=last_used_at)

    def revoke(self, credential_id: str, revoked_at: datetime) -> bool:
        credential = self.items.get(credential_id)
        if credential is None or not credential.is_active:
            return False
        self.items[credential_id] = replace(credential, revoked_at=revoked_at)
        return True


def _service() -> tuple[ExternalIdentityService, MemoryIdentities, MemoryCredentials]:
    identities = MemoryIdentities()
    credentials = MemoryCredentials()
    identifiers = iter(("identity", "credential", "rotated"))
    service = ExternalIdentityService(
        identities,
        credentials,
        secret_factory=lambda: "synthetic-secret-with-enough-entropy",
        id_factory=lambda: next(identifiers),
    )
    return service, identities, credentials


def test_api_key_is_returned_once_while_only_its_hash_is_stored() -> None:
    service, _, credentials = _service()

    issued = service.create(
        profile_id="profile_default",
        name="Shopping agent",
        description=None,
        scopes=(PREFERENCE_SUMMARY_READ, DECISION_PREDICT),
        now=NOW,
    )

    assert issued.api_key.startswith("sk_soulmate.credential_")
    assert issued.api_key not in repr(credentials.items)
    assert "synthetic-secret" not in repr(credentials.items)
    principal = service.authenticate(issued.api_key, NOW)
    assert principal.identity.id == issued.identity.id
    assert credentials.items[issued.credential.id].last_used_at == NOW


def test_unknown_scopes_and_wrong_api_keys_are_rejected() -> None:
    service, _, _ = _service()

    with pytest.raises(ExternalAccessError, match="Unknown permission scope"):
        service.create(
            profile_id="profile_default",
            name="Agent",
            description=None,
            scopes=("memory:read",),
            now=NOW,
        )

    with pytest.raises(ExternalAccessError):
        service.authenticate("sk_soulmate.missing.wrong", NOW)


def test_scope_changes_and_revocation_take_effect_immediately() -> None:
    service, _, _ = _service()
    issued = service.create(
        profile_id="profile_default",
        name="Calendar agent",
        description=None,
        scopes=(DECISION_PREDICT,),
        now=NOW,
    )
    principal = service.authenticate(issued.api_key, NOW)

    with pytest.raises(ExternalAccessError, match=PREFERENCE_SUMMARY_READ):
        service.require_scope(principal, PREFERENCE_SUMMARY_READ)

    updated = service.replace_scopes(
        "profile_default", issued.identity.id, (PREFERENCE_SUMMARY_READ,)
    )
    assert updated.scopes == (PREFERENCE_SUMMARY_READ,)
    service.revoke_identity("profile_default", issued.identity.id, NOW)

    with pytest.raises(ExternalAccessError, match="not active"):
        service.authenticate(issued.api_key, NOW)
