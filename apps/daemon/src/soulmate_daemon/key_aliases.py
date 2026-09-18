"""Daemon composition and owner review workflow for canonical target key aliases."""

from dataclasses import replace
from datetime import datetime
from enum import StrEnum

from soulmate_core.domain import (
    EvidenceRepository,
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasRepository,
    TargetKeyAliasStatus,
)
from soulmate_core.keys import propose_normalized_aliases
from soulmate_core.preferences import ModelRebuilder
from soulmate_storage_sqlite import Repositories

from soulmate_daemon.config import Settings

OWNER_ALIAS_VERSION = "owner-alias-v1"


def alias_repository(
    repositories: Repositories, settings: Settings
) -> TargetKeyAliasRepository | None:
    """Return the alias repository, or ``None`` when the owner disabled aliases."""
    return repositories.key_aliases if settings.key_aliases.enabled else None


def model_rebuilder(repositories: Repositories, settings: Settings) -> ModelRebuilder:
    """Build the one rebuilder configuration every daemon workflow must share."""
    return ModelRebuilder(
        repositories.evidence,
        repositories.personal_models,
        alias_repository(repositories, settings),
    )


def register_normalized_aliases(
    evidence: EvidenceRepository,
    aliases: TargetKeyAliasRepository | None,
    profile_id: str,
    now: datetime,
) -> tuple[TargetKeyAlias, ...]:
    """Store active aliases for reviewed keys whose normalized forms are equal."""
    if aliases is None:
        return ()
    keys = tuple(
        (item.target_type, item.target_key) for item in evidence.list_for_profile(profile_id)
    )
    stored: list[TargetKeyAlias] = []
    for proposal in propose_normalized_aliases(
        profile_id, keys, aliases.list_for_profile(profile_id), now
    ):
        try:
            stored.append(aliases.upsert(proposal))
        except ValueError:
            # A concurrent owner change closed a cycle; keep the keys separate.
            continue
    return tuple(stored)


class KeyAliasReviewAction(StrEnum):
    """Owner decisions on an existing alias."""

    APPROVE = "approve"
    REJECT = "reject"
    INVERT = "invert"


class KeyAliasError(ValueError):
    """An alias change conflicts with alias rules or current state."""


class KeyAliasService:
    """Owner-only alias changes; every write invalidates the current model snapshot."""

    def __init__(self, evidence: EvidenceRepository, aliases: TargetKeyAliasRepository) -> None:
        self._evidence = evidence
        self._aliases = aliases

    def list_for_profile(self, profile_id: str) -> tuple[TargetKeyAlias, ...]:
        return self._aliases.list_for_profile(profile_id)

    def create(
        self,
        *,
        profile_id: str,
        target_type: EvidenceTargetType,
        alias_key: str,
        canonical_key: str,
        polarity: int,
        now: datetime,
    ) -> TargetKeyAlias:
        """Merge a used key into another key as an owner decision."""
        alias_key = alias_key.strip()
        canonical_key = canonical_key.strip()
        used = {
            item.target_key
            for item in self._evidence.list_for_profile(profile_id)
            if item.target_type is target_type
        }
        if alias_key not in used:
            raise KeyError(alias_key)
        existing = self._aliases.get(profile_id, target_type, alias_key)
        try:
            alias = TargetKeyAlias(
                profile_id=profile_id,
                target_type=target_type,
                alias_key=alias_key,
                canonical_key=canonical_key,
                polarity=polarity,
                method=TargetKeyAliasMethod.OWNER,
                status=TargetKeyAliasStatus.ACTIVE,
                algorithm_version=OWNER_ALIAS_VERSION,
                created_at=now if existing is None else existing.created_at,
                updated_at=now,
            )
            return self._aliases.upsert(alias)
        except ValueError as exc:
            raise KeyAliasError(str(exc)) from exc

    def review(
        self,
        *,
        profile_id: str,
        target_type: EvidenceTargetType,
        alias_key: str,
        action: KeyAliasReviewAction,
        now: datetime,
    ) -> TargetKeyAlias:
        """Approve, reject, or invert an alias; rejection is kept so it is not re-proposed."""
        alias = self._aliases.get(profile_id, target_type, alias_key)
        if alias is None:
            raise KeyError(alias_key)
        if action is KeyAliasReviewAction.REJECT:
            changed = replace(alias, status=TargetKeyAliasStatus.REJECTED, updated_at=now)
        elif action is KeyAliasReviewAction.APPROVE:
            changed = replace(alias, status=TargetKeyAliasStatus.ACTIVE, updated_at=now)
        else:
            if alias.target_type is not EvidenceTargetType.PREFERENCE:
                raise KeyAliasError("Only preference aliases can invert polarity.")
            changed = replace(
                alias,
                polarity=-alias.polarity,
                status=TargetKeyAliasStatus.ACTIVE,
                updated_at=now,
            )
        try:
            return self._aliases.upsert(changed)
        except ValueError as exc:
            raise KeyAliasError(str(exc)) from exc

    def remove(self, profile_id: str, target_type: EvidenceTargetType, alias_key: str) -> None:
        """Delete an alias; automatic aliases may be proposed again unless rejected."""
        if not self._aliases.remove(profile_id, target_type, alias_key):
            raise KeyError(alias_key)
