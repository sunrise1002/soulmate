"""Add Decision I/O source provenance, event envelopes, and observations.

Revision ID: 0012_phase_13
Revises: 0011_key_consistency

Columns are added in place rather than through a batch table rebuild: SQLite
recreates a table to add a check constraint, and ``sources``, ``raw_events``,
``decision_events``, and ``decision_options`` are all foreign-key targets whose
children declare ``ON DELETE CASCADE``. For the same reason the new references on
existing tables are plain columns that the Decision I/O repository resolves and
removes explicitly. The domain records enforce the vocabulary for those columns;
the new observation tables carry their checks and foreign keys in the database.

The backfill is deliberately conservative. Nothing is assumed to be owner-authored,
consented, or eligible merely because it is stored locally.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_phase_13"
down_revision: str | None = "0011_key_consistency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTOR_TYPES = "actor_type IN ('owner', 'agent', 'assistant', 'system', 'third_party', 'unknown')"
OBSERVATION_STATUSES = "status IN ('unmatched', 'pending', 'confirmed', 'rejected')"
DISPOSITIONS = "IN ('accepted', 'modified', 'replaced', 'reverted', 'unknown')"

# Live local records the owner produced by using Soulmate itself.
OWNER_EVENT_TYPES = (
    "conversation_message",
    "preference_correction",
    "active_question_answer",
    "decision_resolution",
    "decision_outcome",
)


def upgrade() -> None:
    _upgrade_sources()
    _upgrade_raw_events()
    _upgrade_decisions()
    _create_observation_tables()


def _upgrade_sources() -> None:
    op.add_column("sources", sa.Column("provider", sa.String(), nullable=True))
    op.add_column(
        "sources",
        sa.Column(
            "acquisition_method",
            sa.String(),
            nullable=False,
            server_default="legacy_unverified",
        ),
    )
    op.add_column(
        "sources",
        sa.Column("consent_mode", sa.String(), nullable=False, server_default="legacy_unverified"),
    )
    op.add_column("sources", sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sources",
        sa.Column("data_classes_json", sa.Text(), nullable=False, server_default='["metadata"]'),
    )
    op.add_column(
        "sources",
        sa.Column("author_scope", sa.String(), nullable=False, server_default="mixed"),
    )
    op.add_column(
        "sources",
        sa.Column(
            "raw_retention_policy", sa.String(), nullable=False, server_default="metadata_only"
        ),
    )
    op.add_column("sources", sa.Column("adapter_version", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("parser_version", sa.String(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("policy_profile_version", sa.String(), nullable=False, server_default="legacy"),
    )
    op.add_column("sources", sa.Column("service_identity_id", sa.String(), nullable=True))
    # An import is an explicit owner action, and it stores whole conversations.
    op.execute(
        sa.text(
            "UPDATE sources SET acquisition_method = 'owner_import', "
            "consent_mode = 'owner_explicit', consent_at = created_at, "
            'data_classes_json = \'["metadata", "prompt", "response"]\', '
            "raw_retention_policy = 'full_content', provider = 'chat_import' "
            "WHERE source_type LIKE 'import:%'"
        )
    )
    op.create_index("ix_sources_profile_created", "sources", ["profile_id", "created_at", "id"])


def _upgrade_raw_events() -> None:
    op.add_column(
        "raw_events",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("raw_events", sa.Column("external_event_id", sa.String(), nullable=True))
    op.add_column(
        "raw_events",
        sa.Column("actor_type", sa.String(), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "raw_events",
        sa.Column(
            "evidence_eligibility", sa.String(), nullable=False, server_default="contextual_only"
        ),
    )
    op.add_column("raw_events", sa.Column("correlation_id", sa.String(), nullable=True))
    op.add_column("raw_events", sa.Column("causation_event_id", sa.String(), nullable=True))
    op.add_column("raw_events", sa.Column("content_fingerprint", sa.String(), nullable=True))
    # Only records the owner created locally in Soulmate are owner-authored.
    # Imported and connector events keep 'unknown' and stay contextual only.
    events = sa.table(
        "raw_events",
        sa.column("actor_type", sa.String()),
        sa.column("evidence_eligibility", sa.String()),
        sa.column("event_type", sa.String()),
        sa.column("source_id", sa.String()),
    )
    op.execute(
        events.update()
        .where(events.c.source_id.is_(None), events.c.event_type.in_(OWNER_EVENT_TYPES))
        .values(actor_type="owner", evidence_eligibility="eligible")
    )
    op.create_index("ix_raw_events_correlation", "raw_events", ["profile_id", "correlation_id"])
    op.create_index(
        "uq_raw_events_source_external",
        "raw_events",
        ["source_id", "external_event_id"],
        unique=True,
        sqlite_where=sa.text("external_event_id IS NOT NULL"),
    )


def _upgrade_decisions() -> None:
    op.add_column(
        "decision_events",
        sa.Column("origin", sa.String(), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "decision_events",
        sa.Column("purpose", sa.String(), nullable=False, server_default="owner_interactive"),
    )
    op.add_column("decision_events", sa.Column("source_id", sa.String(), nullable=True))
    op.add_column("decision_events", sa.Column("external_decision_id", sa.String(), nullable=True))
    op.add_column("decision_events", sa.Column("source_event_id", sa.String(), nullable=True))
    op.create_index("ix_decision_events_source", "decision_events", ["source_id"])
    op.create_index(
        "uq_decision_events_source_external",
        "decision_events",
        ["source_id", "external_decision_id"],
        unique=True,
        sqlite_where=sa.text("external_decision_id IS NOT NULL"),
    )
    op.add_column("decision_options", sa.Column("external_option_id", sa.String(), nullable=True))
    op.create_index(
        "uq_decision_options_external",
        "decision_options",
        ["decision_id", "external_option_id"],
        unique=True,
        sqlite_where=sa.text("external_option_id IS NOT NULL"),
    )
    # A stored outcome whose actor cannot be proven keeps its visibility but not
    # the trust of an owner confirmation.
    op.add_column(
        "decision_outcomes",
        sa.Column("attribution", sa.String(), nullable=False, server_default="legacy_unverified"),
    )


def _create_observation_tables() -> None:
    op.create_table(
        "resolution_observations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=True),
        sa.Column("external_decision_id", sa.String(), nullable=True),
        sa.Column("chosen_option_id", sa.String(), nullable=True),
        sa.Column("external_option_id", sa.String(), nullable=True),
        sa.Column("correlation_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_code", sa.String(), nullable=True),
        sa.CheckConstraint(ACTOR_TYPES, name="ck_resolution_observations_actor_type"),
        sa.CheckConstraint(OBSERVATION_STATUSES, name="ck_resolution_observations_status"),
        sa.CheckConstraint(
            f"disposition {DISPOSITIONS}", name="ck_resolution_observations_disposition"
        ),
        sa.CheckConstraint(
            "decision_id IS NOT NULL OR external_decision_id IS NOT NULL",
            name="ck_resolution_observations_decision_reference",
        ),
        sa.CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_resolution_observations_confirmation",
        ),
        sa.CheckConstraint(
            "correlation_confidence IS NULL OR "
            "(correlation_confidence >= 0 AND correlation_confidence <= 1)",
            name="ck_resolution_observations_confidence",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["raw_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["decision_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chosen_option_id"], ["decision_options.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_resolution_observations_profile_status",
        "resolution_observations",
        ["profile_id", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_resolution_observations_decision", "resolution_observations", ["decision_id"]
    )
    op.create_index("ix_resolution_observations_source", "resolution_observations", ["source_id"])
    op.create_index(
        "ix_resolution_observations_external",
        "resolution_observations",
        ["profile_id", "external_decision_id"],
    )
    op.create_table(
        "outcome_observations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=True),
        sa.Column("external_decision_id", sa.String(), nullable=True),
        sa.Column("technical_status", sa.String(), nullable=True),
        sa.Column("disposition", sa.String(), nullable=True),
        sa.Column("satisfaction", sa.Float(), nullable=True),
        sa.Column("regret", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_code", sa.String(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('technical', 'user_behavior', 'owner_reported')",
            name="ck_outcome_observations_kind",
        ),
        sa.CheckConstraint(ACTOR_TYPES, name="ck_outcome_observations_actor_type"),
        sa.CheckConstraint(OBSERVATION_STATUSES, name="ck_outcome_observations_status"),
        sa.CheckConstraint(
            "technical_status IS NULL OR "
            "technical_status IN ('succeeded', 'failed', 'partial', 'unknown')",
            name="ck_outcome_observations_technical_values",
        ),
        sa.CheckConstraint(
            f"disposition IS NULL OR disposition {DISPOSITIONS}",
            name="ck_outcome_observations_disposition_values",
        ),
        sa.CheckConstraint(
            "(kind = 'technical') = (technical_status IS NOT NULL)",
            name="ck_outcome_observations_technical_status",
        ),
        sa.CheckConstraint(
            "(kind = 'user_behavior') = (disposition IS NOT NULL)",
            name="ck_outcome_observations_disposition",
        ),
        sa.CheckConstraint(
            "kind = 'owner_reported' OR (satisfaction IS NULL AND regret IS NULL)",
            name="ck_outcome_observations_wellbeing_scope",
        ),
        sa.CheckConstraint(
            "kind <> 'owner_reported' OR (satisfaction IS NOT NULL AND regret IS NOT NULL)",
            name="ck_outcome_observations_wellbeing_complete",
        ),
        sa.CheckConstraint(
            "satisfaction IS NULL OR (satisfaction >= 0 AND satisfaction <= 1)",
            name="ck_outcome_observations_satisfaction",
        ),
        sa.CheckConstraint(
            "decision_id IS NOT NULL OR external_decision_id IS NOT NULL",
            name="ck_outcome_observations_decision_reference",
        ),
        sa.CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_outcome_observations_confirmation",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["raw_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["decision_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outcome_observations_profile_status",
        "outcome_observations",
        ["profile_id", "status", "created_at", "id"],
    )
    op.create_index("ix_outcome_observations_decision", "outcome_observations", ["decision_id"])
    op.create_index("ix_outcome_observations_source", "outcome_observations", ["source_id"])
    op.create_index(
        "ix_outcome_observations_external",
        "outcome_observations",
        ["profile_id", "external_decision_id"],
    )


def downgrade() -> None:
    op.drop_table("outcome_observations")
    op.drop_table("resolution_observations")
    op.drop_column("decision_outcomes", "attribution")
    op.drop_index("uq_decision_options_external", table_name="decision_options")
    op.drop_column("decision_options", "external_option_id")
    op.drop_index("uq_decision_events_source_external", table_name="decision_events")
    op.drop_index("ix_decision_events_source", table_name="decision_events")
    for column in ("source_event_id", "external_decision_id", "source_id", "purpose", "origin"):
        op.drop_column("decision_events", column)
    op.drop_index("uq_raw_events_source_external", table_name="raw_events")
    op.drop_index("ix_raw_events_correlation", table_name="raw_events")
    for column in (
        "content_fingerprint",
        "causation_event_id",
        "correlation_id",
        "evidence_eligibility",
        "actor_type",
        "external_event_id",
        "schema_version",
    ):
        op.drop_column("raw_events", column)
    op.drop_index("ix_sources_profile_created", table_name="sources")
    for column in (
        "service_identity_id",
        "policy_profile_version",
        "parser_version",
        "adapter_version",
        "raw_retention_policy",
        "author_scope",
        "data_classes_json",
        "consent_at",
        "consent_mode",
        "acquisition_method",
        "provider",
    ):
        op.drop_column("sources", column)
