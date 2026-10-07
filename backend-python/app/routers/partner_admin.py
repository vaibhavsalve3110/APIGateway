"""Organizations — the write side (CP-PTN-01 to CP-PTN-03, BRD 6.2).

Registering an organization issues its credentials in the same transaction: an RSA signature key pair
and an IPV salt. The private key and the salt are returned once and then unrecoverable — only the
public key, the fingerprint, the masked salt and the encrypted salt are kept.

Access tier and status changes publish nothing to the gateway beyond the consumer record; revoking
production access or disabling an organization is what the key lifecycle reacts to, and that work
belongs to phase 5. Until then those two paths are deliberately refused rather than silently
half-done — see `_unsupported`.
"""

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import java_instant
from ..credentials import SHOWN_ONCE, IpvSaltMaterial, SignatureKeyMaterial
from ..crypto import SecretCipher
from ..db import engine
from ..gateway import GatewayClient
from .catalogue import _PARTNER_COLUMNS, _partner_view
from .partner_users import EMAIL_PATTERN

router = APIRouter(prefix="/api/admin")

AUDIT_PARTNER = "PARTNER"
AUDIT_GROUP = "PARTNER_GROUP"

AccessTier = Literal["UAT_ONLY", "PRODUCTION"]
RecordStatus = Literal["ACTIVE", "DISABLED"]

#: Words dropped from an organization name when deriving its Client ID.
_COMPANY_SUFFIX = re.compile(r"\b(pvt|private|ltd|limited|llp|inc)\b")


class GroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class PartnerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    groupId: uuid.UUID  # noqa: N815
    contactEmail: str | None = Field(  # noqa: N815
        default=None, max_length=200, pattern=EMAIL_PATTERN
    )


class UpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    contactEmail: str | None = Field(  # noqa: N815
        default=None, max_length=200, pattern=EMAIL_PATTERN
    )


class TierRequest(BaseModel):
    accessTier: AccessTier  # noqa: N815


class StatusRequest(BaseModel):
    status: RecordStatus


def _slug(name: str) -> str:
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = _COMPANY_SUFFIX.sub("", stripped.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"(^-+|-+$)", "", slug)
    if len(slug) > 40:
        slug = re.sub(r"-+$", "", slug[:40])
    return slug or "partner"


async def _unique_client_id(conn: AsyncConnection, name: str, environment: str) -> str:
    base = _slug(name)
    short = "sbx" if environment == "SANDBOX" else "prd"
    attempt = 1
    while True:
        candidate = (base if attempt == 1 else f"{base}-{attempt}") + f"-{short}"
        taken = (
            await conn.execute(
                text(
                    "SELECT 1 FROM partner"
                    " WHERE client_id_sandbox = :c OR client_id_production = :c"
                ),
                {"c": candidate},
            )
        ).first()
        if taken is None:
            return candidate
        attempt += 1


async def _next_code(conn: AsyncConnection) -> str:
    count = (await conn.execute(text("SELECT COUNT(*) AS n FROM partner"))).one().n
    number = int(count) + 1
    while True:
        code = f"PTN-{number:05d}"
        taken = (
            await conn.execute(text("SELECT 1 FROM partner WHERE code = :code"), {"code": code})
        ).first()
        if taken is None:
            return code
        number += 1


