"""Verify migration 0012 upgrades a real 0011 database conservatively (P13-T14)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from soulmate_core.domain import (
    AcquisitionMethod,
    ConsentMode,
    DecisionOrigin,
    DecisionPurpose,
    EventActorType,
    EvidenceEligibility,
    OutcomeAttribution,
    RawRetentionPolicy,
)
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import inspect, text

from .legacy_schema import insert_legacy_raw_event

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 17, tzinfo=UTC)
PROFILE = "profile_legacy"
PHASE_13_TABLES = {"resolution_observations", "outcome_observations"}


def _legacy_database(tmp_path: Path) -> Database:
    """Build a revision 0011 database holding one record of every legacy kind."""
    database = Database(tmp_path / "soulmate.db")
    database.connect()
    command.upgrade(database.migration_config, "0011_key_consistency")
    assert database.engine is not None
    with database.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO profiles (id, display_name, created_at) VALUES (:id, NULL, :at)"),
            {"id": PROFILE, "at": NOW},
        )
        for source_id, source_type in (
            ("source_import", "import:chatgpt"),
            ("source_connector", "connector:local_notes"),
        ):
            connection.execute(
                text(
                    "INSERT INTO sources (id, profile_id, source_type, name, created_at) "
                    "VALUES (:id, :profile, :type, 'Synthetic', :at)"
                ),
                {"id": source_id, "profile": PROFILE, "type": source_type, "at": NOW},
            )
    insert_legacy_raw_event(database, "event_chat", PROFILE, NOW, "conversation_message")
    insert_legacy_raw_event(database, "event_resolution", PROFILE, NOW, "decision_resolution")
    insert_legacy_raw_event(database, "event_outcome", PROFILE, NOW, "decision_outcome")
    insert_legacy_raw_event(database, "event_unknown", PROFILE, NOW, "synthetic")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_events (id, profile_id, source_id, event_type, content_json, "
                "created_at, ingested_at, sensitivity) VALUES ('event_imported', :profile, "
                "'source_import', 'imported_chat_message', '{}', :at, :at, 'normal')"
            ),
            {"profile": PROFILE, "at": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO decision_events (id, profile_id, domain, question, context_json, "
                "status, created_at) VALUES ('decision_legacy', :profile, 'code', "
                "'Synthetic?', '{}', 'resolved', :at)"
            ),
            {"profile": PROFILE, "at": NOW},
        )
        for option_id in ("option_a", "option_b"):
            connection.execute(
                text(
                    "INSERT INTO decision_options (id, decision_id, label, description, "
                    "features_json, feature_confidence) VALUES (:id, 'decision_legacy', :id, "
                    "'Synthetic option', '{\"code.simplicity\": 1.0}', 1.0)"
                ),
                {"id": option_id},
            )
        connection.execute(
            text(
                "INSERT INTO decision_resolutions (id, decision_id, chosen_option_id, "
                "source_event_id, created_at) VALUES ('resolution_legacy', 'decision_legacy', "
                "'option_a', 'event_resolution', :at)"
            ),
            {"at": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO decision_outcomes (id, decision_id, profile_id, satisfaction, "
                "regret, notes, source_event_id, created_at) VALUES ('outcome_legacy', "
                "'decision_legacy', :profile, 0.7, 0, NULL, 'event_outcome', :at)"
            ),
            {"profile": PROFILE, "at": NOW},
        )
    return database


def test_upgrade_backfills_provenance_without_inventing_trust(tmp_path: Path) -> None:
    # Given: a real 0011 database with imports, connectors, live events, and outcomes
    database = _legacy_database(tmp_path)
    # When: it migrates to 0012
    database.migrate()
    assert database.session_factory is not None
    repositories = Repositories(database.session_factory)
    # Then: only locally created owner records become owner-authored and eligible
    for event_id in ("event_chat", "event_resolution", "event_outcome"):
        event = repositories.raw_events.get(event_id)
        assert event is not None
        assert event.provenance.actor_type is EventActorType.OWNER
        assert event.provenance.evidence_eligibility is EvidenceEligibility.ELIGIBLE
    for event_id in ("event_imported", "event_unknown"):
        event = repositories.raw_events.get(event_id)
        assert event is not None
        assert event.provenance.actor_type is EventActorType.UNKNOWN
        assert event.provenance.evidence_eligibility is EvidenceEligibility.CONTEXTUAL_ONLY
    # And: an import is an explicit owner acquisition; a connector is left unverified
    imported = repositories.sources.get("source_import")
    connector = repositories.sources.get("source_connector")
    assert imported is not None and connector is not None
    assert imported.provenance.acquisition_method is AcquisitionMethod.OWNER_IMPORT
    assert imported.provenance.consent_mode is ConsentMode.OWNER_EXPLICIT
    assert imported.provenance.raw_retention_policy is RawRetentionPolicy.FULL_CONTENT
    assert connector.provenance.acquisition_method is AcquisitionMethod.LEGACY_UNVERIFIED
    assert connector.provenance.consent_mode is ConsentMode.LEGACY_UNVERIFIED
    # And: the decision stays readable with legacy provenance, and its outcome keeps
    # visibility without gaining the trust of an owner confirmation
    stored = repositories.decisions.get("decision_legacy")
    assert stored is not None
    assert stored[0].origin is DecisionOrigin.LEGACY
    assert stored[0].purpose is DecisionPurpose.OWNER_INTERACTIVE
    assert repositories.decisions.get_resolution("decision_legacy") is not None
    outcome = repositories.outcomes.get_for_decision("decision_legacy")
    assert outcome is not None
    assert outcome.attribution is OutcomeAttribution.LEGACY_UNVERIFIED
    assert database.current_revision() == "0012_phase_13"
    database.close()


def test_downgrade_to_0011_keeps_legacy_records_and_re_upgrade_is_clean(
    tmp_path: Path,
) -> None:
    # Given: a legacy database upgraded to 0012
    database = _legacy_database(tmp_path)
    database.migrate()
    assert database.engine is not None
    assert set(inspect(database.engine).get_table_names()) >= PHASE_13_TABLES
    # When: it is downgraded to 0011
    command.downgrade(database.migration_config, "0011_key_consistency")
    # Then: the Phase 13 tables and columns disappear while legacy rows remain
    assert not PHASE_13_TABLES & set(inspect(database.engine).get_table_names())
    columns = {item["name"] for item in inspect(database.engine).get_columns("raw_events")}
    assert "actor_type" not in columns
    with database.engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM raw_events")).scalar_one()
    assert count == 5
    # And: upgrading again re-applies the same conservative backfill
    database.migrate()
    assert database.session_factory is not None
    event = Repositories(database.session_factory).raw_events.get("event_chat")
    assert event is not None
    assert event.provenance.actor_type is EventActorType.OWNER
    database.close()
