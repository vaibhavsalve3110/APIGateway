"""Security keys (BRD CP-SEC-04, CP-SEC-05, CP-SEC-09).

A key is shown once and never stored: only a SHA-256 hash of it goes to the database, and the same
hash goes to the gateway, where a pre-auth function hashes whatever the caller presented before
comparing. So the platform cannot tell anyone their key, and neither can the gateway.

Rotation overlaps rather than cutting over. Generating a new key moves the current one to EXPIRING
with an expiry 20 minutes out, so a partner can switch systems across without an outage; a scheduled
job ends the old key at that moment.

Everything here writes, and three notices go out once the transaction commits — see notifications.py.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import java_instant
from ..db import connection, engine
from ..gateway import SHORT_CODE, GatewayClient
from ..notifications import notify_key_generated
from ..settings import get_settings
from .partner_portal import list_keys

router = APIRouter()

AUDIT_TYPE = "SECURITY_KEY"
LIVE = ("ACTIVE", "EXPIRING")
SECRET_BYTES = 32

Environment = Literal["SANDBOX", "PRODUCTION"]


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class KeyMaterial:
    """`agw_<env>_<43 url-safe base64 chars>`, its SHA-256 hex, and the masked form the portals show."""

    def __init__(self, plaintext: str, key_hash: str, masked: str):
        self.plaintext = plaintext
        self.hash = key_hash
        self.masked = masked

    @staticmethod
    def generate(environment: str) -> "KeyMaterial":
        prefix = f"agw_{SHORT_CODE[environment]}_"
        plaintext = prefix + secrets.token_urlsafe(SECRET_BYTES).rstrip("=")
        return KeyMaterial(plaintext, sha256_hex(plaintext), prefix + "•" * 8 + plaintext[-4:])

    def __repr__(self) -> str:  # a key must never reach a log line
        return f"KeyMaterial[{self.masked}]"


async def _partner(conn: AsyncConnection, partner_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text(
                "SELECT id, code, name, status, access_tier, client_id_sandbox, client_id_production"
                "  FROM partner WHERE id = :id"
            ),
            {"id": str(partner_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Partner", partner_id)
    return row


def _client_id(partner: Any, environment: str) -> str:
    return partner.client_id_production if environment == "PRODUCTION" else partner.client_id_sandbox


async def _key_view(conn: AsyncConnection, key_id: uuid.UUID) -> dict[str, Any]:
    for key in await list_keys(conn, (await _key_row(conn, key_id)).partner_id):
        if key["id"] == str(key_id):
            return key
    raise ApiException.not_found("Security key", key_id)


async def _key_row(conn: AsyncConnection, key_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text(
                "SELECT id, partner_id, environment, masked_key, status, expires_at"
                "  FROM security_key WHERE id = :id"
            ),
            {"id": str(key_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Security key", key_id)
    return row


async def _audit(
    conn: AsyncConnection, actor: str, role: str | None, action: str, key_id: Any, detail: str
) -> None:
    await audit.record(
        conn,
        actor=actor,
        actor_role=role,
        action=action,
        object_type=AUDIT_TYPE,
        object_id=str(key_id),
        detail=detail,
    )


async def generate_key(partner_id: uuid.UUID, environment: str, actor: Principal) -> dict[str, Any]:
    """Shared by the admin route and the Developer Portal's own."""
    settings = get_settings()
    overlap = timedelta(minutes=settings.key_overlap_minutes)
    material = KeyMaterial.generate(environment)
    key_id = uuid.uuid4()

    async with engine().begin() as conn:
        partner = await _partner(conn, partner_id)
        if partner.status != "ACTIVE":
            raise ApiException.conflict(
                "PARTNER_DISABLED", f"{partner.name} is disabled — keys cannot be issued"
            )
        if environment == "PRODUCTION" and partner.access_tier != "PRODUCTION":
            raise ApiException.forbidden(
                "PRODUCTION_NOT_PROVISIONED",
                f"{partner.name} is on the UAT-only access tier — Production keys cannot be issued",
            )

        live = list(
            await conn.execute(
                text(
                    "SELECT id, status, expires_at FROM security_key"
                    " WHERE partner_id = :partner_id AND environment = :environment"
                    "   AND status IN ('ACTIVE','EXPIRING')"
                ),
                {"partner_id": str(partner_id), "environment": environment},
            )
        )
        # A second rotation inside the window would leave two old keys to expire and no way to say
        # which one a partner is still using.
        for row in live:
            if row.status == "EXPIRING":
                raise ApiException.conflict(
                    "ROTATION_WINDOW_OPEN",
                    "A key rotation is already in progress. The previous key expires at "
                    f"{java_instant(row.expires_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z')}"
                    "; a new key can be generated after that.",
                )

        now = datetime.now(UTC)
        previous_expires_at: datetime | None = None
        for row in live:  # at most one ACTIVE key exists here
            previous_expires_at = now + overlap
            await conn.execute(
                text(
                    "UPDATE security_key SET status = 'EXPIRING', expires_at = :expires WHERE id = :id"
                ),
                {"id": str(row.id), "expires": previous_expires_at},
            )

        await conn.execute(
            text(
                """
                INSERT INTO security_key
                    (id, partner_id, environment, key_hash, masked_key, status, created_at, created_by)
                VALUES (:id, :partner_id, :environment, :key_hash, :masked, 'ACTIVE', :now, :by)
                """
            ),
            {
                "id": str(key_id),
                "partner_id": str(partner_id),
                "environment": environment,
                "key_hash": material.hash,
                "masked": material.masked,
                "now": now,
                "by": actor.username,
            },
        )
        expires_text = (
            ""
            if previous_expires_at is None
            else "; previous key stays valid until "
            + str(java_instant(previous_expires_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"))
        )
        await _audit(
            conn, actor.username, actor.roles[0] if actor.roles else None, "GENERATE", key_id,
            f"{environment} key {material.masked} generated for {partner.code}{expires_text}",
        )
        view = await _key_view(conn, key_id)

    client_id = _client_id(partner, environment)
    gateway = GatewayClient()
    await gateway.ensure_consumer(environment, client_id, partner.code, partner.name)
    await gateway.put_credential(environment, client_id, str(key_id), material.hash)

    # Only once the key exists and the gateway accepts it: nobody is told about a rotation that failed.
    await notify_key_generated(
        partner_id=str(partner_id),
        partner_code=partner.code,
        partner_name=partner.name,
        environment=environment,
        masked_key=material.masked,
        plaintext=material.plaintext,
        client_id=client_id,
        previous_expires_at=previous_expires_at,
        actor_username=actor.username,
        by_partner=actor.has_role("PARTNER"),
    )

    return {
        "key": view,
        "plaintext": material.plaintext,
        "clientId": client_id,
        "previousKeyExpiresAt": (
            java_instant(previous_expires_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z")
            if previous_expires_at
            else None
        ),
    }


@router.get(
    "/api/admin/partners/{partner_id}/keys",
    dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))],
)
async def admin_list_keys(
    partner_id: uuid.UUID, conn: AsyncConnection = Depends(connection)
) -> list[dict[str, Any]]:
    await _partner(conn, partner_id)
    return await list_keys(conn, partner_id)


