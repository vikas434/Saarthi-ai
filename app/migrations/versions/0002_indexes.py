"""Indexes: one row per turn position, and newest-first session listing.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_turns_session_idx", "turns", ["session_id", "idx"], unique=True)
    op.create_index("ix_sessions_started_at", "sessions", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_started_at", table_name="sessions")
    op.drop_index("ix_turns_session_idx", table_name="turns")
