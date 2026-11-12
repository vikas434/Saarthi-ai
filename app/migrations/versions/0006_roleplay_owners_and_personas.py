"""Roleplays get an owner and a visibility; personas get their own table.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing custom scenarios were made by the admin for everyone: they stay published.
    with op.batch_alter_table("scenarios") as batch:
        batch.add_column(sa.Column("owner_id", sa.Text, nullable=True))
        batch.add_column(
            sa.Column("visibility", sa.Text, nullable=False, server_default="published")
        )
        batch.add_column(sa.Column("updated_at", sa.Text, nullable=True))
    op.create_index("ix_scenarios_owner_id", "scenarios", ["owner_id"])
    op.create_table(
        "personas",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("ix_personas_owner_id", "personas", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_personas_owner_id", table_name="personas")
    op.drop_table("personas")
    op.drop_index("ix_scenarios_owner_id", table_name="scenarios")
    with op.batch_alter_table("scenarios") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("visibility")
        batch.drop_column("owner_id")
