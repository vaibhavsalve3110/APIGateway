"""Approvals: a change waits here until a second person agrees to it.

A developer may draft and edit an API freely, because a draft serves no traffic. Three things do not
take effect on their own:

* **PUBLISH** — making a draft or withdrawn API live.
* **UPDATE** — changing an API that is *already* live. Without this the approval would be
  decorative: a developer could leave the API in draft and edit the live one instead.
* **DISABLE** — taking a live API out of service, when a developer asks for it. An administrator can
  disable immediately, because CP-API-03 makes disabling the way to stop calls to a misbehaving API
  and queueing that behind an approval would be the wrong thing in an incident.

The live row is not touched while a request is pending. The proposal is held whole, as the JSON body
the API's own endpoint would have received, and applied by replaying it through that same code on
approval — so an approved change cannot diverge from what a direct call would have done.

**An approval needs a different administrator from the requester.** That is the entire value of the
step, so it is enforced here rather than left to the portal to hide a button.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import roles
from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import instant_column, java_instant
from ..db import engine

router = APIRouter(prefix="/api/admin/change-requests", tags=["approvals"])

AUDIT_TYPE = "CHANGE_REQUEST"

OBJECT_API = "API"
PUBLISH = "PUBLISH"
UPDATE = "UPDATE"
DISABLE = "DISABLE"

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
WITHDRAWN = "WITHDRAWN"

_COLUMNS = f"""
    r.id, r.object_type, r.object_id, r.action, r.payload, r.summary, r.status,
    r.requested_by, {instant_column("r.requested_at", "requested_at")},
    r.decided_by, {instant_column("r.decided_at", "decided_at")}, r.decision_note,
    a.name AS object_name, a.status AS object_status
"""

_FROM = """
    FROM change_request r
    LEFT JOIN api_definition a ON a.id = r.object_id
