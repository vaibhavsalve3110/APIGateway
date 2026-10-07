"""API definitions — the write side (CP-API-01 to CP-API-03, CP-RPT-05).

Onboarding, editing and the status changes that publish an API to the gateways or withdraw it. The
reads live in `catalogue.py`; this module reuses its view builder so both sides cannot drift.

The gateway is pushed inside the same handler as the database write, mirroring the Java service. It
is deliberately *not* inside the database transaction: APISIX has no rollback, so a committed row
with a failed sync is recoverable by retrying the save, while a rolled-back row with a live gateway
route would leave the gateway serving an API the platform no longer knows about.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import java_instant
from ..db import engine
from ..gateway import GatewayClient
from .catalogue import _API_COLUMNS, _api_view, normalise_documentation

router = APIRouter(prefix="/api/admin/apis")

AUDIT_TYPE = "API"

#: CP-RPT-05: an API must stay Disabled for longer than this before it can be deleted.
COOLING_PERIOD_DAYS = 7

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
RateWindow = Literal["MINUTE", "HOUR", "DAY"]
ApiStatus = Literal["DRAFT", "ACTIVE", "DISABLED"]


class ApiRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=60)
    httpMethod: HttpMethod  # noqa: N815 - field names are the wire contract
    proxyPath: str = Field(  # noqa: N815
        min_length=1, max_length=200, pattern=r"^/[A-Za-z0-9/_\-{}.]*$"
    )
    backendUrlSandbox: str = Field(  # noqa: N815
        min_length=1, max_length=300, pattern=r"^https?://.+"
    )
    backendUrlProduction: str | None = Field(  # noqa: N815
        default=None, max_length=300, pattern=r"^https?://.+"
    )
    rateLimitCount: int = Field(ge=1, le=1_000_000)  # noqa: N815
    rateLimitWindow: RateWindow  # noqa: N815
    ownerTeam: str | None = Field(default=None, max_length=120)  # noqa: N815
    description: str | None = Field(default=None, max_length=2000)
    documentation: dict[str, Any] | None = None
    status: ApiStatus | None = None


class GuestVisibilityRequest(BaseModel):
    guestVisible: bool  # noqa: N815


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


async def _require(conn: AsyncConnection, api_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text("SELECT id, name, status, disabled_at FROM api_definition WHERE id = :id"),
            {"id": str(api_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("API", api_id)
    return row


async def _view(conn: AsyncConnection, api_id: uuid.UUID) -> dict[str, Any]:
    """The same shape the read endpoints return, built by the same code, so the two cannot drift."""
    row = (
        await conn.execute(
            text(f"SELECT {_API_COLUMNS} FROM api_definition WHERE id = :id"), {"id": str(api_id)}
        )
    ).first()
    if row is None:
        raise ApiException.not_found("API", api_id)
    return _api_view(row)


def _documentation_json(documentation: dict[str, Any] | None) -> str | None:
    """DocumentationCodec stores it as a JSON string; None leaves whatever is already there.

    Normalised first, so what is written matches what Java's record constructor would have written.
    """
    if documentation is None:
        return None
    return json.dumps(normalise_documentation(documentation), separators=(",", ":"))


def _java_instant_text(value: datetime) -> str:
    """The cooling-period message embeds the instant, so it has to read as Java prints one."""
    return java_instant(value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z") or ""


async def _audit(conn: AsyncConnection, actor: Principal, action: str, api_id: Any, detail: str) -> None:
    await audit.record(
        conn,
        actor=actor.username,
        actor_role=actor.roles[0] if actor.roles else None,
        action=action,
        object_type=AUDIT_TYPE,
        object_id=str(api_id),
        detail=detail,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_api(
    request: ApiRequest, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    api_id = uuid.uuid4()
    now = datetime.now(UTC)
    # A new API is ACTIVE unless the caller asked for a draft, matching ApiService.create.
    api_status = "DRAFT" if request.status == "DRAFT" else "ACTIVE"

    async with engine().begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO api_definition
                    (id, name, category, http_method, proxy_path, backend_url_sandbox,
                     backend_url_production, status, guest_visible, rate_limit_count,
                     rate_limit_window, owner_team, description, documentation, created_at, updated_at)
                VALUES (:id, :name, :category, :http_method, :proxy_path, :sandbox, :production,
                        :status, false, :rate_count, :rate_window, :owner, :description,
                        :documentation, :now, :now)
                """
            ),
            {
                "id": str(api_id),
                "name": request.name.strip(),
                "category": request.category.strip(),
                "http_method": request.httpMethod,
                "proxy_path": request.proxyPath.strip(),
                "sandbox": request.backendUrlSandbox.strip(),
                "production": _blank_to_none(request.backendUrlProduction),
                "status": api_status,
                "rate_count": request.rateLimitCount,
                "rate_window": request.rateLimitWindow,
                "owner": _blank_to_none(request.ownerTeam),
                "description": _blank_to_none(request.description),
                "documentation": _documentation_json(request.documentation),
                "now": now,
            },
        )
        detail = (
            f"{request.name.strip()} onboarded at {request.httpMethod} {request.proxyPath.strip()}"
            + (" as a draft" if api_status == "DRAFT" else "")
            + (
                f" — documentation from {request.documentation.get('source')}"
                if request.documentation is not None
                else ""
            )
        )
        await _audit(conn, actor, "CREATE", api_id, detail)
        view = await _view(conn, api_id)

    await GatewayClient().sync_api(view)
    return view


