"""Persistence for owner key labels and the derived key vectors built from them."""

import json
import struct
from collections.abc import Collection
from datetime import UTC, datetime

from soulmate_core.domain.models import (
    EvidenceTargetType,
    TargetKeyEmbedding,
    TargetKeyLabel,
    TargetKeyLabelSource,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from soulmate_storage_sqlite.schema import TargetKeyCatalogRow, TargetKeyEmbeddingRow

_OWNER = TargetKeyLabelSource.OWNER.value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _pack(vector: tuple[float, ...]) -> bytes:
    """Store vectors little-endian so a database file stays portable across devices."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(raw: bytes, dim: int) -> tuple[float, ...]:
    if len(raw) != dim * 4:
        raise ValueError("Stored key vector length does not match its dimension.")
    return struct.unpack(f"<{dim}f", raw)


def _aliases(raw: str) -> tuple[str, ...]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Stored key label aliases are not valid JSON.") from exc
    if not isinstance(decoded, list) or any(not isinstance(value, str) for value in decoded):
        raise ValueError("Stored key label aliases must be a list of strings.")
    return tuple(decoded)


class SqliteTargetKeyCatalogRepository:
    """Store one label per key, keeping owner edits safe from later extraction."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def upsert(self, entry: TargetKeyLabel) -> TargetKeyLabel:
        """Insert or update a label; an extracted label never replaces an owner label."""
        with self._sessions.begin() as session:
            row = session.get(
                TargetKeyCatalogRow, (entry.profile_id, entry.target_type.value, entry.key)
            )
            if (
                row is not None
                and row.label_source == _OWNER
                and entry.source is not (TargetKeyLabelSource.OWNER)
            ):
                return self._to_domain(row)
            if row is None:
                row = TargetKeyCatalogRow(
                    profile_id=entry.profile_id,
                    target_type=entry.target_type.value,
                    key=entry.key,
                    created_at=entry.created_at,
                )
                session.add(row)
            row.label = entry.label
            row.aliases_json = json.dumps(list(entry.aliases), ensure_ascii=False)
            row.label_source = entry.source.value
            row.updated_at = entry.updated_at
            session.flush()
            return self._to_domain(row)

    def get(
        self, profile_id: str, target_type: EvidenceTargetType, key: str
    ) -> TargetKeyLabel | None:
        with self._sessions() as session:
            row = session.get(TargetKeyCatalogRow, (profile_id, target_type.value, key))
            return None if row is None else self._to_domain(row)

    def list_for_profile(self, profile_id: str) -> tuple[TargetKeyLabel, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(TargetKeyCatalogRow)
                .where(TargetKeyCatalogRow.profile_id == profile_id)
                .order_by(TargetKeyCatalogRow.target_type, TargetKeyCatalogRow.key)
            )
            return tuple(self._to_domain(row) for row in rows)

    def remove(self, profile_id: str, target_type: EvidenceTargetType, key: str) -> bool:
        with self._sessions.begin() as session:
            row = session.get(TargetKeyCatalogRow, (profile_id, target_type.value, key))
            if row is None:
                return False
            session.delete(row)
            return True

    @staticmethod
    def _to_domain(row: TargetKeyCatalogRow) -> TargetKeyLabel:
        return TargetKeyLabel(
            profile_id=row.profile_id,
            target_type=EvidenceTargetType(row.target_type),
            key=row.key,
            label=row.label,
            aliases=_aliases(row.aliases_json),
            source=TargetKeyLabelSource(row.label_source),
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )


class SqliteTargetKeyEmbeddingRepository:
    """Store derived key vectors; they are rebuildable and never exported."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def replace_many(self, embeddings: Collection[TargetKeyEmbedding]) -> int:
        """Write every vector, replacing any earlier vector of the same key and model."""
        if not embeddings:
            return 0
        with self._sessions.begin() as session:
            for embedding in embeddings:
                row = session.get(
                    TargetKeyEmbeddingRow,
                    (
                        embedding.profile_id,
                        embedding.target_type.value,
                        embedding.key,
                        embedding.model_id,
                    ),
                )
                if row is None:
                    row = TargetKeyEmbeddingRow(
                        profile_id=embedding.profile_id,
                        target_type=embedding.target_type.value,
                        key=embedding.key,
                        model_id=embedding.model_id,
                    )
                    session.add(row)
                row.text_hash = embedding.text_hash
                row.dim = embedding.dim
                row.vector = _pack(embedding.vector)
                row.created_at = embedding.created_at
            return len(embeddings)

    def list_for_model(self, profile_id: str, model_id: str) -> tuple[TargetKeyEmbedding, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(TargetKeyEmbeddingRow)
                .where(
                    TargetKeyEmbeddingRow.profile_id == profile_id,
                    TargetKeyEmbeddingRow.model_id == model_id,
                )
                .order_by(TargetKeyEmbeddingRow.target_type, TargetKeyEmbeddingRow.key)
            )
            return tuple(self._to_domain(row) for row in rows)

    def remove_other_models(self, profile_id: str, model_id: str) -> int:
        """Drop vectors of every other model, because only one model is active."""
        with self._sessions.begin() as session:
            stale = list(
                session.scalars(
                    select(TargetKeyEmbeddingRow).where(
                        TargetKeyEmbeddingRow.profile_id == profile_id,
                        TargetKeyEmbeddingRow.model_id != model_id,
                    )
                )
            )
            for row in stale:
                session.delete(row)
            return len(stale)

    @staticmethod
    def _to_domain(row: TargetKeyEmbeddingRow) -> TargetKeyEmbedding:
        return TargetKeyEmbedding(
            profile_id=row.profile_id,
            target_type=EvidenceTargetType(row.target_type),
            key=row.key,
            model_id=row.model_id,
            text_hash=row.text_hash,
            vector=_unpack(row.vector, row.dim),
            created_at=_utc(row.created_at),
        )