"""


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


def _view(row: Any) -> dict[str, Any]:
    payload = row.payload
    if isinstance(payload, str):  # asyncpg hands back JSONB as text
        payload = json.loads(payload)
    return {
        "id": str(row.id),
        "objectType": row.object_type,
        "objectId": str(row.object_id) if row.object_id else None,
        # The API's current name, so the queue reads as a list of APIs rather than of UUIDs. Null
        # once the API has been deleted, which can happen while an old decided request is still here.
        "objectName": row.object_name,
        "objectStatus": row.object_status,
        "action": row.action,
        "payload": payload,
        "summary": row.summary,
        "status": row.status,
        "requestedBy": row.requested_by,
        # Trimmed the way Java's Instant.toString() prints, like every other timestamp the portals
        # receive: they compare these as strings.
        "requestedAt": java_instant(row.requested_at),
        "decidedBy": row.decided_by,
        "decidedAt": java_instant(row.decided_at),
        "decisionNote": row.decision_note,
    }


async def raise_request(
    conn: AsyncConnection,
    *,
    actor: Principal,
    object_type: str,
    object_id: uuid.UUID | None,
    action: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a proposal and return it. Called by the endpoints whose change needs approving."""
    if object_id is not None:
        existing = (
            await conn.execute(
                text(
                    "SELECT id, action, requested_by FROM change_request"
                    " WHERE object_type = :type AND object_id = :id AND status = 'PENDING'"
                ),
                {"type": object_type, "id": str(object_id)},
            )
        ).first()
        if existing is not None:
            # Two pending changes to one API would be applied in approval order, and the second
            # would silently overwrite the first with whatever it was holding.
            raise ApiException.conflict(
                "CHANGE_ALREADY_PENDING",
                f"A {existing.action.lower()} request for this API is already waiting for approval,"
                f" raised by {existing.requested_by}. It has to be decided or withdrawn first.",
            )

    request_id = uuid.uuid4()
    now = datetime.now(UTC)
    await conn.execute(
        text(
            """
            INSERT INTO change_request
                (id, object_type, object_id, action, payload, summary, status, requested_by, requested_at)
            VALUES (:id, :type, :object_id, :action, CAST(:payload AS JSONB), :summary, 'PENDING',
                    :actor, :now)
            """
        ),
        {
            "id": str(request_id),
            "type": object_type,
            "object_id": str(object_id) if object_id else None,
            "action": action,
            "payload": json.dumps(payload) if payload is not None else None,
            "summary": summary,
            "actor": actor.username,
            "now": now,
        },
    )
    await audit.record(
        conn,
        actor=actor.username,
        actor_role=actor.roles[0] if actor.roles else None,
        action="REQUEST_" + action,
        object_type=AUDIT_TYPE,
        object_id=str(request_id),
        detail=f"Approval requested: {summary}",
    )
    row = (
        await conn.execute(text(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = :id"), {"id": str(request_id)})
    ).first()
    return _view(row)


@router.get("")
async def list_requests(
    status: str | None = Query(default=None, description="PENDING, APPROVED, REJECTED or WITHDRAWN"),
    limit: int = Query(default=200, ge=1, le=1000),
    _: Principal = Depends(requires(*roles.REQUEST_CHANGES)),
) -> list[dict[str, Any]]:
    """Change requests, newest first. Defaults to everything; filter by status for the queue."""
    clause = "WHERE r.status = :status" if status else ""
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status.upper()
    async with engine().connect() as conn:
        rows = await conn.execute(
            text(f"SELECT {_COLUMNS} {_FROM} {clause} ORDER BY r.requested_at DESC LIMIT :limit"),
            params,
        )
        return [_view(row) for row in rows]


@router.get("/{request_id}")
async def get_request(
    request_id: uuid.UUID, _: Principal = Depends(requires(*roles.REQUEST_CHANGES))
) -> dict[str, Any]:
    """One request, including the proposed definition in full."""
    async with engine().connect() as conn:
        row = (
            await conn.execute(
                text(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = :id"), {"id": str(request_id)}
            )
        ).first()
        if row is None:
            raise ApiException.not_found("Change request", request_id)
        return _view(row)


async def _pending(conn: AsyncConnection, request_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text(
                "SELECT id, object_type, object_id, action, payload, summary, status, requested_by"
                " FROM change_request WHERE id = :id"
            ),
            {"id": str(request_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Change request", request_id)
    if row.status != PENDING:
        raise ApiException.conflict(
            "CHANGE_ALREADY_DECIDED",
            f"This request was already {row.status.lower()} and cannot be decided again.",
        )
    return row


async def _decide(
    conn: AsyncConnection, request_id: uuid.UUID, actor: Principal, status: str, note: str | None
) -> None:
    await conn.execute(
        text(
            "UPDATE change_request SET status = :status, decided_by = :actor, decided_at = :now,"
            " decision_note = :note WHERE id = :id"
        ),
        {
            "id": str(request_id),
            "status": status,
            "actor": actor.username,
            "now": datetime.now(UTC),
            "note": note,
        },
    )


@router.post("/{request_id}/approve")
async def approve(
    request_id: uuid.UUID,
    decision: DecisionRequest | None = None,
    actor: Principal = Depends(requires(*roles.APPROVE_CHANGES)),
) -> dict[str, Any]:
    """Apply a pending change. An administrator cannot approve one they raised themselves.

    The proposal is applied by replaying it through the API's own code, so an approved change does
    exactly what a direct call would have done — including the gateway sync, which happens after the
    transaction commits for the reason given in api_admin.py.
    """
    # Imported here: api_admin imports this module to raise requests, so a module-level import in
    # the other direction would be a cycle.
    from . import api_admin

    async with engine().begin() as conn:
        pending = await _pending(conn, request_id)
        if pending.requested_by == actor.username:
            raise ApiException(
                403,
                "SELF_APPROVAL_FORBIDDEN",
                "A change has to be approved by a different administrator from the one who raised "
                "it. Ask another APIM Admin to review this, or withdraw it.",
            )
        if pending.object_type != OBJECT_API:
            raise ApiException.conflict(
                "UNSUPPORTED_OBJECT",
                f"This service cannot apply a {pending.object_type} change.",
            )

        view = await api_admin.apply_approved(conn, pending, actor)
        await _decide(conn, request_id, actor, APPROVED, decision.note if decision else None)
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="APPROVE_" + pending.action,
            object_type=AUDIT_TYPE,
            object_id=str(request_id),
            detail=f"Approved {pending.summary} (requested by {pending.requested_by})",
        )
        row = (
            await conn.execute(
                text(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = :id"), {"id": str(request_id)}
            )
        ).first()
        result = _view(row)

    await api_admin.sync_after_approval(view)
    result["applied"] = view
    return result


@router.post("/{request_id}/reject")
async def reject(
    request_id: uuid.UUID,
    decision: DecisionRequest | None = None,
    actor: Principal = Depends(requires(*roles.APPROVE_CHANGES)),
) -> dict[str, Any]:
    """Refuse a pending change. Nothing about the API changes; the proposal is kept for the record."""
    async with engine().begin() as conn:
        pending = await _pending(conn, request_id)
        if pending.requested_by == actor.username:
            raise ApiException(
                403,
                "SELF_APPROVAL_FORBIDDEN",
                "A change has to be decided by a different administrator from the one who raised it."
                " Withdraw it instead if you no longer want it.",
            )
        await _decide(conn, request_id, actor, REJECTED, decision.note if decision else None)
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="REJECT_" + pending.action,
            object_type=AUDIT_TYPE,
            object_id=str(request_id),
            detail=(
                f"Rejected {pending.summary} (requested by {pending.requested_by})"
                + (f" — {decision.note}" if decision and decision.note else "")
            ),
        )
        row = (
            await conn.execute(
                text(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = :id"), {"id": str(request_id)}
            )
        ).first()
        return _view(row)


@router.post("/{request_id}/withdraw")
async def withdraw(
    request_id: uuid.UUID,
    decision: DecisionRequest | None = None,
    actor: Principal = Depends(requires(*roles.REQUEST_CHANGES)),
) -> dict[str, Any]:
    """Take back a request. Its own author may do this, as may an administrator.

    This is how a developer unblocks themselves after raising the wrong thing, without needing an
    administrator to reject it first.
    """
    async with engine().begin() as conn:
        pending = await _pending(conn, request_id)
        if pending.requested_by != actor.username and not actor.has_role(roles.ADMIN):
            raise ApiException(
                403,
                "FORBIDDEN",
                "Only the person who raised a request, or an APIM Admin, can withdraw it.",
            )
        await _decide(conn, request_id, actor, WITHDRAWN, decision.note if decision else None)
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="WITHDRAW_" + pending.action,
            object_type=AUDIT_TYPE,
            object_id=str(request_id),
            detail=f"Withdrew {pending.summary}",
        )
        row = (
            await conn.execute(
                text(f"SELECT {_COLUMNS} {_FROM} WHERE r.id = :id"), {"id": str(request_id)}
            )
        ).first()
        return _view(row)
