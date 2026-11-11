"""Alembic environment. Migrations always run on a connection handed over by app.db."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Run migrations through app.db (python -m app.db upgrade).")

context.configure(connection=connection)
with context.begin_transaction():
    context.run_migrations()
