-- One schema and one login role per environment, so staging can never touch production tables.
-- Run once per environment as an admin, passing the name and a fresh password:
--   psql "$ADMIN_URL" -v env=staging -v pw="$(openssl rand -hex 24)" -f deploy/postgres-env-setup.sql
-- The role's search_path is fixed to its schema, so the app's unqualified table names land there.
\set ON_ERROR_STOP on
SELECT set_config('saarthi.env', :'env', false);
SELECT format('saarthi_%s', :'env') AS role_name \gset
CREATE SCHEMA IF NOT EXISTS :"env";
CREATE ROLE :"role_name" LOGIN PASSWORD :'pw';
GRANT USAGE, CREATE ON SCHEMA :"env" TO :"role_name";
ALTER SCHEMA :"env" OWNER TO :"role_name";
ALTER ROLE :"role_name" SET search_path = :"env";
REVOKE ALL ON SCHEMA public FROM :"role_name";
-- Supabase API roles must not reach Saarthi tables (they live outside the exposed schemas anyway).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM anon, authenticated', current_setting('saarthi.env', true));
  END IF;
END $$;