@router.put("/{api_id}")
async def update_api(
    api_id: uuid.UUID,
    request: ApiRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        await _require(conn, api_id)
        await conn.execute(
            text(
                """
                UPDATE api_definition
                   SET name = :name, category = :category, http_method = :http_method,
                       proxy_path = :proxy_path, backend_url_sandbox = :sandbox,
                       backend_url_production = :production, rate_limit_count = :rate_count,
                       rate_limit_window = :rate_window, owner_team = :owner,
                       description = :description,
                       documentation = COALESCE(:documentation, documentation),
                       updated_at = :now
                 WHERE id = :id
                """
            ),
            {
                "id": str(api_id),
                "name": request.name.strip(),
                "category": request.category.strip(),
                "http_method": request.httpMethod,
                "proxy_path": request.proxyPath.strip(),
                "sandbox": request.backendUrlSandbox.strip(),
                "production": _blank_to_none(request.backendUrlProduction),
                "rate_count": request.rateLimitCount,
                "rate_window": request.rateLimitWindow,
                "owner": _blank_to_none(request.ownerTeam),
                "description": _blank_to_none(request.description),
                # Only replaced when the request carries documentation, as setDocumentation is.
                "documentation": _documentation_json(request.documentation),
                "now": datetime.now(UTC),
            },
        )
        await _audit(conn, actor, "UPDATE", api_id, f"{request.name.strip()} configuration updated")
        view = await _view(conn, api_id)

    await GatewayClient().sync_api(view)
    return view


@router.put("/{api_id}/guest-visibility")
async def set_guest_visibility(
    api_id: uuid.UUID,
    request: GuestVisibilityRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    """Catalogue visibility only — it changes nothing at the gateway, so nothing is synced."""
    async with engine().begin() as conn:
        await _require(conn, api_id)
        await conn.execute(
            text("UPDATE api_definition SET guest_visible = :visible, updated_at = :now WHERE id = :id"),
            {"id": str(api_id), "visible": request.guestVisible, "now": datetime.now(UTC)},
        )
        await _audit(
            conn,
            actor,
            "UPDATE",
            api_id,
            f"Visible to guest users set to {'Yes' if request.guestVisible else 'No'}",
        )
        return await _view(conn, api_id)


@router.post("/{api_id}/disable")
async def disable_api(
    api_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    """CP-API-03: disabling blocks further calls immediately — the gateway route is removed."""
    async with engine().begin() as conn:
        api = await _require(conn, api_id)
        if api.status != "DISABLED":
            now = datetime.now(UTC)
            await conn.execute(
                text(
                    "UPDATE api_definition SET status = 'DISABLED', disabled_at = :now,"
                    " updated_at = :now WHERE id = :id"
                ),
                {"id": str(api_id), "now": now},
            )
        await _audit(
            conn, actor, "DISABLE", api_id, f"{api.name} disabled — cooling period started"
        )
        view = await _view(conn, api_id)

    await GatewayClient().sync_api(view)
    return view


@router.post("/{api_id}/enable")
async def enable_api(
    api_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    async with engine().begin() as conn:
        api = await _require(conn, api_id)
        await conn.execute(
            text(
                "UPDATE api_definition SET status = 'ACTIVE', disabled_at = NULL, updated_at = :now"
                " WHERE id = :id"
            ),
            {"id": str(api_id), "now": datetime.now(UTC)},
        )
        await _audit(conn, actor, "ENABLE", api_id, f"{api.name} re-enabled")
        view = await _view(conn, api_id)

    await GatewayClient().sync_api(view)
    return view


@router.delete("/{api_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api(
    api_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> Response:
    """CP-RPT-05: deletion only after the API has stayed Disabled past the cooling period."""
    async with engine().begin() as conn:
        api = await _require(conn, api_id)
        if api.status != "DISABLED" or api.disabled_at is None:
            raise ApiException.conflict("API_NOT_DISABLED", "Disable the API before deleting it")
        eligible_from = api.disabled_at + timedelta(days=COOLING_PERIOD_DAYS)
        if datetime.now(UTC) < eligible_from:
            raise ApiException.conflict(
                "COOLING_PERIOD_ACTIVE",
                f"This API can be deleted from {_java_instant_text(eligible_from)}, after the "
                f"{COOLING_PERIOD_DAYS}-day cooling period",
            )
        await conn.execute(text("DELETE FROM api_definition WHERE id = :id"), {"id": str(api_id)})
        await _audit(conn, actor, "DELETE", api_id, f"{api.name} deleted permanently")

    await GatewayClient().remove_api(str(api_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
