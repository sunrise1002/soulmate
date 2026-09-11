"""Add Phase 3 conversation and extraction provenance schema.

Revision ID: 0003_phase_3
Revises: 0002_phase_2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase_3"
down_revision: str | None = "0002_phase_2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_profile_updated", "conversations", ["profile_id", "updated_at"]
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider_model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at", "id"]
    )
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("extractor_model", sa.String(), nullable=True))
        batch.add_column(sa.Column("source_message_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_source_message",
            "messages",
            ["source_message_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_evidence_source_message", ["source_message_id"])


def downgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.drop_index("ix_evidence_source_message")
        batch.drop_constraint("fk_evidence_source_message", type_="foreignkey")
        batch.drop_column("source_message_id")
        batch.drop_column("extractor_model")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_profile_updated", table_name="conversations")
    op.drop_table("conversations")
