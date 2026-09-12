"""Add Phase 8 active learning, outcome, and advice schema.

Revision ID: 0006_phase_8
Revises: 0005_phase_7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase_8"
down_revision: str | None = "0005_phase_7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_outcomes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("satisfaction", sa.Float(), nullable=False),
        sa.Column("regret", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "satisfaction >= 0 AND satisfaction <= 1", name="ck_outcomes_satisfaction"
        ),
        sa.ForeignKeyConstraint(["decision_id"], ["decision_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["raw_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index(
        "ix_decision_outcomes_profile_created",
        "decision_outcomes",
        ["profile_id", "created_at", "id"],
    )
    op.create_table(
        "decision_advice",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("behavioral_prediction_id", sa.String(), nullable=False),
        sa.Column("ranking_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale_json", sa.Text(), nullable=False),
        sa.Column("supporting_outcome_ids_json", sa.Text(), nullable=False),
        sa.Column("model_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_advice_confidence"),
        sa.ForeignKeyConstraint(
            ["behavioral_prediction_id"], ["decision_predictions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["decision_id"], ["decision_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id", "model_snapshot_version"],
            ["user_model_snapshots.profile_id", "user_model_snapshots.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_advice_decision_created",
        "decision_advice",
        ["decision_id", "created_at", "id"],
    )
    op.create_table(
        "active_questions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("preference_keys_json", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("option_a_label", sa.Text(), nullable=False),
        sa.Column("option_a_features_json", sa.Text(), nullable=False),
        sa.Column("option_b_label", sa.Text(), nullable=False),
        sa.Column("option_b_features_json", sa.Text(), nullable=False),
        sa.Column("information_gain_score", sa.Float(), nullable=False),
        sa.Column("model_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "information_gain_score >= 0 AND information_gain_score <= 1",
            name="ck_active_questions_information_gain",
        ),
        sa.CheckConstraint("status IN ('pending', 'answered')", name="ck_active_questions_status"),
        sa.ForeignKeyConstraint(
            ["profile_id", "model_snapshot_version"],
            ["user_model_snapshots.profile_id", "user_model_snapshots.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_active_questions_profile_status",
        "active_questions",
        ["profile_id", "status", "created_at"],
    )
    op.create_table(
        "question_answers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("question_id", sa.String(), nullable=False),
        sa.Column("choice", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("choice IN ('a', 'b')", name="ck_question_answers_choice"),
        sa.ForeignKeyConstraint(["question_id"], ["active_questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["raw_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id"),
    )


def downgrade() -> None:
    op.drop_table("question_answers")
    op.drop_index("ix_active_questions_profile_status", table_name="active_questions")
    op.drop_table("active_questions")
    op.drop_index("ix_decision_advice_decision_created", table_name="decision_advice")
    op.drop_table("decision_advice")
    op.drop_index("ix_decision_outcomes_profile_created", table_name="decision_outcomes")
    op.drop_table("decision_outcomes")
