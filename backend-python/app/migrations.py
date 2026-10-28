"""Schema migrations, taken over from Flyway.

Flyway lived in backend-java, which meant the schema existed only because that service had started.
This applies the same files, in the same order, against the same ledger — so the handover needs no
migration of state and nothing already applied is applied twice.

## What it does

`migrations/V<n>__<name>.sql` are applied in numeric order. Which ones have run is read from
`flyway_schema_history`, the table Flyway already maintains, keyed on `version`. Its nine existing
rows therefore count as applied on the first run under this code, exactly as they should.

**Checksums are not verified.** Flyway's checksum is a CRC32 of the file in its own encoding, and
reproducing it here would be guesswork; a wrong one would refuse to start a service whose schema is
perfectly fine. The version number is the key, and a migration file is immutable once applied —
which is the rule that makes checksums a belt on top of braces rather than the mechanism. Rows this
module writes carry a NULL checksum, which is also how you tell at a glance which runner applied
what.

## Why it holds a lock

Two instances starting together would otherwise both see V10 as unapplied and both run it. The lock
is a PostgreSQL advisory lock: held for the duration, released when the session ends, and taken on a
constant so every instance of this service contends for the same one. The second instance blocks,
then finds nothing left to do.

Flyway must be switched off in backend-java (`spring.flyway.enabled=false`) before this is used, or
the two race for the same ledger — and Flyway would refuse to start anyway, having found a row for a
migration whose file it can no longer see.
"""

import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy import text

from .db import engine

log = logging.getLogger(__name__)

#: Where the .sql files live, beside the application package.
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"

#: Any 64-bit constant; it only has to be the same in every instance of this service.
LOCK_ID = 8_241_907_553_110_942

_FILENAME = re.compile(r"^V(\d+)__(.+)\.sql$")


def _discover() -> list[tuple[int, str, Path]]:
    """Every migration on disk, in numeric order, as (version, description, path)."""
    found: list[tuple[int, str, Path]] = []
    for path in MIGRATIONS.glob("*.sql"):
        match = _FILENAME.match(path.name)
        if not match:
            # Named something else: a helper script, a note. Skipped rather than guessed at.
            log.warning("Ignoring %s — not a V<n>__<name>.sql migration", path.name)
            continue
        found.append((int(match.group(1)), match.group(2).replace("_", " "), path))
    # Sorted numerically, not lexically: V10 comes after V9, where a string sort puts it after V1.
    return sorted(found, key=lambda item: item[0])


async def _ledger_exists(conn) -> bool:  # type: ignore[no-untyped-def]
    row = (
        await conn.execute(text("SELECT to_regclass(:name) IS NOT NULL AS present"),
                           {"name": "flyway_schema_history"})
    ).first()
    return bool(row.present)


async def _create_ledger(conn) -> None:  # type: ignore[no-untyped-def]
    """The same shape Flyway creates, so a database built here is one Flyway would recognise."""
    await conn.execute(
        text(
            """
            CREATE TABLE flyway_schema_history (
                installed_rank INTEGER NOT NULL PRIMARY KEY,
                version        VARCHAR(50),
                description    VARCHAR(200) NOT NULL,
                type           VARCHAR(20)  NOT NULL,
                script         VARCHAR(1000) NOT NULL,
                checksum       INTEGER,
                installed_by   VARCHAR(100) NOT NULL,
                installed_on   TIMESTAMP NOT NULL DEFAULT now(),
                execution_time INTEGER NOT NULL,
                success        BOOLEAN NOT NULL
            )
            """
        )
    )
    log.info("Created flyway_schema_history — this database had none")


async def apply() -> int:
    """Apply whatever has not run yet. Returns how many were applied.

    Called once at startup. Raises if a migration fails, which stops the service: a half-migrated
    schema serving traffic is worse than one that will not start.
    """
    migrations = _discover()
    if not migrations:
        log.error("No migrations found at %s", MIGRATIONS)
        return 0

    applied = 0
    async with engine().begin() as conn:
        # Taken before anything is read: two instances must not both decide the same file is unrun.
        await conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": LOCK_ID})

        if not await _ledger_exists(conn):
            await _create_ledger(conn)

        rows = await conn.execute(text("SELECT version, success FROM flyway_schema_history"))
        done = {str(r.version): r.success for r in rows}

        failed = [v for v, ok in done.items() if not ok]
        if failed:
            # Flyway leaves a success=false row behind when a migration dies half-way. Continuing
            # would apply later files on top of a schema nobody can describe.
            raise RuntimeError(
                f"Migration(s) {', '.join(failed)} are recorded as failed. The schema is in an "
                "unknown state; repair it and remove the failed row before starting again."
            )

        rank = (
            await conn.execute(
                text("SELECT coalesce(max(installed_rank), 0) AS top FROM flyway_schema_history")
            )
        ).first().top

        for version, description, path in migrations:
            if str(version) in done:
                continue
            sql = path.read_text(encoding="utf-8")
            log.info("Applying V%s — %s", version, description)
            # Through the raw asyncpg connection, not conn.execute(text(...)): a migration file is a
            # script of many statements, and anything that goes via a prepared statement accepts
            # only one. asyncpg's own execute() uses the simple query protocol, which takes a whole
            # script. It joins the transaction opened above, so a failure still rolls the file back.
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(sql)
            rank += 1
            await conn.execute(
                text(
                    """
                    INSERT INTO flyway_schema_history
                        (installed_rank, version, description, type, script, checksum,
                         installed_by, installed_on, execution_time, success)
                    VALUES (:rank, :version, :description, 'SQL', :script, NULL,
                            'backend-python', now(), 0, true)
                    """
                ),
                {
                    "rank": rank,
                    "version": str(version),
                    "description": description,
                    "script": path.name,
                },
            )
            applied += 1

    if applied:
        log.info("Applied %d migration(s); schema is at V%s", applied, migrations[-1][0])
    else:
        log.info("Schema is up to date at V%s", migrations[-1][0])
    return applied


def fingerprint() -> str:
    """A short hash of every migration file, for a log line that makes two deployments comparable."""
    digest = hashlib.sha256()
    for _, _, path in _discover():
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
