-- One-time setup of a local PostgreSQL for the API Gateway platform backend.
--
-- Creates:  login role  apigw        (owner of the application's objects)
--           database    apigw
--           schema      apim         (all application tables live here)
--
-- Tables are NOT created here. Flyway creates them in schema apim, and records the history in
-- apim.flyway_schema_history, when the backend first starts with the "local" profile
-- (backend/src/main/resources/db/migration/V1__baseline.sql, V2__api_documentation.sql, ...).
--
-- Run as the PostgreSQL superuser, from a terminal (psql asks for passwords, input is hidden):
--   "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -f infra/postgres/local-setup.sql
--
-- Safe to re-run: existing role, database and schema are kept; you are asked for the apigw password again.

\set ON_ERROR_STOP on

-- 1. Application role (no password yet; set interactively at the end so it never sits in a file).
SELECT 'CREATE ROLE apigw LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'apigw') \gexec

-- 2. Database owned by the application role.
SELECT 'CREATE DATABASE apigw OWNER apigw ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'apigw') \gexec

\connect apigw

-- 3. Schema APIM (stored lowercase: apim), owned by the application role.
CREATE SCHEMA IF NOT EXISTS apim AUTHORIZATION apigw;

-- Unqualified names resolve to apim for this role, e.g. when you query with psql or pgAdmin as apigw.
ALTER ROLE apigw IN DATABASE apigw SET search_path = apim;

-- Nothing else may create objects in public in this database.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 4. The role still has no password. Set it yourself in an INTERACTIVE psql session:
--      "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d postgres
--      ALTER ROLE apigw WITH PASSWORD 'your-password';
--    (\password apigw is silently skipped when psql runs a file with -f, which is why it is not used here.)
--    Then put the same password in backend/config/application-local.yml (git-ignored).

\echo
\echo 'Done: database apigw, schema apim, role apigw.'
\echo 'NEXT: the apigw role has no password yet. In an interactive psql as postgres, run:'
\echo '  ALTER ROLE apigw WITH PASSWORD ''your-password'';'
\echo 'Put the same password in backend/config/application-local.yml, then start the backend'
\echo 'with profiles local,demo — Flyway creates the tables in apim.'
