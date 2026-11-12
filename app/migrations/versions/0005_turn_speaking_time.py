"""Speaking time per spoken reply, for pace and talk-time analytics.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Seconds the agent spoke for this reply; NULL for typed replies.
    with op.batch_alter_table("turns") as batch:
        batch.add_column(sa.Column("agent_seconds", sa.Float, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.drop_column("agent_seconds")
