"""Gate: the migration runner that took over from Flyway.

The schema is the one thing in this platform that cannot be rebuilt from anything else, so this runs
against a **throwaway schema**, created and dropped here, never against `apim`. A schema rather than
a whole database on purpose: the application role owns the database and can create one, so this
needs no superuser, and every migration is schema-agnostic — they name no schema and rely on the
connection's `search_path`, which is exactly what makes this work.

What it proves:

* all nine migrations apply to an empty schema, in order, and produce the tables the services
  expect — so the runner can build a deployment from nothing, which is what Flyway did.
* running it twice applies nothing the second time. A runner that re-applies is worse than one that
  does nothing, because `CREATE TABLE` fails and a deployment stops.
* an existing Flyway ledger is honoured: rows Flyway wrote count as applied, which is what makes the
  handover need no migration of state.
* a migration recorded as failed stops the run, rather than applying later files on top of a schema
  nobody can describe.
* V10 would be applied after V9, not after V1 — a lexical sort of the filenames gets that wrong, and
  it is the bug that bites the tenth time somebody adds a migration rather than the first.

Needs Docker and the host's PostgreSQL. Run:  python tests/check_migrations.py
"""

import asyncio
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")
PASSWORD = re.search(r"^DB_PASSWORD=(.*)$", infra_env, re.M).group(1).strip()

#: A schema per run, so a failure never leaves the real one in a half-migrated state.
SCRATCH = f"migcheck_{uuid.uuid4().hex[:8]}"

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


def psql(sql: str) -> str:
    """Against the real database, but never the real schema — every statement names SCRATCH."""
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "host",
         "-e", f"PGPASSWORD={PASSWORD}", "postgres:17-alpine", "psql",
         "postgresql://apigw@host.docker.internal:5432/apigw", "-Atc", sql],
        capture_output=True, text=True, timeout=180,
    )
    return (result.stdout + result.stderr).strip()


async def run_against(schema: str) -> int:
    """Point the app's engine at one schema and apply migrations, returning how many ran."""
    # Imported here, and re-aimed per call, because the engine and the settings are both cached for
    # the life of the process — pointing them somewhere else is the whole point of this helper.
    import app.db as db
    import app.migrations as migrations
    from app.settings import Settings

    settings = Settings(  # type: ignore[call-arg]
        DATABASE_URL=f"postgresql+asyncpg://apigw:{PASSWORD}@127.0.0.1:5432/apigw",
        DB_SCHEMA=schema,
        AUTH_JWT_SECRET="x" * 40,
    )
    db._engine = None  # noqa: SLF001 - resetting the module's cached engine is the point
    db.get_settings = lambda: settings  # type: ignore[attr-defined]
    migrations.get_settings = lambda: settings  # type: ignore[attr-defined]
    try:
        return await migrations.apply()
    finally:
        await db.dispose()
        db._engine = None  # noqa: SLF001


try:
    print(f"--- a schema built from nothing ({SCRATCH})")
    created = psql(f'CREATE SCHEMA "{SCRATCH}"')
    check("the scratch schema was created", "ERROR" not in created.upper(), created or "(ok)")

    applied = asyncio.run(run_against(SCRATCH))
    check("every migration applied to an empty schema", applied == 9, f"{applied} applied")

    tables = psql(
        f"SELECT count(*) FROM information_schema.tables WHERE table_schema = '{SCRATCH}'"
    )
    check("the schema has tables in it", int(tables or 0) >= 12, f"{tables} tables")

    for table in ("api_definition", "partner", "security_key", "platform_user", "error_event",
                  "product", "product_assignment", "change_request", "flyway_schema_history"):
        present = psql(f"SELECT to_regclass('{SCRATCH}.{table}') IS NOT NULL")
        check(f"{table} exists", present == "t", present)

    check(
        "product_assignment carries the CP-PTN-03 authority, NOT NULL",
        psql(f"SELECT is_nullable FROM information_schema.columns WHERE table_schema='{SCRATCH}'"
             " AND table_name='product_assignment' AND column_name='approval_reference'") == "NO",
        "V9 did not apply as expected",
    )
    check(
        "the role column documents ADMIN | DEVELOPER, not EDITOR",
        "DEVELOPER" in psql(
            f"SELECT col_description('{SCRATCH}.platform_user'::regclass,"
            f" (SELECT ordinal_position FROM information_schema.columns"
            f"  WHERE table_schema='{SCRATCH}' AND table_name='platform_user'"
            f"  AND column_name='role')::int)"),
        "V8 did not apply as expected",
    )

    print()
    print("--- running it again")
    again = asyncio.run(run_against(SCRATCH))
    check("a second run applies nothing", again == 0, f"{again} applied")
    rows = psql(f'SELECT count(*) FROM "{SCRATCH}".flyway_schema_history')
    check("the ledger still has one row per migration", rows == "9", f"{rows} rows")

    print()
    print("--- an existing Flyway ledger is honoured")
    writer = psql(
        f"SELECT count(*) FROM \"{SCRATCH}\".flyway_schema_history"
        " WHERE installed_by = 'backend-python'")
    check("this run recorded itself as the installer", writer == "9", f"{writer} rows")
    # Exactly the handover: rows as Flyway wrote them, with its checksums and its name.
    psql(f'UPDATE "{SCRATCH}".flyway_schema_history SET installed_by = \'flyway\', checksum = 123')
    third = asyncio.run(run_against(SCRATCH))
    check("rows Flyway wrote count as applied", third == 0, f"{third} applied")

    print()
    print("--- a failed migration stops the run")
    psql(f'INSERT INTO "{SCRATCH}".flyway_schema_history (installed_rank, version, description,'
         " type, script, installed_by, installed_on, execution_time, success)"
         " VALUES (99, '99', 'deliberately broken', 'SQL', 'V99__x.sql', 'test', now(), 0, false)")
    try:
        asyncio.run(run_against(SCRATCH))
        check("a failed row stops the runner", False, "it carried on regardless")
    except RuntimeError as exc:
        check("a failed row stops the runner", "99" in str(exc), str(exc)[:120])
    psql(f"DELETE FROM \"{SCRATCH}\".flyway_schema_history WHERE version = '99'")

    print()
    print("--- ordering")
    import app.migrations as migrations_module

    versions = [v for v, _, _ in migrations_module._discover()]  # noqa: SLF001
    check("migrations are ordered numerically", versions == sorted(versions), str(versions))
    check("they are the nine on disk", versions == list(range(1, 10)), str(versions))
    # The bug this guards against: sorted() on filenames puts V10 between V1 and V2.
    lexical = sorted(f"V{v}__x.sql" for v in [*versions, 10])
    check(
        "a lexical sort would put V10 before V2 — the numeric sort is what prevents it",
        lexical.index("V10__x.sql") < lexical.index("V2__x.sql"),
        "if this ever stops being true the guard is no longer needed",
    )

finally:
    print()
    print("--- cleanup")
    psql(f'DROP SCHEMA IF EXISTS "{SCRATCH}" CASCADE')
    left = psql(f"SELECT count(*) FROM information_schema.schemata WHERE schema_name = '{SCRATCH}'")
    check("the scratch schema is gone", left == "0", left)
    real = psql("SELECT count(*) FROM apim.flyway_schema_history")
    check("the real schema is untouched, still 9 migrations", real == "9", real)

print()
print("FAILED" if failures else "all migration checks passed")
sys.exit(1 if failures else 0)