@router.post("/api/admin/partners/{partner_id}/keys/{environment}", status_code=201)
async def admin_generate_key(
    partner_id: uuid.UUID,
    environment: Environment,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    return await generate_key(partner_id, environment, actor)


@router.post("/api/partner/keys/{environment}", status_code=201)
async def partner_generate_key(
    environment: Environment,
    principal: Principal = Depends(requires("PARTNER")),
) -> dict[str, Any]:
    """CP-SEC-05: only a Partner Admin of the organization may rotate its own key."""
    async with engine().connect() as conn:
        if not principal.partner_code:
            raise ApiException(403, "NOT_A_PARTNER", "This endpoint is for Developer Portal users")
        partner = (
            await conn.execute(
                text("SELECT id, name FROM partner WHERE code = :code"),
                {"code": principal.partner_code},
            )
        ).first()
        if partner is None:
            raise ApiException.not_found("Partner", principal.partner_code)
        user = (
            await conn.execute(
                text(
                    "SELECT role, status FROM partner_user"
                    " WHERE email = :email AND partner_id = :partner_id"
                ),
                {"email": principal.username.lower(), "partner_id": str(partner.id)},
            )
        ).first()
        if user is None or user.role != "PARTNER_ADMIN" or user.status != "ACTIVE":
            raise ApiException.forbidden(
                "NOT_PARTNER_ADMIN",
                f"Only a Partner Admin of {partner.name} can generate security keys. "
                "Ask your Partner Admin, or your APIM Admin, to rotate the key.",
            )
    return await generate_key(partner.id, environment, principal)


@router.post("/api/admin/keys/{key_id}/revoke")
async def revoke_key(
    key_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    """Undo a rotation: discard the new key and put the previous one back, inside the window only."""
    overlap_minutes = get_settings().key_overlap_minutes
    async with engine().begin() as conn:
        key = await _key_row(conn, key_id)
        now = datetime.now(UTC)
        previous = (
            await conn.execute(
                text(
                    "SELECT id, masked_key FROM security_key"
                    " WHERE partner_id = :partner_id AND environment = :environment"
                    "   AND status = 'EXPIRING' AND expires_at > :now"
                    " LIMIT 1"
                ),
                {
                    "partner_id": str(key.partner_id),
                    "environment": key.environment,
                    "now": now,
                },
            )
        ).first()
        if key.status != "ACTIVE" or previous is None:
            raise ApiException.conflict(
                "REVOKE_WINDOW_CLOSED",
                "Only a newly generated key can be revoked, and only while the previous key is "
                f"still within its {overlap_minutes}-minute overlap window",
            )
        partner = await _partner(conn, key.partner_id)
        await conn.execute(
            text(
                "UPDATE security_key SET status = 'REVOKED', expires_at = NULL, ended_at = :now"
                " WHERE id = :id"
            ),
            {"id": str(key_id), "now": now},
        )
        await conn.execute(
            text("UPDATE security_key SET status = 'ACTIVE', expires_at = NULL WHERE id = :id"),
            {"id": str(previous.id)},
        )
        await _audit(
            conn, actor.username, actor.roles[0] if actor.roles else None, "REVOKE", key_id,
            f"{key.environment} key {key.masked_key} revoked within the overlap window; "
            f"{previous.masked_key} reinstated as the active key",
        )
        view = await _key_view(conn, key_id)

    await GatewayClient().delete_credential(
        key.environment, _client_id(partner, key.environment), str(key_id)
    )
    return view


async def revoke_all(
    conn: AsyncConnection, partner: Any, environments: tuple[str, ...], actor: Principal, reason: str
) -> list[tuple[str, str]]:
    """Revoke every live key of an organization. Used when access is withdrawn or it is disabled.

    Returns the gateway credentials to delete, so the caller can do that outside the transaction.
    """
    now = datetime.now(UTC)
    rows = list(
        await conn.execute(
            text(
                "SELECT id, environment, masked_key FROM security_key"
                " WHERE partner_id = :partner_id AND status IN ('ACTIVE','EXPIRING')"
            ),
            {"partner_id": str(partner.id)},
        )
    )
    pending: list[tuple[str, str]] = []
    for row in rows:
        if row.environment not in environments:
            continue
        await conn.execute(
            text(
                "UPDATE security_key SET status = 'REVOKED', expires_at = NULL, ended_at = :now"
                " WHERE id = :id"
            ),
            {"id": str(row.id), "now": now},
        )
        # A production credential only exists at the gateway once a production Client ID was issued.
        if row.environment == "SANDBOX" or partner.client_id_production is not None:
            pending.append((row.environment, str(row.id)))
        await _audit(
            conn, actor.username, actor.roles[0] if actor.roles else None, "REVOKE", row.id,
            f"{row.environment} key {row.masked_key} revoked — {reason}",
        )
    return pending
