"""Partner user accounts (CP-PTN-04).

A partner user is a login for the Developer Portal. The organization holds the credentials — the
signature key pair and the IPV salt — so nothing secret lives on the user record, and deleting a user
never touches a key.

The e-mail is the sign-in identity and stays unique across every organization, which is why a change
of address is checked against all of them rather than only the user's own partner.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import instant_column, java_instant
from ..db import connection, engine

router = APIRouter(prefix="/api/admin")

AUDIT_TYPE = "PARTNER_USER"


class PartnerUserRole(StrEnum):
    PARTNER_ADMIN = "PARTNER_ADMIN"
    PARTNER_DEVELOPER = "PARTNER_DEVELOPER"
    PARTNER_VIEWER = "PARTNER_VIEWER"


class RecordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


# Matches Hibernate Validator's @Email, which is what backend-java enforces: a local part, an @, and
# a dotted domain. Pydantic's EmailStr is deliberately not used — it rejects reserved and special-use
# domains such as .test and .local, which Java accepts, so the two services would disagree about
# which addresses are valid.
EMAIL_PATTERN = (
    r"^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~.-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


class CreateRequest(BaseModel):
    fullName: str = Field(min_length=1, max_length=160)  # noqa: N815
    email: str = Field(min_length=1, max_length=200, pattern=EMAIL_PATTERN)
    role: PartnerUserRole


class UpdateRequest(CreateRequest):
    """The e-mail is the portal sign-in and can be corrected; it stays unique across organizations."""


class AccessRequest(BaseModel):
    status: RecordStatus


_COLUMNS = f"""
    u.id, u.partner_id, p.code AS partner_code, p.name AS partner_name,
    u.full_name, u.email, u.role, u.status, u.created_by,
    {instant_column('u.created_at', 'created_at')},
    {instant_column('u.updated_at', 'updated_at')}
