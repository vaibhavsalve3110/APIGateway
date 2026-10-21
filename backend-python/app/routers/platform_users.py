"""APIM users and their roles (CP-LOG-02) — the people who sign in to the management portal.

Administrators only, all of it. This is the module that decides who else can administer the
platform, so a developer being able to reach any of it would make the role boundary meaningless:
they could give themselves ADMIN and approve their own work.

Distinct from `partner_users.py`, which is the Developer Portal's people and belongs to a partner
organization. A row here has no organization and carries ADMIN or DEVELOPER.

There are no passwords. Sign-in is a CAPTCHA and an e-mailed one-time code (see `auth_routes.py`),
so creating a user here is enough for them to sign in — nothing has to be sent to them and there is
no credential to leak. The address *is* the identity.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .. import roles
from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import instant_column, java_instant
from ..db import engine

router = APIRouter(prefix="/api/admin/platform-users", tags=["platform-users"])

AUDIT_TYPE = "PLATFORM_USER"

PlatformRole = Literal["ADMIN", "DEVELOPER"]
RecordStatus = Literal["ACTIVE", "DISABLED"]

# Hibernate's @Email, which is what the Java service validates with. Deliberately not Pydantic's
# EmailStr: that rejects .test and .local, which the fixtures and this network both use.
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_COLUMNS = f"""
    id, email, full_name, role, status, created_by,
    {instant_column("created_at", "created_at")},
    {instant_column("updated_at", "updated_at")},
    {instant_column("last_login_at", "last_login_at")}
"""


class UserRequest(BaseModel):
    fullName: str = Field(min_length=1, max_length=160)  # noqa: N815 - field names are the contract
    email: str = Field(min_length=3, max_length=200)
    role: PlatformRole
    status: RecordStatus | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL.match(value):
            raise ValueError("must be a valid e-mail address")
        return value


class RoleRequest(BaseModel):
    role: PlatformRole


class StatusRequest(BaseModel):
    status: RecordStatus


def _view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "email": row.email,
        "fullName": row.full_name,
        "role": row.role,
        "status": row.status,
        "createdBy": row.created_by,
        "createdAt": java_instant(row.created_at),
        "updatedAt": java_instant(row.updated_at),
        # Null until they have signed in once, which is how an account created and never used is
        # spotted in a review.
        "lastLoginAt": java_instant(row.last_login_at),
    }


async def _load(conn: AsyncConnection, user_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(f"SELECT {_COLUMNS} FROM platform_user WHERE id = :id"), {"id": str(user_id)}
        )
    ).first()
    if row is None:
        raise ApiException.not_found("APIM user", user_id)
    return _view(row)


async def _require(conn: AsyncConnection, user_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text("SELECT id, email, full_name, role, status FROM platform_user WHERE id = :id"),
            {"id": str(user_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("APIM user", user_id)
    return row


async def _active_admins(conn: AsyncConnection, excluding: uuid.UUID) -> int:
    row = (
        await conn.execute(
            text(
                "SELECT count(*) AS n FROM platform_user"
                " WHERE role = 'ADMIN' AND status = 'ACTIVE' AND id <> :id"
            ),
            {"id": str(excluding)},
        )
    ).first()
    return int(row.n)


async def _guard_last_admin(conn: AsyncConnection, user: Any, what: str) -> None:
    """Refuse a change that would leave the platform with no administrator.

    Nothing could then be approved, no user could be created, and nobody could put it right from
    inside the portal — it would need somebody with database access. Worth one query to prevent.

    Note this allows going down to a single administrator, which is a state the platform can reach
    and work in, except that nothing can be approved: an approval needs a second administrator. The
    approvals screen says so when it happens.
    """
    if user.role == "ADMIN" and user.status == "ACTIVE" and await _active_admins(conn, user.id) == 0:
        raise ApiException.conflict(
            "LAST_ADMIN",
            f"{user.email} is the only active APIM Admin, so {what} would leave the platform with "
            "none. Make somebody else an admin first.",
        )


async def _audit(conn: AsyncConnection, actor: Principal, action: str, user_id: Any, detail: str) -> None:
    await audit.record(
        conn,
        actor=actor.username,
        actor_role=actor.roles[0] if actor.roles else None,
        action=action,
        object_type=AUDIT_TYPE,
        object_id=str(user_id),
        detail=detail,
    )


@router.get("")
async def list_users(_: Principal = Depends(requires(*roles.ADMIN_ONLY))) -> list[dict[str, Any]]:
    """Everyone who can sign in to the management portal, administrators first."""
    async with engine().connect() as conn:
        rows = await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM platform_user"
                " ORDER BY CASE role WHEN 'ADMIN' THEN 0 ELSE 1 END, full_name ASC"
            )
        )
        return [_view(row) for row in rows]


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID, _: Principal = Depends(requires(*roles.ADMIN_ONLY))
) -> dict[str, Any]:
    """One APIM user."""
    async with engine().connect() as conn:
        return await _load(conn, user_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserRequest, actor: Principal = Depends(requires(*roles.ADMIN_ONLY))
) -> dict[str, Any]:
    """Add someone to the management portal. They can sign in immediately with a one-time code.

    The address must not already belong to a Developer Portal user: one address is one person, and
    the same address on both sides would make a session's role depend on which table was consulted.
    """
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    async with engine().begin() as conn:
        clash = (
            await conn.execute(
                text("SELECT partner_id FROM partner_user WHERE LOWER(email) = :email"),
                {"email": request.email},
            )
        ).first()
        if clash is not None:
            raise ApiException.conflict(
                "EMAIL_IN_USE",
                f"{request.email} is already a Developer Portal user. One address belongs to one "
                "person, so it cannot also be an APIM user.",
            )
        await conn.execute(
            text(
                """
                INSERT INTO platform_user
                    (id, email, full_name, role, status, created_at, created_by, updated_at)
                VALUES (:id, :email, :full_name, :role, :status, :now, :actor, :now)
                """
            ),
            {
                "id": str(user_id),
                "email": request.email,
                "full_name": request.fullName.strip(),
                "role": request.role,
                "status": request.status or "ACTIVE",
                "now": now,
                "actor": actor.username,
            },
        )
        await _audit(
            conn, actor, "CREATE", user_id, f"{request.email} added as {request.role}"
        )
        return await _load(conn, user_id)


@router.put("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    request: UserRequest,
    actor: Principal = Depends(requires(*roles.ADMIN_ONLY)),
) -> dict[str, Any]:
    """Change a user's name, role or status.

    The e-mail address is not changeable here: it is the identity the audit trail and the one-time
    codes are keyed on. A different address is a different person — create them and disable this one.
    """
    async with engine().begin() as conn:
        user = await _require(conn, user_id)
        new_status = request.status or user.status
        if request.role != "ADMIN" or new_status != "ACTIVE":
            await _guard_last_admin(conn, user, "this change")
        await conn.execute(
            text(
                "UPDATE platform_user SET full_name = :full_name, role = :role, status = :status,"
                " updated_at = :now WHERE id = :id"
            ),
            {
                "id": str(user_id),
                "full_name": request.fullName.strip(),
                "role": request.role,
                "status": new_status,
                "now": datetime.now(UTC),
            },
        )
        changes = []
        if user.role != request.role:
            changes.append(f"role {user.role} -> {request.role}")
        if user.status != new_status:
            changes.append(f"status {user.status} -> {new_status}")
        if user.full_name != request.fullName.strip():
            changes.append("name")
        await _audit(
            conn,
            actor,
            "UPDATE",
            user_id,
            f"{user.email} updated" + (f": {', '.join(changes)}" if changes else " (no change)"),
        )
        return await _load(conn, user_id)


@router.put("/{user_id}/role")
async def set_role(
    user_id: uuid.UUID,
    request: RoleRequest,
    actor: Principal = Depends(requires(*roles.ADMIN_ONLY)),
) -> dict[str, Any]:
    """Set just the role, which is the change the portal's list makes most often."""
    async with engine().begin() as conn:
        user = await _require(conn, user_id)
        if user.role == request.role:
            return await _load(conn, user_id)
        if request.role != "ADMIN":
            await _guard_last_admin(conn, user, "taking their admin role away")
        await conn.execute(
            text("UPDATE platform_user SET role = :role, updated_at = :now WHERE id = :id"),
            {"id": str(user_id), "role": request.role, "now": datetime.now(UTC)},
        )
        await _audit(
            conn, actor, "SET_ROLE", user_id, f"{user.email} role {user.role} -> {request.role}"
        )
        return await _load(conn, user_id)


