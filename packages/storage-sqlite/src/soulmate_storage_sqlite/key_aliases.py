"""Persistence for canonical target key aliases and evidence revision upkeep."""

from datetime import UTC, datetime

from soulmate_core.domain.models import (
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_core.keys import KeyAliasMap
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from soulmate_storage_sqlite.schema import (
    EvidenceRevisionRow,
    EvidenceRow,
    TargetKeyAliasRow,
    TargetKeyCatalogRow,
    TargetKeyEmbeddingRow,
)

type _TypedKey = tuple[str, str]

_ACTIVE = TargetKeyAliasStatus.ACTIVE.value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def bump_evidence_revision(session: Session, profile_id: str) -> None:
    """Advance the revision that marks derived model snapshots as stale."""
    statement = insert(EvidenceRevisionRow).values(profile_id=profile_id, revision=1)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[EvidenceRevisionRow.profile_id],
            set_={"revision": EvidenceRevisionRow.revision + 1},
        )
    )


def _supported_keys(
    session: Session, profile_id: str, aliases: list[TargetKeyAliasRow]
) -> set[_TypedKey]:
    supported: set[_TypedKey] = {
        (target_type, key)
        for target_type, key in session.execute(
            select(EvidenceRow.target_type, EvidenceRow.target_key)
            .where(EvidenceRow.profile_id == profile_id)
            .distinct()
        ).tuples()
    }
    active = [row for row in aliases if row.status == _ACTIVE]
    grown = True
    while grown:
        grown = False
        for row in active:
            canonical = (row.target_type, row.canonical_key)
            if (row.target_type, row.alias_key) in supported and canonical not in supported:
                supported.add(canonical)
                grown = True
    return supported


def _delete_keys(
    session: Session,
    profile_id: str,
    table: type[TargetKeyCatalogRow] | type[TargetKeyEmbeddingRow],
    keys: set[_TypedKey],
) -> None:
    if not keys:
        return
    session.execute(
        delete(table).where(
            table.profile_id == profile_id,
            or_(*(and_(table.target_type == kind, table.key == key) for kind, key in keys)),
        )
    )


def prune_unsupported_keys(session: Session, profile_id: str) -> None:
    """Remove key metadata that deleted evidence no longer supports.

    A key is supported when evidence uses it or when an active alias carries
    supported evidence onto it. Active aliases survive while their alias key is
    supported; suggested and rejected aliases need both keys supported. Catalog
    labels and embeddings survive only for supported keys, so deleted topics do
    not linger as key names.
    """
    aliases = list(
        session.scalars(select(TargetKeyAliasRow).where(TargetKeyAliasRow.profile_id == profile_id))
    )
    supported = _supported_keys(session, profile_id, aliases)
    for row in aliases:
        required = {(row.target_type, row.alias_key)}
        if row.status != _ACTIVE:
            required.add((row.target_type, row.canonical_key))
        if not required <= supported:
            session.delete(row)
    tables: tuple[type[TargetKeyCatalogRow | TargetKeyEmbeddingRow], ...] = (
        TargetKeyCatalogRow,
        TargetKeyEmbeddingRow,
    )
    for table in tables:
        stored = set(
            session.execute(
                select(table.target_type, table.key).where(table.profile_id == profile_id)
            ).tuples()
        )
        _delete_keys(session, profile_id, table, stored - supported)


class SqliteTargetKeyAliasRepository:
    """Store aliases by their natural key and keep the active alias graph acyclic."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def upsert(self, alias: TargetKeyAlias) -> TargetKeyAlias:
        """Insert or replace an alias, keeping its first ``created_at``.

        Raises ``ValueError`` when an active alias would close a cycle, and
        advances the evidence revision so the next model read rebuilds.
        """
        with self._sessions.begin() as session:
            if alias.status is TargetKeyAliasStatus.ACTIVE:
                self._require_acyclic(session, alias)
            row = session.get(
                TargetKeyAliasRow, (alias.profile_id, alias.target_type.value, alias.alias_key)
            )
            if row is None:
                row = TargetKeyAliasRow(
                    profile_id=alias.profile_id,
                    target_type=alias.target_type.value,
                    alias_key=alias.alias_key,
                    created_at=alias.created_at,
                )
                session.add(row)
            row.canonical_key = alias.canonical_key
            row.polarity = alias.polarity
            row.method = alias.method.value
            row.similarity = alias.similarity
            row.status = alias.status.value
            row.algorithm_version = alias.algorithm_version
            row.updated_at = alias.updated_at
            bump_evidence_revision(session, alias.profile_id)
            session.flush()
            return self._to_domain(row)

    def get(
        self, profile_id: str, target_type: EvidenceTargetType, alias_key: str
    ) -> TargetKeyAlias | None:
        with self._sessions() as session:
            row = session.get(TargetKeyAliasRow, (profile_id, target_type.value, alias_key))
            return None if row is None else self._to_domain(row)

    def list_for_profile(
        self, profile_id: str, status: TargetKeyAliasStatus | None = None
    ) -> tuple[TargetKeyAlias, ...]:
        statement = select(TargetKeyAliasRow).where(TargetKeyAliasRow.profile_id == profile_id)
        if status is not None:
            statement = statement.where(TargetKeyAliasRow.status == status.value)
        with self._sessions() as session:
            rows = session.scalars(
                statement.order_by(TargetKeyAliasRow.target_type, TargetKeyAliasRow.alias_key)
            )
            return tuple(self._to_domain(row) for row in rows)

    def remove(self, profile_id: str, target_type: EvidenceTargetType, alias_key: str) -> bool:
        with self._sessions.begin() as session:
            row = session.get(TargetKeyAliasRow, (profile_id, target_type.value, alias_key))
            if row is None:
                return False
            session.delete(row)
            bump_evidence_revision(session, profile_id)
            return True

    def _require_acyclic(self, session: Session, alias: TargetKeyAlias) -> None:
        others = (
            self._to_domain(row)
            for row in session.scalars(
                select(TargetKeyAliasRow).where(
                    TargetKeyAliasRow.profile_id == alias.profile_id,
                    TargetKeyAliasRow.target_type == alias.target_type.value,
                    TargetKeyAliasRow.status == _ACTIVE,
                    TargetKeyAliasRow.alias_key != alias.alias_key,
                )
            )
        )
        KeyAliasMap((*others, alias))

    @staticmethod
    def _to_domain(row: TargetKeyAliasRow) -> TargetKeyAlias:
        return TargetKeyAlias(
            profile_id=row.profile_id,
            target_type=EvidenceTargetType(row.target_type),
            alias_key=row.alias_key,
            canonical_key=row.canonical_key,
            polarity=row.polarity,
            method=TargetKeyAliasMethod(row.method),
            status=TargetKeyAliasStatus(row.status),
            algorithm_version=row.algorithm_version,
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
            similarity=row.similarity,
        )