"""


def _view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "partnerId": str(row.partner_id),
        "partnerCode": row.partner_code,
        "partnerName": row.partner_name,
        "fullName": row.full_name,
        "email": row.email,
        "role": row.role,
        "status": row.status,
        "createdBy": row.created_by,
        "createdAt": java_instant(row.created_at),
        "updatedAt": java_instant(row.updated_at),
    }


def _normalise(email: str) -> str:
    return email.strip().lower()


async def _load(conn: AsyncConnection, user_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM partner_user u"
                " JOIN partner p ON p.id = u.partner_id WHERE u.id = :id"
            ),
            {"id": str(user_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Partner user", user_id)
    return _view(row)


async def _require_raw(conn: AsyncConnection, user_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text("SELECT id, partner_id, email, status FROM partner_user WHERE id = :id"),
            {"id": str(user_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Partner user", user_id)
    return row


async def _require_partner(conn: AsyncConnection, partner_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text("SELECT id, code, name, status FROM partner WHERE id = :id"), {"id": str(partner_id)}
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Partner", partner_id)
    return row


async def _email_taken(conn: AsyncConnection, email: str) -> bool:
    return (
        await conn.execute(text("SELECT 1 FROM partner_user WHERE email = :email"), {"email": email})
    ).first() is not None


@router.get("/partner-users", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def list_users(
    partnerId: uuid.UUID | None = None,  # noqa: N803 - query name matches the Java API
    conn: AsyncConnection = Depends(connection),
) -> list[dict[str, Any]]:
    if partnerId is not None:
        await _require_partner(conn, partnerId)
    rows = await conn.execute(
        text(
            f"""SELECT {_COLUMNS}
                  FROM partner_user u
                  JOIN partner p ON p.id = u.partner_id
                 WHERE (CAST(:partner_id AS uuid) IS NULL OR u.partner_id = :partner_id)
                 ORDER BY u.full_name ASC"""
        ),
        {"partner_id": str(partnerId) if partnerId else None},
    )
    return [_view(r) for r in rows]


@router.get("/partner-users/{user_id}", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def get_user(user_id: uuid.UUID, conn: AsyncConnection = Depends(connection)) -> dict[str, Any]:
    return await _load(conn, user_id)


@router.get(
    "/partners/{partner_id}/users", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))]
)
async def list_for_partner(
    partner_id: uuid.UUID, conn: AsyncConnection = Depends(connection)
) -> list[dict[str, Any]]:
    await _require_partner(conn, partner_id)
    rows = await conn.execute(
        text(
            f"""SELECT {_COLUMNS}
                  FROM partner_user u
                  JOIN partner p ON p.id = u.partner_id
                 WHERE u.partner_id = :partner_id
                 ORDER BY u.full_name ASC"""
        ),
        {"partner_id": str(partner_id)},
    )
    return [_view(r) for r in rows]


@router.post("/partners/{partner_id}/users")
async def create_user(
    partner_id: uuid.UUID,
    request: CreateRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        partner = await _require_partner(conn, partner_id)
        if partner.status == "DISABLED":
            raise ApiException.conflict(
                "PARTNER_DISABLED",
                f"Partner {partner.name} is disabled — re-enable it before adding users",
            )
        email = _normalise(request.email)
        if await _email_taken(conn, email):
            raise ApiException.conflict(
                "EMAIL_IN_USE", f"A partner user with email {email} already exists"
            )

        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        await conn.execute(
            text(
                """
                INSERT INTO partner_user (id, partner_id, email, full_name, role, status,
                                          created_at, created_by, updated_at)
                VALUES (:id, :partner_id, :email, :full_name, :role, 'ACTIVE', :now, :by, :now)
                """
            ),
            {
                "id": str(user_id),
                "partner_id": str(partner.id),
                "email": email,
                "full_name": request.fullName.strip(),
                "role": request.role.value,
                "now": now,
                "by": actor.username,
            },
        )
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="CREATE",
            object_type=AUDIT_TYPE,
            object_id=str(user_id),
            detail=f"Portal user {email} added to {partner.name} ({partner.code}) as {request.role.value}",
        )
        return await _load(conn, user_id)


@router.put("/partner-users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    request: UpdateRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        user = await _require_raw(conn, user_id)
        previous_email = user.email
        email = _normalise(request.email)
        if email != previous_email and await _email_taken(conn, email):
            raise ApiException.conflict(
                "EMAIL_IN_USE", f"A partner user with email {email} already exists"
            )
        await conn.execute(
            text(
                "UPDATE partner_user SET full_name = :full_name, email = :email, role = :role,"
                " updated_at = :now WHERE id = :id"
            ),
            {
                "id": str(user_id),
                "full_name": request.fullName.strip(),
                "email": email,
                "role": request.role.value,
                "now": datetime.now(UTC),
            },
        )
        detail = (
            f"Portal user {email} updated; role {request.role.value}"
            if email == previous_email
            else f"Portal user email changed from {previous_email} to {email}; role {request.role.value}"
        )
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="UPDATE",
            object_type=AUDIT_TYPE,
            object_id=str(user_id),
            detail=detail,
        )
        return await _load(conn, user_id)


@router.post("/partner-users/{user_id}/access")
async def set_access(
    user_id: uuid.UUID,
    request: AccessRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        user = await _require_raw(conn, user_id)
        # Setting the status it already has is a no-op, and must not leave a misleading audit row.
        if user.status == request.status.value:
            return await _load(conn, user_id)
        await conn.execute(
            text("UPDATE partner_user SET status = :status, updated_at = :now WHERE id = :id"),
            {"id": str(user_id), "status": request.status.value, "now": datetime.now(UTC)},
        )
        revoked = request.status is RecordStatus.DISABLED
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="REVOKE_ACCESS" if revoked else "GRANT_ACCESS",
            object_type=AUDIT_TYPE,
            object_id=str(user_id),
            detail="Developer Portal access "
            + ("revoked from " if revoked else "granted to ")
            + user.email,
        )
        return await _load(conn, user_id)


@router.delete("/partner-users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> Response:
    async with engine().begin() as conn:
        user = await _require_raw(conn, user_id)
        # Deleting an account that can still sign in would be a silent revocation; make it deliberate.
        if user.status != "DISABLED":
            raise ApiException.conflict(
                "ACCESS_NOT_REVOKED", f"Revoke {user.email}'s access before deleting the account"
            )
        partner = await _require_partner(conn, user.partner_id)
        await conn.execute(text("DELETE FROM partner_user WHERE id = :id"), {"id": str(user_id)})
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="DELETE",
            object_type=AUDIT_TYPE,
            object_id=str(user_id),
            detail=f"Portal user {user.email} deleted from {partner.name} ({partner.code})",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
