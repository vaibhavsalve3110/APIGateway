"""Usage reporting and the audit list.

Window defaults, the retention clamp and the INVALID_RANGE behaviour follow UsageService in
backend-java exactly — a report that silently covers a different period from the Java one is worse
than a report that fails.
"""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import requires
from ..common.problem import ApiException
from ..common.time import instant_column, java_instant
from ..db import connection

router = APIRouter(prefix="/api/admin")

#: CP-RPT-01/02 default when no range is given, matching UsageService.DEFAULT_WINDOW.
DEFAULT_WINDOW = timedelta(minutes=15)
#: CP-RPT-03: usage data is held online for 30 days; a wider 'from' is clamped, not rejected.
RETENTION = timedelta(days=30)

StatusFilter = Literal["ALL", "SUCCESS", "CLIENT_ERROR", "SERVER_ERROR", "ERROR"]

STATUS_RANGES: dict[str, tuple[int, int]] = {
    "ALL": (0, 999),
    "SUCCESS": (0, 399),
    "CLIENT_ERROR": (400, 499),
    "SERVER_ERROR": (500, 599),
    "ERROR": (400, 999),
}


#: What Java shows for traffic whose API has since been deleted (UsageService.toLogEntry).
DELETED_API = "Deleted API"


def _success_rate(success: int, failed: int) -> float:
    """Java rounds this with BigDecimal HALF_UP to two places; Python's round() is banker's rounding."""
    total = success + failed
    if total == 0:
        return 0.0
    rate = Decimal(success * 100) / Decimal(total)
    return float(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _half_up(value: Any) -> int | None:
    """Math.round() in Java is half-up, not half-to-even."""
    if value is None:
        return None
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _window(frm: datetime | None, to: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    end = to or now
    start = frm or (end - DEFAULT_WINDOW)
    if start >= end:
        raise ApiException.bad_request("INVALID_RANGE", "'from' must be before 'to'")
    earliest = now - RETENTION
    return (max(start, earliest), end)


def _iso(value: datetime) -> str:
    """Render a window boundary the way Java prints an Instant (no offset, no trailing zeros)."""
    text_value = value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return java_instant(text_value) or text_value


async def build_report(
    conn: AsyncConnection,
    frm: datetime | None,
    to: datetime | None,
    client_ids: list[str] | None,
) -> dict[str, Any]:
    """Shared by the admin report and the partner's own.

    `client_ids` None means every caller; an empty list means this caller owns none, so nothing
    matches — not everything, which would leak one organization's traffic into another's view.
    """
    start, end = _window(frm, to)
    if client_ids is not None and not client_ids:
        return {
            "from": _iso(start),
            "to": _iso(end),
            "totalSuccess": 0,
            "totalFailed": 0,
            "apis": [],
        }
    # `u.api_id IS NOT NULL` matches UsageRepository.aggregateAll: a call the gateway could not
    # attribute to an API is counted in neither the per-API rows nor the totals.
    result = await conn.execute(
        text(
            """
            SELECT u.api_id,
                   a.name AS api_name,
                   a.proxy_path,
                   COUNT(*) FILTER (WHERE u.status_code < 400) AS success,
                   COUNT(*) FILTER (WHERE u.status_code >= 400) AS failed,
                   MIN(u.latency_ms) AS min_latency,
                   MAX(u.latency_ms) AS max_latency,
                   AVG(u.latency_ms) AS avg_latency
              FROM usage_event u
              LEFT JOIN api_definition a ON a.id = u.api_id
             WHERE u.occurred_at >= :start
               AND u.occurred_at < :end
               AND u.api_id IS NOT NULL
               AND (CAST(:all_clients AS boolean) OR u.client_id = ANY(:client_ids))
             GROUP BY u.api_id, a.name, a.proxy_path
             ORDER BY (COUNT(*) FILTER (WHERE u.status_code < 400)
                       + COUNT(*) FILTER (WHERE u.status_code >= 400)) DESC
            """
        ),
        {
            "start": start,
            "end": end,
            "all_clients": client_ids is None,
            "client_ids": client_ids or [""],
        },
    )
    apis = [
        {
            "apiId": str(row.api_id) if row.api_id else None,
            # An API deleted since the call was logged still has traffic to account for.
            "apiName": row.api_name if row.api_name is not None else DELETED_API,
            "proxyPath": row.proxy_path,
            "success": int(row.success),
            "failed": int(row.failed),
            "successRate": _success_rate(int(row.success), int(row.failed)),
            "minLatencyMs": int(row.min_latency) if row.min_latency is not None else None,
            "maxLatencyMs": int(row.max_latency) if row.max_latency is not None else None,
            "avgLatencyMs": _half_up(row.avg_latency),
        }
        for row in result
    ]
    return {
        "from": _iso(start),
        "to": _iso(end),
        "totalSuccess": sum(a["success"] for a in apis),
        "totalFailed": sum(a["failed"] for a in apis),
        "apis": apis,
    }


@router.get("/usage/report", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def report(
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    clientId: str | None = None,  # noqa: N803 - query name matches the Java API
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    return await build_report(conn, frm, to, [clientId] if clientId else None)


async def build_logs(
    conn: AsyncConnection,
    frm: datetime | None,
    to: datetime | None,
    status: StatusFilter,
    search: str | None,
    client_ids: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Shared by the admin log viewer and the partner's own; see build_report on `client_ids`."""
    start, end = _window(frm, to)
    if client_ids is not None and not client_ids:
        return []
    low, high = STATUS_RANGES[status]
    term = f"%{search.strip().lower()}%" if search and search.strip() else None

    result = await conn.execute(
        text(
            f"""
            SELECT u.id, {instant_column('u.occurred_at', 'occurred_at')}, u.api_id,
                   a.name AS api_name, a.http_method, a.proxy_path,
                   u.environment, u.client_id, p.name AS partner_name, p.code AS partner_code,
                   u.status_code, u.latency_ms
              FROM usage_event u
              LEFT JOIN api_definition a ON a.id = u.api_id
              LEFT JOIN partner p ON u.client_id IN (p.client_id_sandbox, p.client_id_production)
             WHERE u.occurred_at >= :start
               AND u.occurred_at < :end
               AND u.status_code BETWEEN :low AND :high
               AND (CAST(:all_clients AS boolean) OR u.client_id = ANY(:client_ids))
               AND (CAST(:term AS varchar) IS NULL
                    OR LOWER(a.name) LIKE :term OR LOWER(a.proxy_path) LIKE :term)
             ORDER BY u.occurred_at DESC, u.id DESC
             LIMIT :limit
            """
        ),
        {
            "start": start,
            "end": end,
            "low": low,
            "high": high,
            "all_clients": client_ids is None,
            "client_ids": client_ids or [""],
            "term": term,
            "limit": limit,
        },
    )
    return [
        {
            "id": int(row.id),
            "occurredAt": java_instant(row.occurred_at),
            "apiId": str(row.api_id) if row.api_id else None,
            "apiName": row.api_name if row.api_name is not None else DELETED_API,
            "httpMethod": row.http_method,
            "proxyPath": row.proxy_path,
            "environment": row.environment,
            "clientId": row.client_id,
            "partnerName": row.partner_name,
            "partnerCode": row.partner_code,
            "statusCode": row.status_code,
            "latencyMs": row.latency_ms,
        }
        for row in result
    ]


@router.get("/usage/logs", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def logs(
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    status: StatusFilter = "ALL",
    search: str | None = None,
    clientId: str | None = None,  # noqa: N803
    limit: int = Query(default=200, ge=1, le=1000),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    return await build_logs(
        conn, frm, to, status, search, [clientId] if clientId else None, limit
    )


@router.get(
    "/usage/apis/{api_id}/consumers",
    dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))],
)
async def consumers(api_id: str, conn: AsyncConnection = Depends(connection)) -> list[str]:
    """CP-RPT-04: who has actually called this API inside the retention window."""
    since = datetime.now(UTC) - RETENTION
    result = await conn.execute(
        text(
            """
            SELECT DISTINCT p.name
              FROM usage_event u
              JOIN partner p ON u.client_id IN (p.client_id_sandbox, p.client_id_production)
             WHERE u.api_id = :api_id
               AND u.occurred_at >= :since
             ORDER BY p.name
            """
        ),
        {"api_id": api_id, "since": since},
    )
    return [row.name for row in result]


@router.get("/audit/actors", dependencies=[Depends(requires("ADMIN"))])
async def audit_actors(
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """Everyone who appears in the audit trail, for the "who" filter.

    Read from the trail itself rather than from the user tables: somebody who has since been deleted
    still did what they did, and their history must stay findable.
    """
    rows = await conn.execute(
        text(
            f"""
            SELECT actor, MAX(actor_role) AS actor_role, COUNT(*) AS entries,
                   {instant_column('MAX(occurred_at)', 'last_seen')}
              FROM audit_event
             GROUP BY actor
             ORDER BY MAX(occurred_at) DESC
            """
        )
    )
    return [
        {
            "actor": r.actor,
            "actorRole": r.actor_role,
            "entries": int(r.entries),
            "lastSeen": java_instant(r.last_seen),
        }
        for r in rows
    ]


@router.get("/audit", dependencies=[Depends(requires("ADMIN"))])
async def audit(
    limit: int = Query(default=100, ge=1, le=1000),
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    actor: str | None = None,
    action: str | None = None,
    search: str | None = None,
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """The audit trail, newest first.

    Every filter is optional and absent means no filter, so an unfiltered call returns exactly what
    backend-java returns. Note that these parameters exist only here: if this route is ever pointed
    back at Java they are silently ignored rather than rejected, and the page would quietly show
    everything.
    """
    result = await conn.execute(
        text(
            f"""
            SELECT id, {instant_column('occurred_at', 'occurred_at')}, actor, actor_role, action,
                   object_type, object_id, detail
              FROM audit_event
             WHERE (CAST(:frm AS timestamptz) IS NULL OR occurred_at >= :frm)
               AND (CAST(:to AS timestamptz) IS NULL OR occurred_at < :to)
               AND (CAST(:actor AS varchar) IS NULL OR LOWER(actor) = LOWER(:actor))
               AND (CAST(:action AS varchar) IS NULL OR action = :action)
               AND (CAST(:search AS varchar) IS NULL
                    OR LOWER(detail) LIKE :search OR LOWER(object_type) LIKE :search
                    OR LOWER(coalesce(object_id, '')) LIKE :search)
             ORDER BY occurred_at DESC, id DESC
             LIMIT :limit
            """
        ),
        {
            "limit": limit,
            "frm": frm,
            "to": to,
            "actor": actor.strip() if actor and actor.strip() else None,
            "action": action.strip().upper() if action and action.strip() else None,
            "search": f"%{search.strip().lower()}%" if search and search.strip() else None,
        },
    )
    return [
        {
            "id": int(row.id),
            "occurredAt": java_instant(row.occurred_at),
            "actor": row.actor,
            "actorRole": row.actor_role,
            "action": row.action,
            "objectType": row.object_type,
            "objectId": row.object_id,
            "detail": row.detail,
        }
        for row in result
    ]
