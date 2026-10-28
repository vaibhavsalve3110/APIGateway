"""Background jobs, taken over from backend-java's three ``@Scheduled`` methods.

| Job | Runs | Does |
| --- | --- | --- |
| key expiry | every 15 seconds | ends keys whose 20-minute overlap window has closed |
| sign-in code cleanup | hourly | deletes one-time codes that expired over an hour ago |
| error-log retention | daily | deletes error rows older than the retention period |

Audit rows are never purged. Those are evidence; the error log is diagnostics.

## Only one instance runs each tick

Java ran these with no guard at all, so two replicas would have expired every key twice and purged
the error log from two transactions at once. Each tick here takes a PostgreSQL advisory lock and
skips the tick entirely if another instance holds it — `pg_try_advisory_lock`, which returns false
rather than waiting, because a tick that waits for the previous one has nothing useful left to do by
the time it gets in.

The lock is per job, so the hourly purge never blocks the fifteen-second sweep.

## A failure never stops the loop

Every tick is wrapped: a gateway outage must not kill the scheduler, and the work is idempotent, so
whatever failed is simply picked up by the next tick. Failures are recorded against
``SCHEDULER`` in the error log, which is what the monitoring document tells people to watch.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .common import audit, errors
from .db import engine
from .gateway import GatewayClient
from .settings import get_settings

log = logging.getLogger(__name__)

#: One lock per job. Any constants, so long as every instance of this service uses the same ones.
LOCK_KEY_EXPIRY = 8_241_907_553_110_001
LOCK_OTP_CLEANUP = 8_241_907_553_110_002
LOCK_ERROR_RETENTION = 8_241_907_553_110_003

#: Matches backend-java's apigw.keys.expiry-check-interval default of PT15S.
KEY_EXPIRY_SECONDS = 15
OTP_CLEANUP_SECONDS = 60 * 60
ERROR_RETENTION_SECONDS = 24 * 60 * 60

#: apigw.errors.retention, P30D in backend-java.
ERROR_RETENTION_DAYS = 30

AUDIT_TYPE = "SECURITY_KEY"


async def _took_lock(conn: AsyncConnection, key: int) -> bool:
    """True when this instance may run the tick. False means another one is already on it."""
    row = (await conn.execute(text("SELECT pg_try_advisory_xact_lock(:k) AS got"), {"k": key})).first()
    return bool(row.got)


# --------------------------------------------------------------------------- the work


async def expire_due_keys() -> int:
    """End keys whose overlap window has closed, and withdraw them from the gateway.

    **The gateway call happens inside the transaction here**, which is the opposite of how an API
    sync is done elsewhere in this service, and deliberately so. The two failure modes are not
    equally bad:

    * commit first, then fail to withdraw → the platform believes the key is dead while the gateway
      goes on honouring it. A partner keeps calling with an expired credential and nothing says so.
    * withdraw first, then fail to commit → the key stays EXPIRING, so the platform still believes
      it is live while the gateway has already stopped accepting it. The partner loses a key a few
      minutes early and the next tick puts the record right.

    The second is an availability blip that heals itself; the first is a live credential that should
    have died. So a gateway failure rolls the whole tick back and it is retried, exactly as the Java
    job did by being transactional.
    """
    now = datetime.now(UTC)
    withdrawn: list[tuple[str, str, str]] = []

    async with engine().begin() as conn:
        if not await _took_lock(conn, LOCK_KEY_EXPIRY):
            return 0
        due = list(
            await conn.execute(
                text(
                    "SELECT k.id, k.partner_id, k.environment, k.masked_key,"
                    "       p.client_id_sandbox, p.client_id_production"
                    "  FROM security_key k JOIN partner p ON p.id = k.partner_id"
                    " WHERE k.status = 'EXPIRING' AND k.expires_at <= :now"
                ),
                {"now": now},
            )
        )
        if not due:
            return 0

        overlap = get_settings().key_overlap_minutes
        for key in due:
            await conn.execute(
                text(
                    "UPDATE security_key SET status = 'EXPIRED', ended_at = :now WHERE id = :id"
                ),
                {"id": str(key.id), "now": now},
            )
            # Same wording as the Java job's audit row: the trail is read across both services and
            # a reader should not be able to tell which one ended a key.
            await audit.record(
                conn,
                actor="SYSTEM",
                actor_role="SYSTEM",
                action="EXPIRE",
                object_type=AUDIT_TYPE,
                object_id=str(key.id),
                detail=(
                    f"{key.environment} key {key.masked_key} expired at the end of the "
                    f"{overlap}-minute overlap window"
                ),
            )
            client_id = (
                key.client_id_production if key.environment == "PRODUCTION" else key.client_id_sandbox
            )
            if client_id:
                # Raises on a gateway failure, which rolls this tick back — see the note above.
                await GatewayClient().delete_credential(
                    key.environment, client_id, str(key.id)
                )
                withdrawn.append((key.environment, client_id, str(key.id)))

    log.info("Expired %d security key(s) at the end of their overlap window", len(due))
    return len(due)


async def purge_expired_codes() -> int:
    """Delete one-time codes that expired over an hour ago. They are of no further use."""
    async with engine().begin() as conn:
        if not await _took_lock(conn, LOCK_OTP_CLEANUP):
            return 0
        result = await conn.execute(
            text("DELETE FROM otp_challenge WHERE expires_at < :before"),
            {"before": datetime.now(UTC) - timedelta(hours=1)},
        )
        removed = result.rowcount or 0
    if removed:
        log.info("Purged %d expired sign-in code(s)", removed)
    return removed


async def purge_old_errors() -> int:
    """Keep the error log to its retention period. Audit rows are never touched."""
    async with engine().begin() as conn:
        if not await _took_lock(conn, LOCK_ERROR_RETENTION):
            return 0
        result = await conn.execute(
            text("DELETE FROM error_event WHERE occurred_at < :before"),
            {"before": datetime.now(UTC) - timedelta(days=ERROR_RETENTION_DAYS)},
        )
        deleted = result.rowcount or 0
    if deleted:
        log.info("Purged %d error record(s) older than %d days", deleted, ERROR_RETENTION_DAYS)
    return deleted


# --------------------------------------------------------------------------- the loop


async def _loop(name: str, every: int, work, code: str) -> None:  # type: ignore[no-untyped-def]
    """Run one job forever. Never raises: a failed tick is recorded and the next one tries again."""
    while True:
        await asyncio.sleep(every)
        try:
            await work()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one job's failure must not stop the others
            log.exception("%s failed; will retry on the next run", name)
            with contextlib.suppress(Exception):
                # Recording the failure must not itself end the loop — if the database is the thing
                # that is down, this write fails too, and the log line above is what remains.
                await errors.record(
                    errors.SCHEDULER, code, f"The {name} failed and will be retried: {exc}",
                    detail=repr(exc),
                )


def start() -> list[asyncio.Task[None]]:
    """Start every job. Returns the tasks so the lifespan can cancel them on shutdown."""
    settings = get_settings()
    if not settings.scheduler_enabled:
        log.warning("SCHEDULER_ENABLED is off — keys will not expire and nothing will be purged")
        return []

    jobs = [
        ("key expiry sweep", KEY_EXPIRY_SECONDS, expire_due_keys, "KEY_EXPIRY_FAILED"),
        ("sign-in code cleanup", OTP_CLEANUP_SECONDS, purge_expired_codes, "OTP_PURGE_FAILED"),
        ("error-log retention purge", ERROR_RETENTION_SECONDS, purge_old_errors,
         "ERROR_RETENTION_FAILED"),
    ]
    tasks = [asyncio.create_task(_loop(*job), name=job[0]) for job in jobs]
    log.info("Started %d background job(s); one instance runs each tick", len(tasks))
    return tasks


async def stop(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
