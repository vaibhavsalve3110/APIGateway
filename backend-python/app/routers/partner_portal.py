"""The Developer Portal's own endpoints — what a signed-in partner sees.

Every route here is scoped to the organization on the caller's token and nothing else. That scoping
is the whole security property of this module: a partner must never see another organization's
traffic, keys, products or Client IDs, and the scope comes from the token rather than from any
parameter the caller could change.

Two routes in this package are deliberately not ported yet, because they depend on work that has not
happened: `POST /api/partner/keys/{environment}` needs the cipher and the rotation rules (phase 5),
and `POST /api/partner/apis/{id}/try` calls the gateway. Both stay on Java until then.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import Principal, current_principal, requires
from ..common.problem import ApiException
from ..common.time import instant_column, java_instant
from ..db import connection
from ..settings import get_settings
from .dashboard import _parse_window
from .usage import StatusFilter, _half_up, _success_rate, build_logs, build_report

router = APIRouter()

#: The header partners send their security key in; ApisixConfigFactory.KEY_HEADER on the Java side.
KEY_HEADER = "X-Security-Key"


async def _current_partner(conn: AsyncConnection, principal: Principal) -> Any:
    """The organization on the token. Never a parameter — that is what keeps tenants apart."""
    if not principal.partner_code:
        raise ApiException(403, "NOT_A_PARTNER", "This endpoint is for Developer Portal users")
    row = (
        await conn.execute(
            text(
                "SELECT id, code, name, access_tier, status, client_id_sandbox, client_id_production"
                "  FROM partner WHERE code = :code"
            ),
            {"code": principal.partner_code},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Partner", principal.partner_code)
    return row


def _client_ids(partner: Any) -> list[str]:
    ids = [partner.client_id_sandbox]
    if partner.client_id_production:
        ids.append(partner.client_id_production)
    return ids


async def _signed_in_user(conn: AsyncConnection, partner: Any, principal: Principal) -> Any:
    """The partner_user record behind the token, or None when the token names nobody in this org."""
    return (
        await conn.execute(
            text(
                "SELECT id, role, status FROM partner_user"
                " WHERE email = :email AND partner_id = :partner_id"
            ),
            {"email": principal.username.lower(), "partner_id": str(partner.id)},
        )
    ).first()


# --------------------------------------------------------------------------- who am I


@router.get("/api/me")
async def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    """Both portals call this on load to restore a session. Not partner-specific."""
    return {
        "username": principal.username,
        "roles": sorted(principal.roles),
        "partnerCode": principal.partner_code,
    }


@router.get("/api/partner/me", dependencies=[Depends(requires("PARTNER"))])
async def partner_me(
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    partner = await _current_partner(conn, principal)
    user = await _signed_in_user(conn, partner, principal)
    role = user.role if user else None
    return {
        "code": partner.code,
        "name": partner.name,
        "accessTier": partner.access_tier,
        "status": partner.status,
        "clientIdSandbox": partner.client_id_sandbox,
        # A sandbox-only partner is not told a production Client ID even if one exists on the record.
        "clientIdProduction": (
            partner.client_id_production if partner.access_tier == "PRODUCTION" else None
        ),
        "role": role,
        "canGenerateKeys": role == "PARTNER_ADMIN",
    }


# --------------------------------------------------------------------------- catalogue


@router.get("/api/partner/apis", dependencies=[Depends(requires("PARTNER"))])
async def catalogue(
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    """Only live APIs: a draft or disabled API is not something to send a partner to."""
    partner = await _current_partner(conn, principal)
    rows = await conn.execute(
        text(
            """
            SELECT id, name, category, http_method, proxy_path, description,
                   rate_limit_count, rate_limit_window, backend_url_production
              FROM api_definition
             WHERE status = 'ACTIVE'
             ORDER BY name ASC
            """
        )
    )
    production = partner.access_tier == "PRODUCTION"
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "category": r.category,
            "httpMethod": r.http_method,
            "proxyPath": r.proxy_path,
            "description": r.description,
            "rateLimitCount": r.rate_limit_count,
            "rateLimitWindow": r.rate_limit_window,
            "productionAvailable": production and r.backend_url_production is not None,
        }
        for r in rows
    ]


@router.get("/api/partner/apis/{api_id}", dependencies=[Depends(requires("PARTNER"))])
async def api_detail(
    api_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    partner = await _current_partner(conn, principal)
    row = (
        await conn.execute(
            text(
                """
                SELECT id, name, category, http_method, proxy_path, description,
                       rate_limit_count, rate_limit_window, backend_url_production, status, documentation
                  FROM api_definition WHERE id = :id
                """
            ),
            {"id": str(api_id)},
        )
    ).first()
    # An API that is not live reads as absent here, rather than as forbidden: a partner has no
    # business learning that a draft API exists.
    if row is None or row.status != "ACTIVE":
        raise ApiException.not_found("API", api_id)

    settings = get_settings()
    documentation = None
    if row.documentation:
        try:
            documentation = json.loads(row.documentation)
        except ValueError:
            documentation = None
    return {
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "httpMethod": row.http_method,
        "proxyPath": row.proxy_path,
        "description": row.description,
        "rateLimitCount": row.rate_limit_count,
        "rateLimitWindow": row.rate_limit_window,
        "productionAvailable": (
            partner.access_tier == "PRODUCTION" and row.backend_url_production is not None
        ),
        "sandboxBaseUrl": settings.public_sandbox_url,
        "keyHeader": KEY_HEADER,
        "tryItSimulated": settings.try_it_mode.upper() == "SIMULATE",
        "documentation": documentation,
    }


# --------------------------------------------------------------------------- keys (read only)


@router.get("/api/partner/keys", dependencies=[Depends(requires("PARTNER"))])
async def keys(
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    partner = await _current_partner(conn, principal)
    return await list_keys(conn, partner.id)


async def list_keys(conn: AsyncConnection, partner_id: Any) -> list[dict[str, Any]]:
    """Shared with the admin key list. Only the masked key is ever returned; the key itself is not stored."""
    rows = await conn.execute(
        text(
            f"""
            SELECT id, environment, masked_key, status,
                   {instant_column('created_at', 'created_at')}, created_by,
                   {instant_column('expires_at', 'expires_at')},
                   {instant_column('ended_at', 'ended_at')},
                   expires_at AS expires_raw
              FROM security_key
             WHERE partner_id = :partner_id
             ORDER BY created_at DESC
            """
        ),
        {"partner_id": str(partner_id)},
    )
    now = datetime.now(UTC)
    out = []
    for r in rows:
        # Only a key inside its overlap window counts down; everything else has nothing to report.
        remaining = None
        if r.status == "EXPIRING" and r.expires_raw is not None:
            remaining = max(0, int((r.expires_raw - now).total_seconds()))
        out.append(
            {
                "id": str(r.id),
                "environment": r.environment,
                "maskedKey": r.masked_key,
                "status": r.status,
                "createdAt": java_instant(r.created_at),
                "createdBy": r.created_by,
                "expiresAt": java_instant(r.expires_at),
                "secondsRemaining": remaining,
                "endedAt": java_instant(r.ended_at),
            }
        )
    return out


# --------------------------------------------------------------------------- usage


@router.get("/api/partner/usage", dependencies=[Depends(requires("PARTNER"))])
async def partner_usage(
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    partner = await _current_partner(conn, principal)
    return await build_report(conn, frm, to, _client_ids(partner))


@router.get("/api/partner/usage/logs", dependencies=[Depends(requires("PARTNER"))])
async def partner_logs(
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    status: StatusFilter = "ALL",
    search: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    partner = await _current_partner(conn, principal)
    return await build_logs(conn, frm, to, status, search, _client_ids(partner), limit)


@router.get("/api/partner/dashboard", dependencies=[Depends(requires("PARTNER"))])
async def partner_dashboard(
    window: str | None = None,
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    partner = await _current_partner(conn, principal)
    span = _parse_window(window) if window else timedelta(hours=24)
    since = datetime.now(UTC) - span
    client_ids = _client_ids(partner)

    apis_available = (
        await conn.execute(text("SELECT COUNT(*) AS n FROM api_definition WHERE status = 'ACTIVE'"))
    ).one()
    active_keys = (
        await conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM security_key"
                " WHERE partner_id = :id AND status IN ('ACTIVE','EXPIRING')"
            ),
            {"id": str(partner.id)},
        )
    ).one()
    products = await _visible_products(conn, partner, principal)

    totals = (
        await conn.execute(
            text(
                """
                SELECT COUNT(*) FILTER (WHERE status_code < 400) AS success,
                       COUNT(*) FILTER (WHERE status_code >= 400) AS failed,
                       AVG(latency_ms) AS avg_latency
                  FROM usage_event
                 WHERE occurred_at >= :since AND client_id = ANY(:client_ids)
                """
            ),
            {"since": since, "client_ids": client_ids},
        )
    ).one()
    success, failed = int(totals.success or 0), int(totals.failed or 0)

    report = await build_report(conn, since, None, client_ids)
    recent = await build_logs(conn, since, None, "ALL", None, client_ids, 25)

    # Everything defaults to zero on a quiet account: an empty dashboard is a fact, not an error.
    return {
        "partnerName": partner.name,
        "partnerCode": partner.code,
        "counts": {
            "apisAvailable": int(apis_available.n),
            "products": len(products),
            "activeKeys": int(active_keys.n),
            "productionAvailable": partner.client_id_production is not None,
        },
        "window": {
            "from": java_instant(since.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"),
            "success": success,
            "failed": failed,
            "successRate": _success_rate(success, failed),
            "avgLatencyMs": _half_up(totals.avg_latency),
        },
        "apis": report["apis"],
        "recentCalls": recent,
    }


# --------------------------------------------------------------------------- products and pages


async def _visible_products(
    conn: AsyncConnection, partner: Any, principal: Principal
) -> list[dict[str, Any]]:
    """Published products assigned to the organization, plus any assigned to this user personally."""
    user = await _signed_in_user(conn, partner, principal)
    rows = await conn.execute(
        text(
            """
            SELECT p.id, p.name, p.slug, p.summary, p.description, p.journey_markdown,
                   BOOL_OR(a.partner_user_id IS NOT NULL) AS personal
              FROM product p
              JOIN product_assignment a ON a.product_id = p.id
             WHERE p.status = 'PUBLISHED'
               AND a.partner_id = :partner_id
               AND (a.partner_user_id IS NULL OR a.partner_user_id = CAST(:user_id AS uuid))
             GROUP BY p.id, p.name, p.slug, p.summary, p.description, p.journey_markdown
             ORDER BY p.name ASC
            """
        ),
        {"partner_id": str(partner.id), "user_id": str(user.id) if user else None},
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "slug": r.slug,
            "summary": r.summary,
            "description": r.description,
            "journeyMarkdown": r.journey_markdown,
            "steps": await _live_steps(conn, r.id),
            "assignedToYouDirectly": bool(r.personal),
        }
        for r in rows
    ]


async def _live_steps(conn: AsyncConnection, product_id: Any) -> list[dict[str, Any]]:
    """Only live APIs appear in a partner's journey, renumbered so the sequence has no gaps."""
    rows = await conn.execute(
        text(
            """
            SELECT s.api_id, s.step_note, s.depends_on_api_id,
                   a.name AS api_name, a.category, a.http_method, a.proxy_path, a.status,
                   a.description AS api_description, d.name AS depends_on_api_name
              FROM product_step s
              JOIN api_definition a ON a.id = s.api_id
              LEFT JOIN api_definition d ON d.id = s.depends_on_api_id
             WHERE s.product_id = :id
             ORDER BY s.position ASC
            """
        ),
        {"id": str(product_id)},
    )
    out = []
    number = 1
    for r in rows:
        if r.status != "ACTIVE":
            continue
        out.append(
            {
                "step": number,
                "apiId": str(r.api_id),
                "apiName": r.api_name,
                "category": r.category,
                "httpMethod": r.http_method,
                "proxyPath": r.proxy_path,
                "status": r.status,
                "apiDescription": r.api_description,
                "note": r.step_note,
                "dependsOnApiId": str(r.depends_on_api_id) if r.depends_on_api_id else None,
                "dependsOnApiName": r.depends_on_api_name,
            }
        )
        number += 1
    return out


