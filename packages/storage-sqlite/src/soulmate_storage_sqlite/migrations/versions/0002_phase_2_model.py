"""Add Phase 2 evidence and Personal Model schema.

Revision ID: 0002_phase_2
Revises: 0001_phase_1
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase_2"
down_revision: str | None = "0001_phase_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _derived_table(name: str, *, preference: bool = False) -> None:
    columns: list[Any] = [
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("context_key", sa.String(), nullable=False),
    ]
    if preference:
        columns.extend(
            [
                sa.Column("value", sa.Float(), nullable=False),
                sa.Column("uncertainty", sa.Float(), nullable=False),
            ]
        )
    else:
        columns.append(sa.Column("value_json", sa.Text(), nullable=False))
    columns.extend(
        [
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("context_json", sa.Text(), nullable=False),
            sa.Column("supporting_evidence_ids_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("model_version", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("profile_id", "key", "context_key"),
        ]
    )
    op.create_table(name, *columns)


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_key", sa.String(), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("extractor_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('fact', 'preference', 'goal', 'constraint')",
            name="ck_evidence_target_type",
        ),
        sa.CheckConstraint("strength >= 0 AND strength <= 1", name="ck_evidence_strength_range"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_evidence_confidence_range"
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["raw_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_profile_target", "evidence", ["profile_id", "target_key"])
    op.create_index("ix_evidence_source_event", "evidence", ["source_event_id"])
    op.create_table(
        "evidence_revisions",
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    _derived_table("preferences", preference=True)
    op.create_index("ix_preferences_profile_key", "preferences", ["profile_id", "key"])
    _derived_table("facts")
    _derived_table("goals")
    _derived_table("constraints")
    op.create_table(
        "user_model_snapshots",
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("evidence_revision", sa.Integer(), nullable=False),
        sa.Column("model_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id", "version"),
    )
    op.create_index(
        "ix_user_model_snapshots_profile_version",
        "user_model_snapshots",
        ["profile_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_model_snapshots_profile_version", table_name="user_model_snapshots")
    op.drop_table("user_model_snapshots")
    op.drop_table("constraints")
    op.drop_table("goals")
    op.drop_table("facts")
    op.drop_index("ix_preferences_profile_key", table_name="preferences")
    op.drop_table("preferences")
    op.drop_table("evidence_revisions")
    op.drop_index("ix_evidence_source_event", table_name="evidence")
    op.drop_index("ix_evidence_profile_target", table_name="evidence")
    op.drop_table("evidence")
