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
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    partnerId: str | None = None,  # noqa: N803 - query name matches the rest of the admin API
    search: str | None = None,
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """The system error log. Admin only: rows carry stack traces and the addresses of signed-in users.

    Each row carries the organization it belongs to, where one can be worked out. `error_event` has no
    partner column — what it records is who was signed in (`actor`) and what they called (`request`) —
    so the organization is derived: the actor is one of its portal users, or the request path names
    it. `partnerId=none` returns only what could not be attributed to any organization: the platform's
    own failures, which is what you want when asking whether the system itself is unhealthy.

    Attribution is best-effort by nature. A failure with nobody signed in cannot be traced to anyone,
    and reads as a platform failure rather than being guessed at.

    Like the audit filters, these parameters exist only in this service.
    """
    normalised = source.strip().upper() if source and source.strip() else None
    wants_partner = bool(partnerId and partnerId.strip() and partnerId.strip().lower() != "none")
    wants_systemic = bool(partnerId and partnerId.strip().lower() == "none")

    # Attribution happens once, here, and both the returned column and the filter read it. Two
    # definitions would eventually disagree, and the column saying one thing while the filter does
    # another is worse than having neither.
    #
    # Two ways an error points at an organization:
    #   by_actor   — a portal user of theirs was signed in;
    #   by_request — the path names the organization, which is how an admin's action on them reads.
    attributed = f"""
        SELECT e.id, {instant_column('e.occurred_at', 'occurred_at')},
               -- The formatted column above is text; filtering and ordering need the real value.
               e.occurred_at AS occurred_raw,
               e.source, e.code,
               e.message, e.detail, e.actor, e.request, e.client_ip, e.reference,
               COALESCE(by_actor.id, by_request.id)     AS partner_id,
               COALESCE(by_actor.code, by_request.code) AS partner_code,
               COALESCE(by_actor.name, by_request.name) AS partner_name
          FROM error_event e
          LEFT JOIN partner_user pu ON LOWER(pu.email) = LOWER(e.actor)
          LEFT JOIN partner by_actor ON by_actor.id = pu.partner_id
          -- substring returns NULL when the request carries no UUID, so the cast is safe.
          LEFT JOIN partner by_request ON by_request.id = CAST(
              substring(e.request from
                  '[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}'
              ) AS uuid)
    """

    if wants_partner:
        scope = "AND a.partner_id = CAST(:partner_id AS uuid)"
    elif wants_systemic:
        # Nobody signed in, or signed in as somebody who belongs to no organization.
        scope = "AND a.partner_id IS NULL"
    else:
        scope = ""

    result = await conn.execute(
        text(
            f"""
            WITH a AS ({attributed})
            SELECT * FROM a
             WHERE (CAST(:source AS varchar) IS NULL OR a.source = :source)
               AND (CAST(:frm AS timestamptz) IS NULL OR a.occurred_raw >= :frm)
               AND (CAST(:to AS timestamptz) IS NULL OR a.occurred_raw < :to)
               AND (CAST(:search AS varchar) IS NULL
                    OR LOWER(a.message) LIKE :search OR LOWER(COALESCE(a.detail, '')) LIKE :search
                    OR LOWER(a.code) LIKE :search OR LOWER(COALESCE(a.request, '')) LIKE :search
                    OR LOWER(a.reference) LIKE :search
                    OR LOWER(COALESCE(a.partner_name, '')) LIKE :search
                    OR LOWER(COALESCE(a.partner_code, '')) LIKE :search)
               {scope}
             ORDER BY a.occurred_raw DESC, a.id DESC
             LIMIT :limit
            """
        ),
        {
            "source": normalised,
            "limit": limit,
            "frm": frm,
            "to": to,
            "search": f"%{search.strip().lower()}%" if search and search.strip() else None,
            **({"partner_id": partnerId.strip()} if wants_partner else {}),
        },
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
            # Null means the failure belongs to no organization — the platform's own.
            "partnerId": str(r.partner_id) if r.partner_id else None,
            "partnerCode": r.partner_code,
            "partnerName": r.partner_name,
        }
        for r in result
    ]
