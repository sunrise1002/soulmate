"""Write records the way an older revision did, before newer columns existed."""

from datetime import datetime

from soulmate_storage_sqlite import Database
from sqlalchemy import text

LEGACY_RAW_EVENT = text(
    "INSERT INTO raw_events "
    "(id, profile_id, source_id, event_type, content_json, created_at, ingested_at, sensitivity) "
    "VALUES (:id, :profile_id, NULL, :event_type, '{}', :created_at, :created_at, 'normal')"
)


LEGACY_EVIDENCE = text(
    "INSERT INTO evidence "
    "(id, profile_id, target_type, target_key, value_json, strength, confidence, context_json, "
    "source_type, source_event_id, extractor_version, extractor_model, source_message_id, "
    "created_at) VALUES "
    "(:id, :profile_id, :target_type, :target_key, :value_json, 1.0, 1.0, '{}', "
    "'explicit_statement', :source_event_id, 'synthetic-v1', NULL, NULL, :created_at)"
)


def insert_legacy_raw_event(
    database: Database,
    event_id: str,
    profile_id: str,
    created_at: datetime,
    event_type: str = "synthetic",
) -> str:
    """Insert a raw event using only the columns that predate migration 0012."""
    if database.engine is None:
        raise RuntimeError("The database must be connected.")
    with database.engine.begin() as connection:
        connection.execute(
            LEGACY_RAW_EVENT,
            {
                "id": event_id,
                "profile_id": profile_id,
                "event_type": event_type,
                "created_at": created_at,
            },
        )
    return event_id


def insert_legacy_evidence(
    database: Database,
    evidence_id: str,
    profile_id: str,
    target_key: str,
    created_at: datetime,
    value_json: str = "0.8",
    target_type: str = "preference",
) -> str:
    """Insert evidence and its raw event without reading newer columns."""
    if database.engine is None:
        raise RuntimeError("The database must be connected.")
    event_id = insert_legacy_raw_event(database, f"event_{evidence_id}", profile_id, created_at)
    with database.engine.begin() as connection:
        connection.execute(
            LEGACY_EVIDENCE,
            {
                "id": evidence_id,
                "profile_id": profile_id,
                "target_type": target_type,
                "target_key": target_key,
                "value_json": value_json,
                "source_event_id": event_id,
                "created_at": created_at,
            },
        )
    return evidence_id