async def _view(conn: AsyncConnection, partner_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                f"""SELECT {_PARTNER_COLUMNS}
                      FROM partner p
                      LEFT JOIN partner_group g ON g.id = p.group_id
                     WHERE p.id = :id"""
            ),
            {"id": str(partner_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Partner", partner_id)
    return _partner_view(row)


async def _require(conn: AsyncConnection, partner_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text(
                "SELECT id, code, name, contact_email, access_tier, status, client_id_production,"
                " ipv_salt_cipher, ipv_salt_masked, signature_fingerprint"
                " FROM partner WHERE id = :id"
            ),
            {"id": str(partner_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Partner", partner_id)
    return row


async def _audit(
    conn: AsyncConnection, actor: Principal, action: str, obj: str, oid: Any, detail: str
) -> None:
    await audit.record(
        conn,
        actor=actor.username,
        actor_role=actor.roles[0] if actor.roles else None,
        action=action,
        object_type=obj,
        object_id=str(oid),
        detail=detail,
    )


def _unsupported(what: str) -> ApiException:
    """Refuse rather than half-do it.

    Revoking production access and disabling an organization both have to revoke security keys,
    which backend-java does through an event the key lifecycle listens to. That lifecycle is phase 5.
    Performing the database half here would leave live keys behind — worse than not accepting it.
    """
    return ApiException(
        501,
        "NOT_MIGRATED",
        f"{what} is still handled by the Java control plane while key revocation is being migrated",
    )


# --------------------------------------------------------------------------- groups


@router.post("/partner-groups", status_code=201)
async def create_group(
    request: GroupRequest, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    async with engine().begin() as conn:
        group_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO partner_group (id, name, description, status, created_at)"
                " VALUES (:id, :name, :description, 'ACTIVE', :now)"
            ),
            {
                "id": str(group_id),
                "name": request.name.strip(),
                "description": request.description.strip() if request.description else None,
                "now": datetime.now(UTC),
            },
        )
        await _audit(
            conn, actor, "CREATE", AUDIT_GROUP, group_id,
            f"Partner group {request.name.strip()} created",
        )
        return {
            "id": str(group_id),
            "name": request.name.strip(),
            "description": request.description.strip() if request.description else None,
            "status": "ACTIVE",
            "partnerCount": 0,
        }


# --------------------------------------------------------------------------- organizations


@router.post("/partners", status_code=201)
async def register_partner(
    request: PartnerRequest, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    """CP-PTN-01: register an organization and issue its credentials, once."""
    signature = SignatureKeyMaterial.generate()
    salt = IpvSaltMaterial.generate()
    cipher = SecretCipher()

    async with engine().begin() as conn:
        group = (
            await conn.execute(
                text("SELECT id, name FROM partner_group WHERE id = :id"),
                {"id": str(request.groupId)},
            )
        ).first()
        if group is None:
            raise ApiException.not_found("Partner group", request.groupId)

        partner_id = uuid.uuid4()
        name = request.name.strip()
        code = await _next_code(conn)
        client_id = await _unique_client_id(conn, name, "SANDBOX")
        now = datetime.now(UTC)

        await conn.execute(
            text(
                """
                INSERT INTO partner
                    (id, code, name, group_id, access_tier, status, contact_email,
                     client_id_sandbox, created_at, updated_at,
                     signature_algorithm, signature_public_key, signature_fingerprint, signature_created_at,
                     ipv_salt_cipher, ipv_salt_masked, ipv_salt_created_at)
                VALUES (:id, :code, :name, :group_id, 'UAT_ONLY', 'ACTIVE', :contact_email,
                        :client_id, :now, :now,
                        :algorithm, :public_key, :fingerprint, :now,
                        :salt_cipher, :salt_masked, :now)
                """
            ),
            {
                "id": str(partner_id),
                "code": code,
                "name": name,
                "group_id": str(group.id),
                "contact_email": request.contactEmail.strip() if request.contactEmail else None,
                "client_id": client_id,
                "now": now,
                "algorithm": signature.algorithm,
                "public_key": signature.public_key_pem,
                "fingerprint": signature.fingerprint,
                "salt_cipher": cipher.encrypt(salt.plaintext),
                "salt_masked": salt.masked,
            },
        )
        await _audit(
            conn, actor, "CREATE", AUDIT_PARTNER, partner_id,
            f"{name} ({code}) added to {group.name} with UAT-only access; sandbox Client ID {client_id}",
        )
        await _audit(
            conn, actor, "ISSUE_CREDENTIALS", AUDIT_PARTNER, partner_id,
            f"Signature key {signature.fingerprint} and IPV salt {salt.masked} issued to {name}",
        )
        view = await _view(conn, partner_id)

    await GatewayClient().ensure_consumer("SANDBOX", client_id, code, name)
    return {
        "partner": view,
        "privateKeyPem": signature.private_key_pem,
        "publicKeyPem": signature.public_key_pem,
        "ipvSalt": salt.plaintext,
        "notice": SHOWN_ONCE,
    }


@router.put("/partners/{partner_id}")
async def update_partner(
    partner_id: uuid.UUID,
    request: UpdateRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        partner = await _require(conn, partner_id)
        before = f"{partner.name} <{partner.contact_email or ''}>"
        name = request.name.strip()
        raw_email = request.contactEmail
        email = raw_email.strip() if raw_email and raw_email.strip() else None
        await conn.execute(
            text(
                "UPDATE partner SET name = :name, contact_email = :email, updated_at = :now"
                " WHERE id = :id"
            ),
            {"id": str(partner_id), "name": name, "email": email, "now": datetime.now(UTC)},
        )
        await _audit(
            conn, actor, "UPDATE", AUDIT_PARTNER, partner_id,
            f"Organization details changed from {before} to {name} <{email or ''}>",
        )
        return await _view(conn, partner_id)


@router.put("/partners/{partner_id}/access-tier")
async def change_tier(
    partner_id: uuid.UUID,
    request: TierRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        partner = await _require(conn, partner_id)
        if partner.access_tier == request.accessTier:
            return await _view(conn, partner_id)
        if request.accessTier != "PRODUCTION":
            raise _unsupported("Withdrawing production access")

        client_id = partner.client_id_production or await _unique_client_id(
            conn, partner.name, "PRODUCTION"
        )
        await conn.execute(
            text(
                "UPDATE partner SET access_tier = :tier, client_id_production = :client_id,"
                " updated_at = :now WHERE id = :id"
            ),
            {
                "id": str(partner_id),
                "tier": request.accessTier,
                "client_id": client_id,
                "now": datetime.now(UTC),
            },
        )
        await _audit(
            conn, actor, "ACCESS_TIER", AUDIT_PARTNER, partner_id,
            f"Access tier changed from {partner.access_tier} to {request.accessTier}",
        )
        view = await _view(conn, partner_id)

    await GatewayClient().ensure_consumer("PRODUCTION", client_id, partner.code, partner.name)
    return view


@router.put("/partners/{partner_id}/status")
async def set_status(
    partner_id: uuid.UUID,
    request: StatusRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        partner = await _require(conn, partner_id)
        if partner.status == request.status:
            return await _view(conn, partner_id)
        if request.status == "DISABLED":
            raise _unsupported("Disabling an organization")

        await conn.execute(
            text("UPDATE partner SET status = :status, updated_at = :now WHERE id = :id"),
            {"id": str(partner_id), "status": request.status, "now": datetime.now(UTC)},
        )
        await _audit(
            conn, actor, "ENABLE", AUDIT_PARTNER, partner_id, f"{partner.name} re-enabled"
        )
        return await _view(conn, partner_id)


# --------------------------------------------------------------------------- credentials


@router.post("/partners/{partner_id}/signature")
async def regenerate_signature(
    partner_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    signature = SignatureKeyMaterial.generate()
    async with engine().begin() as conn:
        partner = await _require(conn, partner_id)
        previous = partner.signature_fingerprint
        await conn.execute(
            text(
                "UPDATE partner SET signature_algorithm = :algorithm, signature_public_key = :public_key,"
                " signature_fingerprint = :fingerprint, signature_created_at = :now, updated_at = :now"
                " WHERE id = :id"
            ),
            {
                "id": str(partner_id),
                "algorithm": signature.algorithm,
                "public_key": signature.public_key_pem,
                "fingerprint": signature.fingerprint,
                "now": datetime.now(UTC),
            },
        )
        await _audit(
            conn, actor, "REGENERATE_SIGNATURE", AUDIT_PARTNER, partner_id,
            f"Signature key pair recreated for {partner.name}; {previous} replaced by "
            f"{signature.fingerprint}",
        )
        return {
            "partner": None,
            "privateKeyPem": signature.private_key_pem,
            "publicKeyPem": signature.public_key_pem,
            "ipvSalt": None,
            "notice": SHOWN_ONCE,
        }


@router.post("/partners/{partner_id}/ipv-salt")
async def rotate_ipv_salt(
    partner_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    salt = IpvSaltMaterial.generate()
    cipher = SecretCipher()
    async with engine().begin() as conn:
        partner = await _require(conn, partner_id)
        previous = partner.ipv_salt_masked
        await conn.execute(
            text(
                "UPDATE partner SET ipv_salt_cipher = :cipher, ipv_salt_masked = :masked,"
                " ipv_salt_created_at = :now, updated_at = :now WHERE id = :id"
            ),
            {
                "id": str(partner_id),
                "cipher": cipher.encrypt(salt.plaintext),
                "masked": salt.masked,
                "now": datetime.now(UTC),
            },
        )
        await _audit(
            conn, actor, "ROTATE_IPV_SALT", AUDIT_PARTNER, partner_id,
            f"IPV salt rotated for {partner.name}; {previous} replaced by {salt.masked}",
        )
        return {
            "partner": None,
            "privateKeyPem": None,
            "publicKeyPem": None,
            "ipvSalt": salt.plaintext,
            "notice": "Update the salt in the organization's configuration — the previous salt "
                      "stops working immediately.",
        }


@router.post("/partners/{partner_id}/ipv-salt/reveal")
async def reveal_ipv_salt(
    partner_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN"))
) -> dict[str, Any]:
    """Admin only, and audited: this returns a live secret in plain text."""
    async with engine().begin() as conn:
        partner = await _require(conn, partner_id)
        await _audit(
            conn, actor, "VIEW_IPV_SALT", AUDIT_PARTNER, partner_id,
            f"IPV salt of {partner.name} revealed",
        )
        created_at = (
            await conn.execute(
                text(
                    "SELECT to_char(ipv_salt_created_at AT TIME ZONE 'UTC',"
                    " 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') AS created_at"
                    " FROM partner WHERE id = :id"
                ),
                {"id": str(partner_id)},
            )
        ).one()
        return {
            "partnerId": str(partner_id),
            "ipvSalt": SecretCipher().decrypt(partner.ipv_salt_cipher),
            "createdAt": java_instant(created_at.created_at),
        }
