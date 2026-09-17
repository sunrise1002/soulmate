"""Shared synthetic fixtures for target key alias persistence tests."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from soulmate_core.domain import (
    Evidence,
    EvidenceTargetType,
    Profile,
    RawEvent,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import text

PROFILE = "profile_keys"
NOW = datetime(2026, 9, 17, tzinfo=UTC)


def open_storage(path: Path, revision: str = "head") -> tuple[Database, Repositories]:
    database = Database(path)
    database.connect()
    command.upgrade(database.migration_config, revision)
    return database, Repositories(database.sessions())


def add_profile(repositories: Repositories, profile_id: str = PROFILE) -> None:
    repositories.profiles.add(Profile(profile_id, "Synthetic Owner", NOW))


def add_evidence(
    repositories: Repositories,
    evidence_id: str,
    key: str,
    value: object = 0.8,
    *,
    profile_id: str = PROFILE,
    target_type: EvidenceTargetType = EvidenceTargetType.PREFERENCE,
    source_event_id: str | None = None,
) -> None:
    if source_event_id is None:
        source_event_id = f"event_{evidence_id}"
        repositories.raw_events.add(
            RawEvent(source_event_id, profile_id, None, "synthetic", {}, NOW, NOW)
        )
    repositories.evidence.add(
        Evidence(
            id=evidence_id,
            profile_id=profile_id,
            target_type=target_type,
            target_key=key,
            value=value,
            strength=1.0,
            confidence=1.0,
            context={},
            source_type="explicit_statement",
            source_event_id=source_event_id,
            extractor_version="synthetic-v1",
            created_at=NOW,
        )
    )


def alias(
    alias_key: str,
    canonical_key: str,
    *,
    status: TargetKeyAliasStatus = TargetKeyAliasStatus.ACTIVE,
    polarity: int = 1,
    profile_id: str = PROFILE,
    target_type: EvidenceTargetType = EvidenceTargetType.PREFERENCE,
) -> TargetKeyAlias:
    return TargetKeyAlias(
        profile_id=profile_id,
        target_type=target_type,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=polarity,
        method=TargetKeyAliasMethod.NORMALIZED,
        status=status,
        algorithm_version="key-normalizer-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def semantic(value: TargetKeyAlias, similarity: float) -> TargetKeyAlias:
    return replace(value, method=TargetKeyAliasMethod.SEMANTIC, similarity=similarity)


def add_key_metadata(database: Database, key: str, profile_id: str = PROFILE) -> None:
    """Insert catalog and embedding rows directly; their repositories arrive in P5."""
    assert database.engine is not None
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO target_key_catalog (profile_id, target_type, key, label, "
                "aliases_json, label_source, created_at, updated_at) VALUES "
                "(:profile_id, 'preference', :key, 'giao diện tối', '[]', 'owner', :now, :now)"
            ),
            {"profile_id": profile_id, "key": key, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO target_key_embeddings (profile_id, target_type, key, model_id, "
                "text_hash, dim, vector, created_at) VALUES "
                "(:profile_id, 'preference', :key, 'fake-model', 'hash', 2, :vector, :now)"
            ),
            {"profile_id": profile_id, "key": key, "vector": b"\x00" * 8, "now": NOW},
        )


def metadata_keys(database: Database, table: str) -> set[str]:
    assert database.engine is not None
    with database.engine.connect() as connection:
        return {str(row[0]) for row in connection.execute(text(f"SELECT key FROM {table}"))}  # noqa: S608 -- fixed test table names.