@router.get("/api/partner/products", dependencies=[Depends(requires("PARTNER"))])
async def partner_products(
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    partner = await _current_partner(conn, principal)
    return await _visible_products(conn, partner, principal)


@router.get("/api/partner/products/{slug}", dependencies=[Depends(requires("PARTNER"))])
async def partner_product(
    slug: str,
    principal: Principal = Depends(current_principal),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    partner = await _current_partner(conn, principal)
    for product in await _visible_products(conn, partner, principal):
        if product["slug"] == slug:
            return product
    # A product they are not assigned reads as absent, not forbidden.
    raise ApiException.not_found("Product", slug)


@router.get("/api/partner/pages", dependencies=[Depends(requires("PARTNER"))])
async def partner_pages(conn: AsyncConnection = Depends(connection)) -> list[dict[str, Any]]:
    """The Developer Portal menu: published pages only, in the order the editor set."""
    rows = await conn.execute(
        text(
            "SELECT slug, title, category FROM portal_page WHERE status = 'PUBLISHED'"
            " ORDER BY category ASC, position ASC, title ASC"
        )
    )
    return [{"slug": r.slug, "title": r.title, "category": r.category} for r in rows]


@router.get("/api/partner/pages/{slug}", dependencies=[Depends(requires("PARTNER"))])
async def partner_page(
    slug: str, conn: AsyncConnection = Depends(connection)
) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                f"""
                SELECT p.slug, p.title, p.category, v.body_markdown,
                       {instant_column('p.published_at', 'published_at')}
                  FROM portal_page p
                  JOIN portal_page_version v ON v.id = p.published_version
                 WHERE p.slug = :slug AND p.status = 'PUBLISHED'
                """
            ),
            {"slug": slug},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Page", slug)
    return {
        "slug": row.slug,
        "title": row.title,
        "category": row.category,
        "bodyMarkdown": row.body_markdown,
        "publishedAt": java_instant(row.published_at),
    }

