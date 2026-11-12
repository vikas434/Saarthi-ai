"""Sessions get a kind (roleplay or tutor) and a plan (a tutor's lesson and answer keys).

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("kind", sa.Text, nullable=False, server_default="roleplay"))
        # Server-side only: a tutor lesson with its answer keys and the learner's answers.
        batch.add_column(sa.Column("plan", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("plan")
        batch.drop_column("kind")
