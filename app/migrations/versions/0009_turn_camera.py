"""Turns get the agent's on-camera numbers for that reply (no images, only percentages).

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        # JSON: {"frames", "face_pct", "eye_contact_pct", "smile_pct", "tense_pct"}
        batch.add_column(sa.Column("camera", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.drop_column("camera")
