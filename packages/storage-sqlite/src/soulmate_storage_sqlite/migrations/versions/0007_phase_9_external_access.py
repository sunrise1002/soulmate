"""Add Phase 9 external service identities, scopes, and API-key hashes.

Revision ID: 0007_phase_9
Revises: 0006_phase_8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_phase_9"
down_revision: str | None = "0006_phase_8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_identities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_identities_profile_created",
        "service_identities",
        ["profile_id", "created_at", "id"],
    )
    op.create_table(
        "service_identity_scopes",
        sa.Column("service_identity_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_identity_id"], ["service_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("service_identity_id", "scope"),
    )
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("service_identity_id", sa.String(), nullable=False),
        sa.Column("secret_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_identity_id"], ["service_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_hash"),
    )
    op.create_index(
        "ix_api_credentials_identity_created",
        "api_credentials",
        ["service_identity_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_credentials_identity_created", table_name="api_credentials")
    op.drop_table("api_credentials")
    op.drop_table("service_identity_scopes")
    op.drop_index("ix_service_identities_profile_created", table_name="service_identities")
    op.drop_table("service_identities")
