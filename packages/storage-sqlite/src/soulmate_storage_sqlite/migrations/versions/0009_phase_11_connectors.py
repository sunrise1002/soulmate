"""Add connector registrations, permissions, sync state, and item identities.

Revision ID: 0009_phase_11
Revises: 0008_phase_10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_phase_11"
down_revision: str | None = "0008_phase_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_registrations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("connector_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("granted_permissions_json", sa.Text(), nullable=False),
        sa.Column("configuration_json", sa.Text(), nullable=False),
        sa.Column("cursor_json", sa.Text(), nullable=True),
        sa.Column("sync_status", sa.String(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sync_status IN ('never', 'running', 'succeeded', 'failed')",
            name="ck_connector_registrations_sync_status",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index(
        "ux_connector_registrations_profile_connector",
        "connector_registrations",
        ["profile_id", "connector_id"],
        unique=True,
    )
    op.create_table(
        "connector_items",
        sa.Column("registration_id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("raw_event_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["registration_id"], ["connector_registrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["raw_event_id"], ["raw_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("registration_id", "external_id"),
        sa.UniqueConstraint("raw_event_id"),
    )


def downgrade() -> None:
    op.drop_table("connector_items")
    op.drop_index(
        "ux_connector_registrations_profile_connector",
        table_name="connector_registrations",
    )
    op.drop_table("connector_registrations")
