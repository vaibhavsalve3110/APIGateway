"""Gate: the demo seeder, ported from backend-java.

Run against a **throwaway schema**, never the real one — the whole risk of a seeder is that it writes
into a database that already means something.

What it proves:

* a fresh environment comes out usable: groups, partners with deterministic codes, APIs, people and
  a day of traffic, so the dashboard shows something rather than a flat line.
* **two administrators**, because approving a change needs one other than the requester and a demo
  with a single admin could not publish anything at all.
* **it refuses to touch a database that already has rows.** This is the guard that matters: the
  profile check is a string somebody can get wrong, an existing row is a fact.
* the traffic is relative to now, so a freshly seeded demo never opens on "no traffic in the last
  hour", which reads as an outage rather than as an empty fixture.

Run:  python tests/check_demo_seed.py
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
SCRATCH = f"seedcheck_{uuid.uuid4().hex[:8]}"

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


def psql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "host",
         "-e", f"PGPASSWORD={PASSWORD}", "postgres:17-alpine", "psql",
         "postgresql://apigw@host.docker.internal:5432/apigw", "-Atc", sql],
        capture_output=True, text=True, timeout=180,
    )
    return (result.stdout + result.stderr).strip()


async def main() -> None:
    import app.db as db
    import app.demo_seed as demo_seed
    import app.migrations as migrations
    from app.settings import Settings

    settings = Settings(  # type: ignore[call-arg]
        DATABASE_URL=f"postgresql+asyncpg://apigw:{PASSWORD}@127.0.0.1:5432/apigw",
        DB_SCHEMA=SCRATCH,
        AUTH_JWT_SECRET="x" * 40,
    )
    db._engine = None  # noqa: SLF001
    for module in (db, migrations, demo_seed):
        module.get_settings = lambda: settings  # type: ignore[attr-defined]

    try:
        print(f"--- a fresh environment ({SCRATCH})")
        psql(f'CREATE SCHEMA "{SCRATCH}"')
        await migrations.apply()

        seeded = await demo_seed.seed()
        check("the seeder wrote into the empty schema", seeded is True)

        check("four partner groups",
              psql(f'SELECT count(*) FROM "{SCRATCH}".partner_group') == "4")
        check("four partners, codes starting at PTN-00001",
              psql(f'SELECT string_agg(code, \',\' ORDER BY code) FROM "{SCRATCH}".partner')
              == "PTN-00001,PTN-00002,PTN-00003,PTN-00004")
        check("Acme is PTN-00001, as the designs and the demo realm expect",
              psql(f"SELECT code FROM \"{SCRATCH}\".partner WHERE name LIKE 'Acme%'") == "PTN-00001")
        check("six APIs, one of them withdrawn",
              psql(f'SELECT count(*) FROM "{SCRATCH}".api_definition') == "6"
              and psql(f"SELECT count(*) FROM \"{SCRATCH}\".api_definition"
                       " WHERE status = 'DISABLED'") == "1")
        check("a withdrawn API has a disabled_at, so the cooling period can be judged",
              psql(f"SELECT disabled_at IS NOT NULL FROM \"{SCRATCH}\".api_definition"
                   " WHERE status = 'DISABLED'") == "t")
        check("two active administrators, so a change can actually be approved",
              psql(f"SELECT count(*) FROM \"{SCRATCH}\".platform_user"
                   " WHERE role = 'ADMIN' AND status = 'ACTIVE'") == "2")
        check("nobody holds the old EDITOR role",
              psql(f"SELECT count(*) FROM \"{SCRATCH}\".platform_user"
                   " WHERE role = 'EDITOR'") == "0")
        check("partner users exist to sign in to the Developer Portal",
              int(psql(f'SELECT count(*) FROM "{SCRATCH}".partner_user')) >= 3)
        check("at least one API carries documentation partners can read",
              int(psql(f"SELECT count(*) FROM \"{SCRATCH}\".api_definition"
                       " WHERE documentation IS NOT NULL")) >= 1)

        print()
        print("--- the traffic is worth looking at")
        total = int(psql(f'SELECT count(*) FROM "{SCRATCH}".usage_event'))
        check("a day of calls was written", total > 500, f"{total} rows")
        check("including some in the last hour, so the dashboard is not blank",
              int(psql(f'SELECT count(*) FROM "{SCRATCH}".usage_event'
                       " WHERE occurred_at > now() - interval '1 hour'")) > 0)
        failed = int(psql(f'SELECT count(*) FROM "{SCRATCH}".usage_event WHERE status_code >= 400'))
        check("with some failures, so the success rate is not a flat 100%",
              0 < failed < total // 2, f"{failed} of {total}")
        check("the withdrawn API has no traffic",
              psql(f'SELECT count(*) FROM "{SCRATCH}".usage_event u'
                   f' JOIN "{SCRATCH}".api_definition a ON a.id = u.api_id'
                   " WHERE a.status = 'DISABLED'") == "0")

        print()
        print("--- it will not touch a database that already has rows")
        again = await demo_seed.seed()
        check("a second run writes nothing", again is False)
        check("and the partner count is unchanged",
              psql(f'SELECT count(*) FROM "{SCRATCH}".partner') == "4")

        print()
        print("--- and never under the production profile")
        production = Settings(  # type: ignore[call-arg]
            DATABASE_URL=f"postgresql+asyncpg://apigw:{PASSWORD}@127.0.0.1:5432/apigw",
            DB_SCHEMA=SCRATCH, AUTH_JWT_SECRET="x" * 40, ENVIRONMENT="production",
            CRYPTO_MASTER_KEY="", PAYLOAD_PRIVATE_KEY="",
        )
        demo_seed.get_settings = lambda: production  # type: ignore[attr-defined]
        psql(f'TRUNCATE "{SCRATCH}".partner, "{SCRATCH}".api_definition,'
             f' "{SCRATCH}".usage_event, "{SCRATCH}".partner_user CASCADE')
        check("an empty production database is still not seeded",
              await demo_seed.seed() is False)
        check("and it is still empty",
              psql(f'SELECT count(*) FROM "{SCRATCH}".partner') == "0")

    finally:
        print()
        print("--- cleanup")
        await db.dispose()
        psql(f'DROP SCHEMA IF EXISTS "{SCRATCH}" CASCADE')
        check("the scratch schema is gone",
              psql("SELECT count(*) FROM information_schema.schemata"
                   f" WHERE schema_name = '{SCRATCH}'") == "0")
        check("the real schema still has its four partners",
              psql("SELECT count(*) FROM apim.partner") == "4")


asyncio.run(main())

print()
print("FAILED" if failures else "all demo seed checks passed")
sys.exit(1 if failures else 0)