@router.put("/{user_id}/status")
async def set_status(
    user_id: uuid.UUID,
    request: StatusRequest,
    actor: Principal = Depends(requires(*roles.ADMIN_ONLY)),
) -> dict[str, Any]:
    """Suspend or reinstate an account. Disabling stops them signing in; their trail stays."""
    async with engine().begin() as conn:
        user = await _require(conn, user_id)
        if user.status == request.status:
            return await _load(conn, user_id)
        if request.status == "DISABLED":
            await _guard_last_admin(conn, user, "disabling them")
        await conn.execute(
            text("UPDATE platform_user SET status = :status, updated_at = :now WHERE id = :id"),
            {"id": str(user_id), "status": request.status, "now": datetime.now(UTC)},
        )
        await _audit(
            conn,
            actor,
            "REVOKE_ACCESS" if request.status == "DISABLED" else "GRANT_ACCESS",
            user_id,
            f"{user.email} {'suspended' if request.status == 'DISABLED' else 'reinstated'}",
        )
        return await _load(conn, user_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID, actor: Principal = Depends(requires(*roles.ADMIN_ONLY))
) -> Response:
    """Remove an account. What they did stays in the audit trail, which is keyed on the address."""
    async with engine().begin() as conn:
        user = await _require(conn, user_id)
        await _guard_last_admin(conn, user, "deleting them")
        await conn.execute(text("DELETE FROM platform_user WHERE id = :id"), {"id": str(user_id)})
        await _audit(conn, actor, "DELETE", user_id, f"{user.email} removed from the APIM portal")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
