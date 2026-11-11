"""Initial schema: the tables the prototype created.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("scenario_id", sa.Text, nullable=False),
        sa.Column("agent_name", sa.Text, nullable=False),
        sa.Column("started_at", sa.Text, nullable=False),
        sa.Column("ended_at", sa.Text),
        sa.Column("done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("score", sa.Float),
        sa.Column("report", sa.Text),
        sa.Column("mode", sa.Text),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("agent_text", sa.Text),
        sa.Column("customer_text", sa.Text, nullable=False),
        sa.Column("coach", sa.Text),
    )
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("body", sa.Text, nullable=False),
    )
    op.create_table(
        "kv",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )


def downgrade() -> None:
    for table in ("kv", "scenarios", "turns", "sessions"):
        op.drop_table(table)
