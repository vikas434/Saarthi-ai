"""Usage: tokens and cost of every model call, for caps and the cost view.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text),
        sa.Column("user_id", sa.Text),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("ix_usage_created_at", "usage", ["created_at"])
    op.create_index("ix_usage_session_id", "usage", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_session_id", table_name="usage")
    op.drop_index("ix_usage_created_at", table_name="usage")
    op.drop_table("usage")
