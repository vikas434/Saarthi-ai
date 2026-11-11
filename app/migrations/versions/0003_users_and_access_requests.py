"""Sign-in: each call belongs to a user; sign-ins from outside the allow-list are recorded.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("user_id", sa.Text, nullable=True))
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "access_requests",
        sa.Column("email", sa.Text, primary_key=True),
        sa.Column("first_seen", sa.Text, nullable=False),
        sa.Column("last_seen", sa.Text, nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("access_requests")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("user_id")
