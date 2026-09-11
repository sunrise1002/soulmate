"""Add Phase 4 decision prediction schema.

Revision ID: 0004_phase_4
Revises: 0003_phase_3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase_4"
down_revision: str | None = "0003_phase_3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_decision_events_status"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_events_profile_created",
        "decision_events",
        ["profile_id", "created_at", "id"],
    )
    op.create_table(
        "decision_options",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("features_json", sa.Text(), nullable=False),
        sa.Column("feature_confidence", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "feature_confidence >= 0 AND feature_confidence <= 1",
            name="ck_decision_options_feature_confidence",
        ),
        sa.ForeignKeyConstraint(["decision_id"], ["decision_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_options_decision", "decision_options", ["decision_id", "id"])
    op.create_table(
        "decision_predictions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("ranking_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("important_factors_json", sa.Text(), nullable=False),
        sa.Column("uncertain_factors_json", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("similar_decision_ids_json", sa.Text(), nullable=False),
        sa.Column("model_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_predictions_confidence"),
        sa.ForeignKeyConstraint(["decision_id"], ["decision_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id", "model_snapshot_version"],
            ["user_model_snapshots.profile_id", "user_model_snapshots.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_predictions_decision_created",
        "decision_predictions",
        ["decision_id", "created_at", "id"],
    )
    op.create_table(
        "decision_resolutions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("chosen_option_id", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decision_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chosen_option_id"], ["decision_options.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_event_id"], ["raw_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index("ix_decision_resolutions_choice", "decision_resolutions", ["chosen_option_id"])


def downgrade() -> None:
    op.drop_index("ix_decision_resolutions_choice", table_name="decision_resolutions")
    op.drop_table("decision_resolutions")
    op.drop_index("ix_decision_predictions_decision_created", table_name="decision_predictions")
    op.drop_table("decision_predictions")
    op.drop_index("ix_decision_options_decision", table_name="decision_options")
    op.drop_table("decision_options")
    op.drop_index("ix_decision_events_profile_created", table_name="decision_events")
    op.drop_table("decision_events")
