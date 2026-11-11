# 0002: Postgres in deployment, SQLite locally, one store behind DATABASE_URL

- Status: accepted
- Date: 2026-11-11

## Context
Saarthi is moving to Railway. SQLite there needs a volume, ties the app to one instance and makes backups manual. Sign-in (Phase 4) and cost tracking (Phase 7) add tables, so schema changes need a repeatable step. Local runs and tests should stay one command with no database server.

## Decision
- `app/store.py` keeps its functions and talks to the database through SQLAlchemy Core (`text()` queries with named parameters). The same SQL runs on SQLite and Postgres; upserts use `INSERT ... ON CONFLICT ... DO UPDATE`, which both support.
- `DATABASE_URL` picks the database. Unset means SQLite at `SAARTHI_DB` (default `data/saarthi.db`). `postgres://` and `postgresql://` URLs are normalised to the `psycopg` (v3) driver.
- Schema changes are Alembic migrations in `app/migrations/versions/`, numbered `0001_...`. The app upgrades to head the first time it opens a database; on Postgres the upgrade holds an advisory lock so two instances can't migrate at once. `python -m app.db upgrade` does the same by hand or as a Railway pre-deploy step. A SQLite file made by the prototype (tables, no version row) is stamped at 0001 instead of re-created.
- Column types stay as they were (JSON and timestamps as text) so behaviour does not change in this step. Typed columns can follow in a later migration if queries need them.
- Tests and evals never read the app's database: `tests/conftest.py`, `app/evals.py` and the browser smoke test set their own `DATABASE_URL` (a throwaway SQLite file, or `TEST_DATABASE_URL` when CI provides Postgres).
- Production host: Supabase Postgres in ap-south-1, one project with a `staging` and a `production` schema, each reached by its own role whose `search_path` is fixed to that schema. If Supabase can't be used, Railway Postgres is the fallback; nothing in the code depends on Supabase.

## Alternatives
- Plain `psycopg` plus hand-written SQLite branches: fewer dependencies, but two code paths to test.
- An ORM with models: more code than the six small tables need.
- Hand-rolled migration runner: Alembic is the standard tool and handles both dialects.

## Consequences
- New dependencies: `sqlalchemy`, `alembic`, `psycopg[binary]`.
- Every schema change from now on is a migration and is tested on both databases in CI.
- The Supabase project's API layer is not used; Saarthi tables live outside the `public` schema, which keeps them off the auto-generated REST API.
