"""Add owner policies and durable delegated-action approvals.

Revision ID: 0010_phase_12
Revises: 0009_phase_11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_phase_12"
down_revision: str | None = "0009_phase_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delegation_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("service_identity_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("impact", sa.String(), nullable=False),
        sa.Column("minimum_confidence", sa.Float(), nullable=False),
        sa.Column("allow_automatic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "impact IN ('low', 'medium', 'high', 'safety_critical')",
            name="ck_delegation_policies_impact",
        ),
        sa.CheckConstraint(
            "minimum_confidence >= 0 AND minimum_confidence <= 1",
            name="ck_delegation_policies_confidence",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["service_identity_id"], ["service_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_delegation_policies_identity_action",
        "delegation_policies",
        ["service_identity_id", "action_type"],
        unique=True,
    )
    op.create_index(
        "ix_delegation_policies_profile",
        "delegation_policies",
        ["profile_id", "created_at", "id"],
    )
    op.create_table(
        "delegation_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("service_identity_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=True),
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("prediction_id", sa.String(), nullable=False),
        sa.Column("external_request_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("action_label", sa.Text(), nullable=False),
        sa.Column("impact", sa.String(), nullable=False),
        sa.Column("predicted_option_id", sa.String(), nullable=False),
        sa.Column("prediction_confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "impact IN ('low', 'medium', 'high', 'safety_critical')",
            name="ck_delegation_requests_impact",
        ),
        sa.CheckConstraint(
            "prediction_confidence >= 0 AND prediction_confidence <= 1",
            name="ck_delegation_requests_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'completed', 'expired')",
            name="ck_delegation_requests_status",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["service_identity_id"], ["service_identities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["policy_id"], ["delegation_policies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_delegation_requests_identity_external",
        "delegation_requests",
        ["service_identity_id", "external_request_id"],
        unique=True,
    )
    op.create_index(
        "ix_delegation_requests_profile_status",
        "delegation_requests",
        ["profile_id", "status", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_delegation_requests_profile_status", table_name="delegation_requests")
    op.drop_index("ux_delegation_requests_identity_external", table_name="delegation_requests")
    op.drop_table("delegation_requests")
    op.drop_index("ix_delegation_policies_profile", table_name="delegation_policies")
    op.drop_index("ux_delegation_policies_identity_action", table_name="delegation_policies")
    op.drop_table("delegation_policies")
