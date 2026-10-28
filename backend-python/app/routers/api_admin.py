"""API definitions — the write side (CP-API-01 to CP-API-03, CP-RPT-05).

Onboarding, editing and the status changes that publish an API to the gateways or withdraw it. The
reads live in `catalogue.py`; this module reuses its view builder so both sides cannot drift.

## What takes effect, and what waits for approval

A draft serves no traffic, so a developer owns it outright: create it, edit it, as often as they
like. Anything that touches what the gateways serve goes through `change_requests.py` instead:

* **publishing** — always, for anybody. An administrator's own publish waits for a *different*
  administrator, which is the whole point of the step.
* **editing a live API** — raises a request and leaves the live definition serving until approved.
  Without this the approval would be decorative: a developer could leave an API in draft and edit
  the live one instead.
* **disabling** — a request when a developer asks, immediate for an administrator. CP-API-03 makes
  disabling the way to stop calls to a misbehaving API, and queueing that behind an approval would
  be the wrong thing to do in an incident.

Approval replays the stored proposal through the same functions these endpoints call, so an approved
change cannot do something a direct call would not have done.

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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import importer, roles
from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import java_instant
from ..db import engine
from ..gateway import GatewayClient
from . import change_requests as cr
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
    request: ApiRequest, actor: Principal = Depends(requires(*roles.WRITE_APIS))
) -> dict[str, Any]:
    """Add an API to the catalogue. It starts as a draft and is not reachable until published.

    A new API is always a draft now, whoever creates it and whatever `status` the request asks for.
    It used to go straight to ACTIVE unless a draft was requested, which would be a way to publish
    an API without anybody reviewing it — and for an administrator, to publish their own work with
    no second pair of eyes. Publish it with `POST /{id}/enable`, which raises a change request.
    """
    api_id = uuid.uuid4()
    now = datetime.now(UTC)
    api_status = "DRAFT"

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
            " as a draft"
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


def _changes(current: Any, request: ApiRequest) -> list[str]:
    """What this request would alter, for the line an approver reads in the queue.

    Built from the fields that matter to someone deciding whether to allow it — where traffic goes,
    how much of it is allowed, and whether the documentation partners read has changed.
    """
    changes: list[str] = []
    if current.name != request.name.strip():
        changes.append(f"name to '{request.name.strip()}'")
    if f"{current.http_method} {current.proxy_path}" != f"{request.httpMethod} {request.proxyPath.strip()}":
        changes.append(f"route to {request.httpMethod} {request.proxyPath.strip()}")
    if (current.backend_url_sandbox or "") != request.backendUrlSandbox.strip():
        changes.append("sandbox backend URL")
    if (current.backend_url_production or "") != (_blank_to_none(request.backendUrlProduction) or ""):
        changes.append("production backend URL")
    if (
        current.rate_limit_count != request.rateLimitCount
        or current.rate_limit_window != request.rateLimitWindow
    ):
        changes.append(f"rate limit to {request.rateLimitCount} per {request.rateLimitWindow.lower()}")
    if (current.description or "") != (_blank_to_none(request.description) or ""):
        changes.append("description")
    if request.documentation is not None:
        changes.append("documentation")
    return changes


async def _apply_update(conn: AsyncConnection, api_id: uuid.UUID, request: ApiRequest) -> None:
    """The definition write itself, shared by a direct edit and by an approved change request."""
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


@router.put("/{api_id}")
async def update_api(
    api_id: uuid.UUID,
    request: ApiRequest,
    actor: Principal = Depends(requires(*roles.WRITE_APIS)),
) -> dict[str, Any]:
    """Change an API's definition. Method and proxy path together must stay unique.

    On a draft or a withdrawn API this applies at once. On a **live** API it raises a change request
    and returns that instead, leaving the live definition serving until an administrator approves —
    so the reply is the request, not the API. `objectType` tells the two apart.
    """
    async with engine().begin() as conn:
        current = (
            await conn.execute(
                text(
                    "SELECT id, name, status, http_method, proxy_path, backend_url_sandbox,"
                    " backend_url_production, rate_limit_count, rate_limit_window, description"
                    " FROM api_definition WHERE id = :id"
                ),
                {"id": str(api_id)},
            )
        ).first()
        if current is None:
            raise ApiException.not_found("API", api_id)

        if current.status == "ACTIVE":
            changes = _changes(current, request)
            if not changes:
                # Nothing to review. Saving an unchanged form should not queue an approval.
                return await _view(conn, api_id)
            raised = await cr.raise_request(
                conn,
                actor=actor,
                object_type=cr.OBJECT_API,
                object_id=api_id,
                action=cr.UPDATE,
                summary=f"Change {current.name} (live): " + ", ".join(changes),
                payload=request.model_dump(),
            )
            # 202, not 200: the caller's change has been accepted for review, not carried out. A 200
            # here would read as "saved" to anything that only checks for success, and the portal
            # would show the proposed values as though they were live.
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=raised)

        await _apply_update(conn, api_id, request)
        await _audit(conn, actor, "UPDATE", api_id, f"{request.name.strip()} configuration updated")
        view = await _view(conn, api_id)

    await GatewayClient().sync_api(view)
    return view


@router.put("/{api_id}/guest-visibility")
async def set_guest_visibility(
    api_id: uuid.UUID,
    request: GuestVisibilityRequest,
    actor: Principal = Depends(requires(*roles.WRITE_APIS)),
) -> dict[str, Any]:
    """Catalogue visibility only — it changes nothing at the gateway, so nothing is synced.

    A developer may set this on a draft. On a live API it decides whether anyone who has not signed
    in can see the API in the Developer Portal, which is a publishing decision, so it is an
    administrator's: raising a change request for a single boolean would be more ceremony than it is
    worth, and the refusal below says what to do instead.
    """
    async with engine().begin() as conn:
        api = await _require(conn, api_id)
        if api.status == "ACTIVE" and not actor.has_role(roles.ADMIN):
            raise ApiException(
                403,
                "FORBIDDEN",
                "Changing guest visibility on a live API is an APIM Admin's decision. Ask an "
                "administrator, or disable the API first if it should not be published at all.",
            )
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


async def _apply_disable(conn: AsyncConnection, api_id: uuid.UUID, current_status: str) -> None:
    if current_status != "DISABLED":
        now = datetime.now(UTC)
        await conn.execute(
            text(
                "UPDATE api_definition SET status = 'DISABLED', disabled_at = :now,"
                " updated_at = :now WHERE id = :id"
            ),
            {"id": str(api_id), "now": now},
        )


@router.post("/{api_id}/disable")
async def disable_api(
    api_id: uuid.UUID, actor: Principal = Depends(requires(*roles.WRITE_APIS))
) -> dict[str, Any]:
    """CP-API-03: disabling blocks further calls immediately — the gateway route is removed.

    Immediate for an administrator, because this is the way to stop calls to an API that is
    misbehaving and an incident is the wrong time to be waiting for a second signature. A
    developer's request is reviewed: for them it is a withdrawal, not an emergency brake.
    """
    async with engine().begin() as conn:
        api = await _require(conn, api_id)

        if not actor.has_role(roles.ADMIN):
            if api.status != "ACTIVE":
                raise ApiException.conflict(
                    "API_NOT_ACTIVE", "Only a live API can be withdrawn from service."
                )
            raised = await cr.raise_request(
                conn,
                actor=actor,
                object_type=cr.OBJECT_API,
                object_id=api_id,
                action=cr.DISABLE,
                summary=f"Withdraw {api.name} from service",
            )
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=raised)

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


async def _apply_enable(conn: AsyncConnection, api_id: uuid.UUID) -> None:
    await conn.execute(
        text(
            "UPDATE api_definition SET status = 'ACTIVE', disabled_at = NULL, updated_at = :now"
            " WHERE id = :id"
        ),
        {"id": str(api_id), "now": datetime.now(UTC)},
    )


@router.post("/{api_id}/enable", status_code=status.HTTP_202_ACCEPTED)
async def enable_api(
    api_id: uuid.UUID, actor: Principal = Depends(requires(*roles.WRITE_APIS))
) -> dict[str, Any]:
    """Ask for an API to be published. **This no longer publishes it.**

    Publishing is what puts a route on the gateways and an API in front of partners, so it always
    waits for an administrator who is not the person who asked — including when an administrator
    asks. The reply is the change request, and the status is 202: accepted, not done.
    """
    async with engine().begin() as conn:
        api = await _require(conn, api_id)
        if api.status == "ACTIVE":
            raise ApiException.conflict("API_ALREADY_ACTIVE", f"{api.name} is already live.")
        return await cr.raise_request(
            conn,
            actor=actor,
            object_type=cr.OBJECT_API,
            object_id=api_id,
            action=cr.PUBLISH,
            summary=f"Publish {api.name} ({api.status.lower()} at present)",
        )


# --------------------------------------------------------------------------- applying an approval


async def apply_approved(conn: AsyncConnection, pending: Any, approver: Principal) -> dict[str, Any]:
    """Carry out an approved change, and return the API as it now stands.

    Called only from `change_requests.approve`, inside its transaction. The gateway sync is left to
    `sync_after_approval` so it happens after the commit, for the reason at the top of this module.
    """
    api_id = uuid.UUID(str(pending.object_id))
    api = await _require(conn, api_id)

    if pending.action == cr.PUBLISH:
        await _apply_enable(conn, api_id)
        detail = f"{api.name} published, approved by {approver.username}"
    elif pending.action == cr.DISABLE:
        await _apply_disable(conn, api_id, api.status)
        detail = f"{api.name} withdrawn from service, approved by {approver.username}"
    elif pending.action == cr.UPDATE:
        payload = pending.payload
        if isinstance(payload, str):  # asyncpg hands JSONB back as text
            payload = json.loads(payload)
        # Validated again rather than trusted: the stored proposal is replayed through the same
        # model the endpoint uses, so a payload that could not be submitted today cannot be applied
        # either — which matters most for a request raised before a validation rule was tightened.
        await _apply_update(conn, api_id, ApiRequest.model_validate(payload))
        detail = f"{api.name} configuration updated, approved by {approver.username}"
    else:
        raise ApiException.conflict(
            "UNSUPPORTED_ACTION", f"Cannot apply a {pending.action} change to an API."
        )

    await audit.record(
        conn,
        actor=pending.requested_by,
        actor_role=None,
        action=pending.action,
        object_type=AUDIT_TYPE,
        object_id=str(api_id),
        # Recorded against the requester, because they are the one who made the change; the approver
        # is named in the detail and has their own APPROVE_ row. The trail has to answer both "who
        # changed this" and "who allowed it".
        detail=detail,
    )
    return await _view(conn, api_id)


async def sync_after_approval(view: dict[str, Any]) -> None:
    """Push the approved definition to the gateways, after the transaction has committed."""
    await GatewayClient().sync_api(view)


@router.delete("/{api_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api(
    api_id: uuid.UUID, actor: Principal = Depends(requires(*roles.ADMIN_ONLY))
) -> Response:
    """CP-RPT-05: deletion only after the API has stayed Disabled past the cooling period.

    Administrators only. It is irreversible and takes the audit trail's subject with it, and the
    cooling period already means nobody does it in a hurry.
    """
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

class ImportRequest(BaseModel):
    fileName: str | None = Field(default=None, max_length=255)  # noqa: N815
    content: str = Field(min_length=1, max_length=5_000_000)


@router.post("/import")
async def import_specification(
    request: ImportRequest, _: Principal = Depends(requires(*roles.ADMIN_ONLY))
) -> dict[str, Any]:
    """Read a Swagger / OpenAPI file or a Postman collection into draft operations (CP-API-06).

    Creates nothing. It returns what the file describes so the Add API editor can be pre-filled and
    a person can decide what to keep — which is why a partially readable file comes back with
    warnings rather than an error.
    """
    return importer.read(request.content)
