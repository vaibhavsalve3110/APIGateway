"""Gate: the three background jobs taken over from backend-java.

These are the jobs nobody watches, which is exactly why they need a test: if key expiry stops, every
replaced key goes on working indefinitely and nothing on any screen says so. The failure is silent
and the consequence is a live credential that should have died twenty minutes ago.

What this proves, against the real database:

* **a key past its overlap window is ended** — status EXPIRED, `ended_at` set — and one still
  inside its window is left alone. Both halves matter: a sweep that expires everything is as wrong
  as one that expires nothing.
* the audit trail records it as SYSTEM, with the same wording backend-java used, so a reader cannot
  tell which service ended a key.
* **two instances ticking together do the work once.** Java had no guard at all; this takes an
  advisory lock, and the test runs two sweeps concurrently to prove the second finds nothing.
* expired sign-in codes are purged and live ones are not.
* old error rows are purged, recent ones are not, and **audit rows are never touched** — those are
  evidence, the error log is diagnostics.

Everything it creates is removed at the end.

Needs the database reachable. Run:  python tests/check_jobs.py
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

import os  # noqa: E402

# The gate is about the jobs, not the gateway. Without this the sweep tries to withdraw a
# credential from an APISIX this process has no admin key for, and fails on a 401.
os.environ["GATEWAY_SYNC_ENABLED"] = "false"

from app import jobs  # noqa: E402
from app.db import dispose, engine  # noqa: E402

failures = 0
MARK = f"zz-jobs-{uuid.uuid4().hex[:8]}"


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


async def scalar(sql: str, **params: object) -> object:
    async with engine().connect() as conn:
        row = (await conn.execute(text(sql), params)).first()
        return row[0] if row else None


async def run() -> None:
    now = datetime.now(UTC)
    group_id = await scalar("SELECT id FROM partner_group LIMIT 1")
    partner_id = uuid.uuid4()
    due_key, live_key = uuid.uuid4(), uuid.uuid4()

    async with engine().begin() as conn:
        # A throwaway organization, so the keys below belong to something that can be cleaned up.
        await conn.execute(
            text(
                "INSERT INTO partner (id, code, name, group_id, access_tier, status,"
                " client_id_sandbox, created_at, updated_at)"
                " VALUES (:id, :code, :name, :g, 'UAT_ONLY', 'ACTIVE', :cid, :now, :now)"
            ),
            {"id": str(partner_id), "code": f"PTN-{MARK[-5:]}", "name": f"ZZ Jobs {MARK}",
             "g": str(group_id), "cid": f"{MARK}-sbx", "now": now},
        )
        for key_id, expires_at in ((due_key, now - timedelta(minutes=1)),
                                   (live_key, now + timedelta(minutes=20))):
            await conn.execute(
                text(
                    "INSERT INTO security_key (id, partner_id, environment, key_hash, masked_key,"
                    " status, created_at, created_by, expires_at)"
                    " VALUES (:id, :p, 'SANDBOX', :hash, :masked, 'EXPIRING', :now, :by, :exp)"
                ),
                {"id": str(key_id), "p": str(partner_id), "hash": uuid.uuid4().hex * 2,
                 "masked": f"sk_{MARK[-6:]}", "now": now, "by": MARK, "exp": expires_at},
            )

    print("--- key expiry")
    expired = await jobs.expire_due_keys()
    check("the sweep ended the key whose window had closed", expired >= 1, f"{expired} expired")
    check("that key is EXPIRED with an end time",
          await scalar("SELECT status || '/' || (ended_at IS NOT NULL)::text FROM security_key"
                       " WHERE id = :id", id=str(due_key)) == "EXPIRED/true")
    check("the key still inside its window was left alone",
          await scalar("SELECT status FROM security_key WHERE id = :id", id=str(live_key))
          == "EXPIRING")
    check("the audit trail names SYSTEM and the overlap window",
          "overlap window" in str(await scalar(
              "SELECT detail FROM audit_event WHERE object_id = :id AND action = 'EXPIRE'"
              " AND actor = 'SYSTEM'", id=str(due_key)) or ""))

    print()
    print("--- two instances ticking at once")
    # Another due key, then two sweeps started together. The advisory lock means one does the work
    # and the other finds the transaction already held and skips its tick entirely.
    second = uuid.uuid4()
    async with engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO security_key (id, partner_id, environment, key_hash, masked_key,"
                " status, created_at, created_by, expires_at)"
                " VALUES (:id, :p, 'SANDBOX', :hash, :masked, 'EXPIRING', :now, :by, :exp)"
            ),
            {"id": str(second), "p": str(partner_id), "hash": uuid.uuid4().hex * 2,
             "masked": f"sk_{MARK[-6:]}", "now": now, "by": MARK,
             "exp": now - timedelta(minutes=1)},
        )
    both = await asyncio.gather(jobs.expire_due_keys(), jobs.expire_due_keys())
    check("the key was expired exactly once across two concurrent sweeps",
          sorted(both) == [0, 1], f"returned {both}")
    check("and exactly one audit row was written for it",
          await scalar("SELECT count(*) FROM audit_event WHERE object_id = :id"
                       " AND action = 'EXPIRE'", id=str(second)) == 1)

    print()
    print("--- sign-in code cleanup")
    stale, fresh = uuid.uuid4(), uuid.uuid4()
    async with engine().begin() as conn:
        for code_id, expires_at in ((stale, now - timedelta(hours=3)),
                                    (fresh, now + timedelta(minutes=5))):
            await conn.execute(
                text(
                    "INSERT INTO otp_challenge (id, email, code_hash, created_at, expires_at,"
                    " attempts, client_ip) VALUES (:id, :email, :h, :now, :exp, 0, '127.0.0.1')"
                ),
                {"id": str(code_id), "email": f"{MARK}@jobs.test", "h": uuid.uuid4().hex,
                 "now": now - timedelta(hours=4), "exp": expires_at},
            )
    await jobs.purge_expired_codes()
    check("the long-expired code is gone",
          await scalar("SELECT count(*) FROM otp_challenge WHERE id = :id", id=str(stale)) == 0)
    check("the live code is untouched",
          await scalar("SELECT count(*) FROM otp_challenge WHERE id = :id", id=str(fresh)) == 1)

    print()
    print("--- error-log retention")
    old_ref, new_ref = f"ERR-{MARK[-8:].upper()}", f"ERR-N{MARK[-7:].upper()}"
    audit_before = await scalar("SELECT count(*) FROM audit_event")
    async with engine().begin() as conn:
        for reference, occurred in ((old_ref, now - timedelta(days=jobs.ERROR_RETENTION_DAYS + 5)),
                                    (new_ref, now - timedelta(days=1))):
            await conn.execute(
                text(
                    "INSERT INTO error_event (occurred_at, source, code, message, reference)"
                    " VALUES (:at, 'SCHEDULER', 'ZZ_JOBS_TEST', :msg, :ref)"
                ),
                {"at": occurred, "msg": f"planted by {MARK}", "ref": reference},
            )
    await jobs.purge_old_errors()
    check("an error row past the retention period is gone",
          await scalar("SELECT count(*) FROM error_event WHERE reference = :r", r=old_ref) == 0)
    check("a recent error row is kept",
          await scalar("SELECT count(*) FROM error_event WHERE reference = :r", r=new_ref) == 1)
    check("audit rows are never purged",
          await scalar("SELECT count(*) FROM audit_event") >= audit_before,
          "the retention purge touched the audit trail")

    print()
    print("--- cleanup")
    async with engine().begin() as conn:
        await conn.execute(text("DELETE FROM security_key WHERE partner_id = :p"),
                           {"p": str(partner_id)})
        await conn.execute(text("DELETE FROM partner WHERE id = :p"), {"p": str(partner_id)})
        await conn.execute(text("DELETE FROM otp_challenge WHERE email = :e"),
                           {"e": f"{MARK}@jobs.test"})
        await conn.execute(text("DELETE FROM error_event WHERE code = 'ZZ_JOBS_TEST'"))
        await conn.execute(
            text("DELETE FROM audit_event WHERE object_id IN (:a, :b, :c)"),
            {"a": str(due_key), "b": str(live_key), "c": str(second)},
        )
    check("no test organization left behind",
          await scalar("SELECT count(*) FROM partner WHERE code = :c",
                       c=f"PTN-{MARK[-5:]}") == 0)
    check("no planted error rows left behind",
          await scalar("SELECT count(*) FROM error_event WHERE code = 'ZZ_JOBS_TEST'") == 0)


async def _cleanup_stragglers() -> None:
    """Remove anything a previous failed run left behind.

    The cleanup inside run() is skipped when a check raises, and an earlier failure did exactly
    that — leaving a test organization in the real database. Belt and braces, at both ends.
    """
    async with engine().begin() as conn:
        await conn.execute(text(
            "DELETE FROM security_key WHERE partner_id IN"
            " (SELECT id FROM partner WHERE name LIKE 'ZZ Jobs %')"))
        await conn.execute(text("DELETE FROM partner WHERE name LIKE 'ZZ Jobs %'"))
        await conn.execute(text("DELETE FROM error_event WHERE code = 'ZZ_JOBS_TEST'"))


async def main() -> None:
    """One event loop for everything: the engine is cached, so a second loop breaks its pool."""
    try:
        await _cleanup_stragglers()
        await run()
    finally:
        await _cleanup_stragglers()
        await dispose()


asyncio.run(main())

print()
print("FAILED" if failures else "all background job checks passed")
sys.exit(1 if failures else 0)
