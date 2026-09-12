"""Link imported conversations to deletable provenance sources.

Revision ID: 0008_phase_10
Revises: 0007_phase_9
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_phase_10"
down_revision: str | None = "0007_phase_9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations ADD COLUMN source_id VARCHAR "
        "REFERENCES sources(id) ON DELETE CASCADE"
    )
    op.create_index("ix_conversations_source", "conversations", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_source", table_name="conversations")
    op.drop_column("conversations", "source_id")
