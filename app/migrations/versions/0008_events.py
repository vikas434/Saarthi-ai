"""Events for the admin's Insights: request timings and errors, model and voice fallbacks.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Text, nullable=False),
        # request | fallback
        sa.Column("kind", sa.Text, nullable=False),
        # A route template such as "POST /api/sessions/{sid}/turns", or what fell back.
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        # The sign-in id (never an email), so active people can be counted.
        sa.Column("user_id", sa.Text, nullable=True),
        # A short reason such as an exception class name. Never call text.
        sa.Column("detail", sa.Text, nullable=True),
    )
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_index("ix_events_kind_created_at", "events", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_events_kind_created_at", table_name="events")
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_table("events")
