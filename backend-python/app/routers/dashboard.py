"""The Management Portal landing page, and the system error log.

The dashboard answers two questions: what is configured, and what the gateways did in the last hour.
Every figure defaults to zero rather than null when there is no traffic, because the portal renders
these directly and an empty tile reads as a broken page.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import requires
from ..common.time import instant_column, java_instant
from ..db import connection
from .usage import DELETED_API, _half_up, _success_rate

router = APIRouter(prefix="/api/admin")

#: Spring parses `window` as an ISO-8601 Duration; the portal only ever sends hours or days.
_DEFAULT_WINDOW = timedelta(hours=1)


def _parse_window(value: str | None) -> timedelta:
    """Accepts the ISO-8601 durations the portal sends: PT1H, PT24H, P7D, P30D."""
    if not value:
        return _DEFAULT_WINDOW
    import re

    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip().upper())
    if not match:
        return _DEFAULT_WINDOW
    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    total = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    return total or _DEFAULT_WINDOW


@router.get("/dashboard", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def dashboard(
    window: str | None = None,
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    span = _parse_window(window)
    since = datetime.now(UTC) - span

    counts_row = (
        await conn.execute(
            text(
                """
                SELECT (SELECT COUNT(*) FROM api_definition) AS apis,
                       (SELECT COUNT(*) FROM api_definition WHERE status = 'ACTIVE') AS active_apis,
                       (SELECT COUNT(*) FROM api_definition WHERE status = 'DRAFT') AS draft_apis,
                       (SELECT COUNT(*) FROM api_definition WHERE status = 'DISABLED') AS disabled_apis,
                       (SELECT COUNT(*) FROM partner) AS partners,
                       (SELECT COUNT(*) FROM partner WHERE status = 'ACTIVE') AS active_partners,
                       (SELECT COUNT(*) FROM partner WHERE client_id_production IS NOT NULL)
                           AS production_partners,
                       (SELECT COUNT(*) FROM partner_user) AS partner_users
                """
            )
        )
    ).one()

    totals = (
        await conn.execute(
            text(
                """
                SELECT COUNT(*) FILTER (WHERE status_code < 400) AS success,
                       COUNT(*) FILTER (WHERE status_code >= 400) AS failed,
                       AVG(latency_ms) AS avg_latency
                  FROM usage_event
                 WHERE occurred_at >= :since
                """
            ),
            {"since": since},
        )
    ).one()

    success, failed = int(totals.success or 0), int(totals.failed or 0)
    last_hour = {
        # Rendered as text in SQL would be neater, but this boundary is computed here in Java too.
        "from": java_instant(since.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"),
        "success": success,
        "failed": failed,
        "successRate": _success_rate(success, failed),
        "avgLatencyMs": _half_up(totals.avg_latency),
    }

    # The same window as the headline figures, so the tables explain the numbers above them.
    top_apis_rows = await conn.execute(
        text(
            """
            SELECT u.api_id, a.name AS api_name, a.proxy_path,
                   COUNT(*) FILTER (WHERE u.status_code < 400) AS success,
                   COUNT(*) FILTER (WHERE u.status_code >= 400) AS failed,
                   MIN(u.latency_ms) AS min_latency,
                   MAX(u.latency_ms) AS max_latency,
                   AVG(u.latency_ms) AS avg_latency
              FROM usage_event u
              LEFT JOIN api_definition a ON a.id = u.api_id
             WHERE u.occurred_at >= :since
               AND u.api_id IS NOT NULL
             GROUP BY u.api_id, a.name, a.proxy_path
             ORDER BY (COUNT(*) FILTER (WHERE u.status_code < 400)
                       + COUNT(*) FILTER (WHERE u.status_code >= 400)) DESC
             LIMIT 5
            """
        ),
        {"since": since},
    )
    top_apis = [
        {
            "apiId": str(r.api_id) if r.api_id else None,
            "apiName": r.api_name if r.api_name is not None else DELETED_API,
            "proxyPath": r.proxy_path,
            "success": int(r.success),
            "failed": int(r.failed),
            "successRate": _success_rate(int(r.success), int(r.failed)),
            "minLatencyMs": int(r.min_latency) if r.min_latency is not None else None,
            "maxLatencyMs": int(r.max_latency) if r.max_latency is not None else None,
            "avgLatencyMs": _half_up(r.avg_latency),
        }
        for r in top_apis_rows
    ]

    top_partner_rows = await conn.execute(
        text(
            """
            SELECT u.client_id, p.name AS partner_name, p.code AS partner_code,
                   COUNT(*) FILTER (WHERE u.status_code < 400) AS success,
                   COUNT(*) FILTER (WHERE u.status_code >= 400) AS failed,
                   AVG(u.latency_ms) AS avg_latency
              FROM usage_event u
              LEFT JOIN partner p ON u.client_id IN (p.client_id_sandbox, p.client_id_production)
             WHERE u.occurred_at >= :since
               AND u.client_id IS NOT NULL
             GROUP BY u.client_id, p.name, p.code
             ORDER BY (COUNT(*) FILTER (WHERE u.status_code < 400)
                       + COUNT(*) FILTER (WHERE u.status_code >= 400)) DESC
             LIMIT 5
            """
        ),
        {"since": since},
    )
    top_partners = [
        {
            "clientId": r.client_id,
            "partnerName": r.partner_name,
            "partnerCode": r.partner_code,
            "success": int(r.success),
            "failed": int(r.failed),
            "avgLatencyMs": _half_up(r.avg_latency),
        }
        for r in top_partner_rows
    ]

    return {
        "counts": {
            "apis": int(counts_row.apis),
            "activeApis": int(counts_row.active_apis),
            "draftApis": int(counts_row.draft_apis),
            "disabledApis": int(counts_row.disabled_apis),
            "partners": int(counts_row.partners),
            "activePartners": int(counts_row.active_partners),
            "productionPartners": int(counts_row.production_partners),
            "partnerUsers": int(counts_row.partner_users),
        },
        "lastHour": last_hour,
        "topApis": top_apis,
        "topPartners": top_partners,
    }


@router.get("/errors", dependencies=[Depends(requires("ADMIN"))])
async def errors(
    source: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """The system error log. Admin only: rows carry stack traces and the addresses of signed-in users."""
    normalised = source.strip().upper() if source and source.strip() else None
    result = await conn.execute(
        text(
            f"""
            SELECT id, {instant_column('occurred_at', 'occurred_at')}, source, code, message, detail,
                   actor, request, client_ip, reference
              FROM error_event
             WHERE (CAST(:source AS varchar) IS NULL OR source = :source)
             ORDER BY occurred_at DESC, id DESC
             LIMIT :limit
            """
        ),
        {"source": normalised, "limit": limit},
    )
    return [
        {
            "id": int(r.id),
            "occurredAt": java_instant(r.occurred_at),
            "source": r.source,
            "code": r.code,
            "message": r.message,
            "detail": r.detail,
            "actor": r.actor,
            "request": r.request,
            "clientIp": r.client_ip,
            "reference": r.reference,
        }
        for r in result
    ]
