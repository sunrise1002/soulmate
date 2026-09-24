"""Least-privilege service identities and hashed API-key credentials."""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from soulmate_core.domain import (
    ApiCredential,
    ApiCredentialRepository,
    ServiceIdentity,
    ServiceIdentityRepository,
)

API_KEY_PREFIX = "sk_soulmate"
API_KEY_SEPARATOR = "."
API_KEY_SECRET_BYTES = 32

AGENT_DELEGATE = "agent:delegate"
INTERACTION_RECORD = "interaction:record"
DECISION_RESOLUTION_RECORD = "decision:resolution:record"
OUTCOME_OBSERVE = "outcome:observe"
MODEL_SUMMARY_READ = "model:summary:read"
DECISION_PREDICT = "decision:predict"
DECISION_RECORD = "decision:record"
OUTCOME_RECORD = "outcome:record"
PREFERENCE_SUMMARY_READ = "preference:summary:read"

SERVICE_SCOPES = (
    AGENT_DELEGATE,
    DECISION_PREDICT,
    DECISION_RECORD,
    DECISION_RESOLUTION_RECORD,
    INTERACTION_RECORD,
    MODEL_SUMMARY_READ,
    OUTCOME_OBSERVE,
    OUTCOME_RECORD,
    PREFERENCE_SUMMARY_READ,
)


class ExternalAccessError(Exception):
    """An external identity or API-key rule rejected an operation."""


def validate_scopes(scopes: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted(set(scopes)))
    if not normalized:
        raise ExternalAccessError("At least one permission scope is required.")
    unknown = tuple(scope for scope in normalized if scope not in SERVICE_SCOPES)
    if unknown:
        raise ExternalAccessError(f"Unknown permission scope: {unknown[0]}")
    return normalized


def hash_api_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def format_api_key(credential_id: str, secret: str) -> str:
    return API_KEY_SEPARATOR.join((API_KEY_PREFIX, credential_id, secret))


def parse_api_key(api_key: str) -> tuple[str, str]:
    prefix, separator, remainder = api_key.partition(API_KEY_SEPARATOR)
    credential_id, separator_two, secret = remainder.partition(API_KEY_SEPARATOR)
    if (
        prefix != API_KEY_PREFIX
        or not separator
        or not separator_two
        or not credential_id
        or not secret
    ):
        raise ExternalAccessError("API credential is malformed.")
    return credential_id, secret


@dataclass(frozen=True, slots=True)
class IssuedApiCredential:
    identity: ServiceIdentity
    credential: ApiCredential
    api_key: str


@dataclass(frozen=True, slots=True)
class ExternalPrincipal:
    identity: ServiceIdentity
    credential: ApiCredential


class ExternalIdentityService:
    """Create, authenticate, scope, rotate, and revoke external identities."""

    def __init__(
        self,
        identities: ServiceIdentityRepository,
        credentials: ApiCredentialRepository,
        *,
        secret_factory: Callable[[], str] = lambda: secrets.token_urlsafe(API_KEY_SECRET_BYTES),
        id_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    ) -> None:
        self._identities = identities
        self._credentials = credentials
        self._secret_factory = secret_factory
        self._id_factory = id_factory

    def create(
        self,
        *,
        profile_id: str,
        name: str,
        description: str | None,
        scopes: tuple[str, ...],
        now: datetime,
    ) -> IssuedApiCredential:
        identity = ServiceIdentity(
            id=f"service_{self._id_factory()}",
            profile_id=profile_id,
            name=name.strip(),
            description=None if description is None else description.strip(),
            scopes=validate_scopes(scopes),
            created_at=now,
        )
        self._identities.add(identity)
        return self.issue_credential(identity.id, now)

    def issue_credential(self, identity_id: str, now: datetime) -> IssuedApiCredential:
        identity = self._active_identity(identity_id)
        secret = self._secret_factory()
        credential = ApiCredential(
            id=f"credential_{self._id_factory()}",
            service_identity_id=identity.id,
            secret_hash=hash_api_secret(secret),
            created_at=now,
        )
        self._credentials.add(credential)
        return IssuedApiCredential(
            identity=identity,
            credential=credential,
            api_key=format_api_key(credential.id, secret),
        )

    def authenticate(self, api_key: str, now: datetime) -> ExternalPrincipal:
        credential_id, secret = parse_api_key(api_key)
        credential = self._credentials.get(credential_id)
        if (
            credential is None
            or not credential.is_active
            or not hmac.compare_digest(hash_api_secret(secret), credential.secret_hash)
        ):
            raise ExternalAccessError("API credential is not recognized.")
        identity = self._active_identity(credential.service_identity_id)
        self._credentials.touch(credential.id, now)
        return ExternalPrincipal(identity=identity, credential=credential)

    def require_scope(self, principal: ExternalPrincipal, scope: str) -> None:
        if scope not in principal.identity.scopes:
            raise ExternalAccessError(f"The service identity lacks the '{scope}' scope.")

    def replace_scopes(
        self, profile_id: str, identity_id: str, scopes: tuple[str, ...]
    ) -> ServiceIdentity:
        identity = self._owned_identity(profile_id, identity_id)
        if not identity.is_active:
            raise ExternalAccessError("Service identity has been revoked.")
        normalized = validate_scopes(scopes)
        if not self._identities.replace_scopes(identity.id, normalized):
            raise ExternalAccessError("Service identity was not found.")
        updated = self._identities.get(identity.id)
        if updated is None:
            raise ExternalAccessError("Service identity was not found.")
        return updated

    def revoke_identity(self, profile_id: str, identity_id: str, now: datetime) -> ServiceIdentity:
        identity = self._owned_identity(profile_id, identity_id)
        if not self._identities.revoke(identity.id, now):
            raise ExternalAccessError("Service identity has already been revoked.")
        revoked = self._identities.get(identity.id)
        if revoked is None:
            raise ExternalAccessError("Service identity was not found.")
        return revoked

    def revoke_credential(
        self, profile_id: str, identity_id: str, credential_id: str, now: datetime
    ) -> ApiCredential:
        identity = self._owned_identity(profile_id, identity_id)
        credential = self._credentials.get(credential_id)
        if credential is None or credential.service_identity_id != identity.id:
            raise ExternalAccessError("API credential was not found.")
        if not self._credentials.revoke(credential.id, now):
            raise ExternalAccessError("API credential has already been revoked.")
        revoked = self._credentials.get(credential.id)
        if revoked is None:
            raise ExternalAccessError("API credential was not found.")
        return revoked

    def list_identities(self, profile_id: str) -> tuple[ServiceIdentity, ...]:
        return self._identities.list_for_profile(profile_id)

    def list_credentials(self, profile_id: str, identity_id: str) -> tuple[ApiCredential, ...]:
        identity = self._owned_identity(profile_id, identity_id)
        return self._credentials.list_for_identity(identity.id)

    def get_identity(self, profile_id: str, identity_id: str) -> ServiceIdentity:
        return self._owned_identity(profile_id, identity_id)

    def _active_identity(self, identity_id: str) -> ServiceIdentity:
        identity = self._identities.get(identity_id)
        if identity is None or not identity.is_active:
            raise ExternalAccessError("Service identity is not active.")
        return identity

    def _owned_identity(self, profile_id: str, identity_id: str) -> ServiceIdentity:
        identity = self._identities.get(identity_id)
        if identity is None or identity.profile_id != profile_id:
            raise ExternalAccessError("Service identity was not found.")
        return identity
