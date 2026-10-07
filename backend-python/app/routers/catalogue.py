"""APIs, partners and partner groups — the read side.

Field-for-field equivalents of backend-java's ApiView, PartnerView and GroupView. The portals are
shared between the services, so a missing or renamed field here is a broken screen there.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import requires
from ..common.problem import ApiException
from ..common.time import instant_column, java_instant
from ..db import connection

router = APIRouter(prefix="/api/admin", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])

# deletable_from is computed in SQL so it keeps the microsecond precision of disabled_at; doing the
# arithmetic in Python on a datetime would be fine, but keeping it here means one source of truth
# for CP-RPT-05's seven-day cooling period.
_API_COLUMNS = f"""
    id, name, category, http_method, proxy_path, backend_url_sandbox, backend_url_production,
    status, guest_visible, rate_limit_count, rate_limit_window, owner_team, description,
    {instant_column('disabled_at', 'disabled_at')},
    {instant_column(
        "CASE WHEN status = 'DISABLED' AND disabled_at IS NOT NULL "
        "THEN disabled_at + interval '7 days' END",
        'deletable_from',
    )},
    {instant_column('created_at', 'created_at')},
    {instant_column('updated_at', 'updated_at')},
    documentation
"""

_PARTNER_COLUMNS = f"""
    p.id, p.code, p.name, p.group_id, g.name AS group_name, p.access_tier, p.status, p.contact_email,
    p.client_id_sandbox, p.client_id_production,
    {instant_column('p.created_at', 'created_at')},
    p.signature_algorithm, p.signature_fingerprint, p.signature_public_key,
    {instant_column('p.signature_created_at', 'signature_created_at')},
    p.ipv_salt_masked,
    {instant_column('p.ipv_salt_created_at', 'ipv_salt_created_at')}
"""


def normalise_documentation(documentation: dict[str, Any] | None) -> dict[str, Any]:
    """ApiDocumentation's compact constructor, in Python.

    Java fills every absent list with an empty one and defaults a missing source to MANUAL, so an API
    with no documentation reads as an empty document rather than as null. Returning null here instead
    is a difference the portals would render as a missing section.
    """
    doc = documentation or {}
    source = (doc.get("source") or "").strip()
    return {
        "source": source or "MANUAL",
        "queryParameters": doc.get("queryParameters") or [],
        "requestHeaders": doc.get("requestHeaders") or [],
        "requestBodyFields": doc.get("requestBodyFields") or [],
        "requestBodyExample": doc.get("requestBodyExample"),
        "responseHeaders": doc.get("responseHeaders") or [],
        "responses": doc.get("responses") or [],
    }


def _documentation(stored: str | None) -> Any:
    """Stored as a JSON string by DocumentationCodec; absent or blank reads as an empty document.

    One deliberate difference: Java throws on a malformed blob, which fails the whole list. A corrupt
    row here reads as empty instead, so one bad record cannot hide every good one.
    """
    if not stored or not stored.strip():
        return normalise_documentation(None)
    try:
        parsed = json.loads(stored)
    except ValueError:
        return normalise_documentation(None)
    return normalise_documentation(parsed if isinstance(parsed, dict) else None)


def _api_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "httpMethod": row.http_method,
        "proxyPath": row.proxy_path,
        "backendUrlSandbox": row.backend_url_sandbox,
        "backendUrlProduction": row.backend_url_production,
        "status": row.status,
        "guestVisible": row.guest_visible,
        "rateLimitCount": row.rate_limit_count,
        "rateLimitWindow": row.rate_limit_window,
        "ownerTeam": row.owner_team,
        "description": row.description,
        "disabledAt": java_instant(row.disabled_at),
        "deletableFrom": java_instant(row.deletable_from),
        "createdAt": java_instant(row.created_at),
        "updatedAt": java_instant(row.updated_at),
        "documentation": _documentation(row.documentation),
    }


def _partner_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "groupId": str(row.group_id),
        "groupName": row.group_name,
        "accessTier": row.access_tier,
        "status": row.status,
        "contactEmail": row.contact_email,
        "clientIdSandbox": row.client_id_sandbox,
        "clientIdProduction": row.client_id_production,
        "createdAt": java_instant(row.created_at),
        "signatureAlgorithm": row.signature_algorithm,
        "signatureFingerprint": row.signature_fingerprint,
        "signaturePublicKey": row.signature_public_key,
        "signatureCreatedAt": java_instant(row.signature_created_at),
        "ipvSaltMasked": row.ipv_salt_masked,
        "ipvSaltCreatedAt": java_instant(row.ipv_salt_created_at),
    }


@router.get("/apis")
async def list_apis(conn: AsyncConnection = Depends(connection)) -> list[dict[str, Any]]:
    result = await conn.execute(text(f"SELECT {_API_COLUMNS} FROM api_definition ORDER BY name ASC"))
    return [_api_view(row) for row in result]


@router.get("/apis/{api_id}")
async def get_api(api_id: str, conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    result = await conn.execute(
        text(f"SELECT {_API_COLUMNS} FROM api_definition WHERE id = :id"), {"id": api_id}
    )
    row = result.first()
    if row is None:
        raise ApiException.not_found("API", api_id)
    return _api_view(row)


@router.get("/partner-groups")
async def list_groups(conn: AsyncConnection = Depends(connection)) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT g.id, g.name, g.description, g.status,
                   (SELECT COUNT(*) FROM partner p WHERE p.group_id = g.id) AS partner_count
              FROM partner_group g
             ORDER BY g.name ASC
            """
        )
    )
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,
            "status": row.status,
            "partnerCount": int(row.partner_count),
        }
        for row in result
    ]


@router.get("/partners")
async def list_partners(conn: AsyncConnection = Depends(connection)) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            f"""SELECT {_PARTNER_COLUMNS}
                  FROM partner p
                  LEFT JOIN partner_group g ON g.id = p.group_id
                 ORDER BY p.name ASC"""
        )
    )
    return [_partner_view(row) for row in result]


@router.get("/partners/{partner_id}")
async def get_partner(partner_id: str, conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    result = await conn.execute(
        text(
            f"""SELECT {_PARTNER_COLUMNS}
                  FROM partner p
                  LEFT JOIN partner_group g ON g.id = p.group_id
                 WHERE p.id = :id"""
        ),
        {"id": partner_id},
    )
    row = result.first()
    if row is None:
        raise ApiException.not_found("Partner", partner_id)
    return _partner_view(row)
