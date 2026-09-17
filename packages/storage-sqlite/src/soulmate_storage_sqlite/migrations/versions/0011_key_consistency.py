"""Add target key aliases, the key label catalog, and derived key embeddings.

Revision ID: 0011_key_consistency
Revises: 0010_phase_12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_key_consistency"
down_revision: str | None = "0010_phase_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_TYPES = "target_type IN ('fact', 'preference', 'goal', 'constraint')"


def upgrade() -> None:
    op.create_table(
        "target_key_aliases",
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("alias_key", sa.String(), nullable=False),
        sa.Column("canonical_key", sa.String(), nullable=False),
        sa.Column("polarity", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(TARGET_TYPES, name="ck_target_key_aliases_target_type"),
        sa.CheckConstraint("polarity IN (1, -1)", name="ck_target_key_aliases_polarity"),
        sa.CheckConstraint(
            "polarity = 1 OR target_type = 'preference'",
            name="ck_target_key_aliases_inversion",
        ),
        sa.CheckConstraint(
            "method IN ('normalized', 'semantic', 'owner')",
            name="ck_target_key_aliases_method",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suggested', 'rejected')",
            name="ck_target_key_aliases_status",
        ),
        sa.CheckConstraint(
            "similarity IS NULL OR (similarity >= 0 AND similarity <= 1)",
            name="ck_target_key_aliases_similarity",
        ),
        sa.CheckConstraint("alias_key <> canonical_key", name="ck_target_key_aliases_distinct"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id", "target_type", "alias_key"),
    )
    op.create_index(
        "ix_target_key_aliases_canonical",
        "target_key_aliases",
        ["profile_id", "target_type", "canonical_key"],
    )
    op.create_index("ix_target_key_aliases_status", "target_key_aliases", ["profile_id", "status"])
    op.create_table(
        "target_key_catalog",
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("aliases_json", sa.Text(), nullable=False),
        sa.Column("label_source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(TARGET_TYPES, name="ck_target_key_catalog_target_type"),
        sa.CheckConstraint(
            "label_source IN ('extracted', 'owner')",
            name="ck_target_key_catalog_label_source",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id", "target_type", "key"),
    )
    op.create_table(
        "target_key_embeddings",
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(TARGET_TYPES, name="ck_target_key_embeddings_target_type"),
        sa.CheckConstraint("dim > 0", name="ck_target_key_embeddings_dim"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id", "target_type", "key", "model_id"),
    )


def downgrade() -> None:
    op.drop_table("target_key_embeddings")
    op.drop_table("target_key_catalog")
    op.drop_index("ix_target_key_aliases_status", table_name="target_key_aliases")
    op.drop_index("ix_target_key_aliases_canonical", table_name="target_key_aliases")
    op.drop_table("target_key_aliases")
