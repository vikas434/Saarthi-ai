# 0002: Postgres in deployment, SQLite locally, one store behind DATABASE_URL

- Status: accepted
- Date: 2026-11-11

## Context
TalkWise is moving to Railway. SQLite there needs a volume, ties the app to one instance and makes backups manual. Sign-in (Phase 4) and cost tracking (Phase 7) add tables, so schema changes need a repeatable step. Local runs and tests should stay one command with no database server.

## Decision
- `app/store.py` keeps its functions and talks to the database through SQLAlchemy Core (`text()` queries with named parameters). The same SQL runs on SQLite and Postgres; upserts use `INSERT ... ON CONFLICT ... DO UPDATE`, which both support.
- `DATABASE_URL` picks the database. Unset means SQLite at `SAARTHI_DB` (default `data/saarthi.db`). `postgres://` and `postgresql://` URLs are normalised to the `psycopg` (v3) driver.
- Schema changes are Alembic migrations in `app/migrations/versions/`, numbered `0001_...`. The app upgrades to head the first time it opens a database; on Postgres the upgrade holds an advisory lock so two instances can't migrate at once. `python -m app.db upgrade` does the same by hand or as a Railway pre-deploy step. A SQLite file made by the prototype (tables, no version row) is stamped at 0001 instead of re-created.
- Column types stay as they were (JSON and timestamps as text) so behaviour does not change in this step. Typed columns can follow in a later migration if queries need them.
- Tests and evals never read the app's database: `tests/conftest.py`, `app/evals.py` and the browser smoke test set their own `DATABASE_URL` (a throwaway SQLite file, or `TEST_DATABASE_URL` when CI provides Postgres).
- Production host: Railway Postgres, one Postgres service in each Railway environment (`staging`, `production`), so the environments share nothing. The app gets `DATABASE_URL` as a reference to its own environment's Postgres over Railway's private network. Nothing in the code depends on the host.
- `deploy/postgres-env-setup.sql` (one schema and one login role per environment) is kept for a host where environments must share one database.

## Alternatives
- Plain `psycopg` plus hand-written SQLite branches: fewer dependencies, but two code paths to test.
- An ORM with models: more code than the six small tables need.
- Hand-rolled migration runner: Alembic is the standard tool and handles both dialects.

## Consequences
- New dependencies: `sqlalchemy`, `alembic`, `psycopg[binary]`.
- Every schema change from now on is a migration and is tested on both databases in CI.
- Supabase (first choice) could not be used: project creation was refused because of an overdue invoice in another organisation on the account. Railway Postgres also keeps the app and its database in one project and one bill, and never pauses for inactivity.
