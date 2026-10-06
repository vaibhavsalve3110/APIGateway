"""Products: journeys made of dependent APIs (BRD CP-API-09).

A Product bundles the APIs needed for one business outcome, in the order they are called, with a note
per step and an optional dependency on an earlier step. It is assigned to an organization, or to
named users inside it, which is what makes it visible in the Developer Portal.

Visibility is not permission: what a partner may actually call is decided by their security key at
the gateway. Nothing here touches a gateway.

This is the first ported module that writes. Each handler runs inside one transaction so the audit
row commits with the change it describes, exactly as ``@Transactional`` does on the Java side.
"""

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import Principal, requires
from ..common import audit
from ..common.problem import ApiException
from ..common.time import instant_column, java_instant
from ..db import engine

router = APIRouter(prefix="/api/admin/products")

AUDIT_TYPE = "PRODUCT"


# --------------------------------------------------------------------------- request shapes


class StepRequest(BaseModel):
    apiId: uuid.UUID  # noqa: N815 - field names are the wire contract
    note: str | None = Field(default=None, max_length=500)
    dependsOnApiId: uuid.UUID | None = None  # noqa: N815


class ProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    journeyMarkdown: str | None = Field(default=None, max_length=100_000)  # noqa: N815
    steps: list[StepRequest] = Field(default_factory=list)


class AssignRequest(BaseModel):
    partnerId: uuid.UUID  # noqa: N815
    partnerUserId: uuid.UUID | None = None  # noqa: N815


# --------------------------------------------------------------------------- helpers


def _trim(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _slugify(name: str) -> str:
    """Slugs appear in Developer Portal URLs, so they stay lower-case, hyphenated and unique."""
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    base = re.sub(r"[^a-z0-9]+", "-", stripped.lower())
    base = re.sub(r"(^-+|-+$)", "", base)
    return base or "product"


async def _unique_slug(conn: AsyncConnection, name: str, keeping_id: uuid.UUID | None) -> str:
    base = _slugify(name)
    attempt = 1
    while True:
        candidate = base if attempt == 1 else f"{base}-{attempt}"
        row = (
            await conn.execute(text("SELECT id FROM product WHERE slug = :slug"), {"slug": candidate})
        ).first()
        if row is None or (keeping_id is not None and row.id == keeping_id):
            return candidate
        attempt += 1


async def _valid_steps(conn: AsyncConnection, requested: list[StepRequest]) -> list[StepRequest]:
    """Keep the author's order, drop repeated APIs, and check the dependencies make sense.

    An API must exist, may not depend on itself, and may only depend on another step of the same
    journey.
    """
    unique: list[StepRequest] = []
    seen: list[uuid.UUID] = []
    for step in requested:
        if step.apiId not in seen:
            seen.append(step.apiId)
            unique.append(step)

    if seen:
        known = {
            r.id
            for r in await conn.execute(
                text("SELECT id FROM api_definition WHERE id = ANY(:ids)"), {"ids": [str(s) for s in seen]}
            )
        }
        for api_id in seen:
            if api_id not in known:
                raise ApiException.not_found("API", api_id)

    for step in unique:
        if step.dependsOnApiId is None:
            continue
        if step.dependsOnApiId == step.apiId:
            raise ApiException.conflict("SELF_DEPENDENCY", "A step cannot depend on itself")
        if step.dependsOnApiId not in seen:
            raise ApiException.conflict(
                "DEPENDENCY_NOT_IN_PRODUCT", "A step can only depend on another API in the same product"
            )
    return unique


async def _replace_steps(conn: AsyncConnection, product_id: uuid.UUID, steps: list[StepRequest]) -> None:
    await conn.execute(text("DELETE FROM product_step WHERE product_id = :id"), {"id": str(product_id)})
    for position, step in enumerate(steps):
        await conn.execute(
            text(
                """
                INSERT INTO product_step (product_id, api_id, position, step_note, depends_on_api_id)
                VALUES (:product_id, :api_id, :position, :note, :depends_on)
                """
            ),
            {
                "product_id": str(product_id),
                "api_id": str(step.apiId),
                "position": position,
                "note": _trim(step.note),
                "depends_on": str(step.dependsOnApiId) if step.dependsOnApiId else None,
            },
        )


_PRODUCT_COLUMNS = f"""
    p.id, p.name, p.slug, p.summary, p.description, p.journey_markdown, p.status,
    {instant_column('p.created_at', 'created_at')}, p.created_by,
    {instant_column('p.updated_at', 'updated_at')},
    {instant_column('p.published_at', 'published_at')}
"""


async def _steps_of(conn: AsyncConnection, product_id: uuid.UUID, live_only: bool) -> list[dict[str, Any]]:
    """Steps are numbered as they are rendered, so skipping one does not leave a gap in the sequence."""
    rows = await conn.execute(
        text(
            """
            SELECT s.api_id, s.step_note, s.depends_on_api_id,
                   a.name AS api_name, a.category, a.http_method, a.proxy_path, a.status,
                   a.description AS api_description,
                   d.name AS depends_on_api_name
              FROM product_step s
              JOIN api_definition a ON a.id = s.api_id
              LEFT JOIN api_definition d ON d.id = s.depends_on_api_id
             WHERE s.product_id = :id
             ORDER BY s.position ASC
            """
        ),
        {"id": str(product_id)},
    )
    out: list[dict[str, Any]] = []
    number = 1
    for r in rows:
        # A disabled API is not something to send anyone to, so the partner view hides it.
        if live_only and r.status != "ACTIVE":
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


async def _assignments_of(conn: AsyncConnection, product_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await conn.execute(
        text(
            f"""
            SELECT a.id, a.partner_id, p.code AS partner_code, p.name AS partner_name,
                   a.partner_user_id, u.email AS partner_user_email, a.assigned_by,
                   {instant_column('a.assigned_at', 'assigned_at')}
              FROM product_assignment a
              LEFT JOIN partner p ON p.id = a.partner_id
              LEFT JOIN partner_user u ON u.id = a.partner_user_id
             WHERE a.product_id = :id
             ORDER BY p.name ASC NULLS LAST
            """
        ),
        {"id": str(product_id)},
    )
    return [
        {
            "id": str(r.id),
            "partnerId": str(r.partner_id),
            "partnerCode": r.partner_code,
            "partnerName": r.partner_name,
            "partnerUserId": str(r.partner_user_id) if r.partner_user_id else None,
            "partnerUserEmail": r.partner_user_email,
            "assignedBy": r.assigned_by,
            "assignedAt": java_instant(r.assigned_at),
        }
        for r in rows
    ]


async def _view(conn: AsyncConnection, product_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(f"SELECT {_PRODUCT_COLUMNS} FROM product p WHERE p.id = :id"), {"id": str(product_id)}
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Product", product_id)
    return {
        "id": str(row.id),
        "name": row.name,
        "slug": row.slug,
        "summary": row.summary,
        "description": row.description,
        "journeyMarkdown": row.journey_markdown,
        "status": row.status,
        "steps": await _steps_of(conn, product_id, live_only=False),
        "assignments": await _assignments_of(conn, product_id),
        "createdAt": java_instant(row.created_at),
        "createdBy": row.created_by,
        "updatedAt": java_instant(row.updated_at),
        "publishedAt": java_instant(row.published_at),
    }


async def _require(conn: AsyncConnection, product_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text("SELECT id, name, slug, status FROM product WHERE id = :id"), {"id": str(product_id)}
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Product", product_id)
    return row


# --------------------------------------------------------------------------- routes


@router.get("", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def list_products() -> list[dict[str, Any]]:
    async with engine().connect() as conn:
        ids = [
            r.id for r in await conn.execute(text("SELECT id FROM product ORDER BY name ASC"))
        ]
        return [await _view(conn, i) for i in ids]


@router.get("/{product_id}", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def get_product(product_id: uuid.UUID) -> dict[str, Any]:
    async with engine().connect() as conn:
        return await _view(conn, product_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(
    request: ProductRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        name = request.name.strip()
        steps = await _valid_steps(conn, request.steps)
        product_id = uuid.uuid4()
        now = datetime.now(UTC)
        await conn.execute(
            text(
                """
                INSERT INTO product (id, name, slug, summary, description, journey_markdown, status,
                                     created_at, created_by, updated_at)
                VALUES (:id, :name, :slug, :summary, :description, :journey, 'DRAFT', :now, :by, :now)
                """
            ),
            {
                "id": str(product_id),
                "name": name,
                "slug": await _unique_slug(conn, name, None),
                "summary": _trim(request.summary),
                "description": _trim(request.description),
                "journey": _trim(request.journeyMarkdown),
                "now": now,
                "by": actor.username,
            },
        )
        await _replace_steps(conn, product_id, steps)
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="CREATE",
            object_type=AUDIT_TYPE,
            object_id=str(product_id),
            detail=f"Product {name} created as a draft journey of {len(steps)} step(s)",
        )
        return await _view(conn, product_id)


@router.put("/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    request: ProductRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        existing = await _require(conn, product_id)
        name = request.name.strip()
        steps = await _valid_steps(conn, request.steps)
        # The slug only moves when the name really changes: a URL partners have bookmarked should not
        # break because someone fixed the capitalisation.
        slug = existing.slug if name.lower() == existing.name.lower() else await _unique_slug(
            conn, name, product_id
        )
        await conn.execute(
            text(
                """
                UPDATE product
                   SET name = :name, slug = :slug, summary = :summary, description = :description,
                       journey_markdown = :journey, updated_at = :now
                 WHERE id = :id
                """
            ),
            {
                "id": str(product_id),
                "name": name,
                "slug": slug,
                "summary": _trim(request.summary),
                "description": _trim(request.description),
                "journey": _trim(request.journeyMarkdown),
                "now": datetime.now(UTC),
            },
        )
        await _replace_steps(conn, product_id, steps)
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="UPDATE",
            object_type=AUDIT_TYPE,
            object_id=str(product_id),
            detail=f"Product {name} updated; {len(steps)} step(s)",
        )
        return await _view(conn, product_id)


async def _set_published(product_id: uuid.UUID, publish: bool, actor: Principal) -> dict[str, Any]:
    async with engine().begin() as conn:
        product = await _require(conn, product_id)
        now = datetime.now(UTC)
        if publish:
            steps = (
                await conn.execute(
                    text("SELECT COUNT(*) AS n FROM product_step WHERE product_id = :id"),
                    {"id": str(product_id)},
                )
            ).one()
            # A journey with no steps is nothing to publish.
            if int(steps.n) == 0:
                raise ApiException.conflict(
                    "PRODUCT_EMPTY", f"Add at least one API before publishing {product.name}"
                )
            await conn.execute(
                text(
                    "UPDATE product SET status = 'PUBLISHED', published_at = :now, updated_at = :now"
                    " WHERE id = :id"
                ),
                {"id": str(product_id), "now": now},
            )
        else:
            # published_at is deliberately left in place: it records when it was last published.
            await conn.execute(
                text("UPDATE product SET status = 'DRAFT', updated_at = :now WHERE id = :id"),
                {"id": str(product_id), "now": now},
            )
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="PUBLISH" if publish else "UNPUBLISH",
            object_type=AUDIT_TYPE,
            object_id=str(product_id),
            detail=f"Product {product.name}"
            + (" published to assigned partners" if publish else " withdrawn to draft"),
        )
        return await _view(conn, product_id)


@router.post("/{product_id}/publish")
async def publish_product(
    product_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    return await _set_published(product_id, True, actor)


@router.post("/{product_id}/unpublish")
async def unpublish_product(
    product_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    return await _set_published(product_id, False, actor)


@router.post("/{product_id}/assignments")
async def assign_product(
    product_id: uuid.UUID,
    request: AssignRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    """CP-API-09: give an organization — or one named user inside it — sight of this journey."""
    async with engine().begin() as conn:
        product = await _require(conn, product_id)
        partner = (
            await conn.execute(
                text("SELECT id, name FROM partner WHERE id = :id"), {"id": str(request.partnerId)}
            )
        ).first()
        if partner is None:
            raise ApiException.not_found("Partner", request.partnerId)

        user = None
        if request.partnerUserId is not None:
            user = (
                await conn.execute(
                    text("SELECT id, email, partner_id FROM partner_user WHERE id = :id"),
                    {"id": str(request.partnerUserId)},
                )
            ).first()
            if user is None:
                raise ApiException.not_found("Partner user", request.partnerUserId)
            if user.partner_id != partner.id:
                raise ApiException.conflict(
                    "USER_NOT_IN_ORGANIZATION", f"{user.email} does not belong to {partner.name}"
                )
            clash = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM product_assignment"
                        " WHERE product_id = :p AND partner_user_id = :u"
                    ),
                    {"p": str(product_id), "u": str(user.id)},
                )
            ).first()
            if clash is not None:
                raise ApiException.conflict(
                    "ALREADY_ASSIGNED", f"{product.name} is already assigned to {user.email}"
                )
        else:
            clash = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM product_assignment"
                        " WHERE product_id = :p AND partner_id = :pa AND partner_user_id IS NULL"
                    ),
                    {"p": str(product_id), "pa": str(partner.id)},
                )
            ).first()
            if clash is not None:
                raise ApiException.conflict(
                    "ALREADY_ASSIGNED", f"{product.name} is already assigned to {partner.name}"
                )

        await conn.execute(
            text(
                """
                INSERT INTO product_assignment
                    (id, product_id, partner_id, partner_user_id, assigned_by, assigned_at)
                VALUES (:id, :product_id, :partner_id, :user_id, :by, :now)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "product_id": str(product_id),
                "partner_id": str(partner.id),
                "user_id": str(user.id) if user else None,
                "by": actor.username,
                "now": datetime.now(UTC),
            },
        )
        who = f"{partner.name} (whole organization)" if user is None else f"{user.email} at {partner.name}"
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="ASSIGN",
            object_type=AUDIT_TYPE,
            object_id=str(product_id),
            detail=f"Product {product.name} assigned to {who}",
        )
        return await _view(conn, product_id)


@router.delete("/{product_id}/assignments/{assignment_id}")
async def unassign_product(
    product_id: uuid.UUID,
    assignment_id: uuid.UUID,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    async with engine().begin() as conn:
        product = await _require(conn, product_id)
        assignment = (
            await conn.execute(
                text(
                    """
                    SELECT a.id, p.name AS partner_name, u.email AS user_email
                      FROM product_assignment a
                      LEFT JOIN partner p ON p.id = a.partner_id
                      LEFT JOIN partner_user u ON u.id = a.partner_user_id
                     WHERE a.id = :id AND a.product_id = :product_id
                    """
                ),
                {"id": str(assignment_id), "product_id": str(product_id)},
            )
        ).first()
        if assignment is None:
            raise ApiException.not_found("Assignment", assignment_id)

        who = assignment.user_email or assignment.partner_name or "an organization"
        await conn.execute(
            text("DELETE FROM product_assignment WHERE id = :id"), {"id": str(assignment_id)}
        )
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="UNASSIGN",
            object_type=AUDIT_TYPE,
            object_id=str(product_id),
            detail=f"Product {product.name} withdrawn from {who}",
        )
        return await _view(conn, product_id)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> Response:
    async with engine().begin() as conn:
        product = await _require(conn, product_id)
        if product.status == "PUBLISHED":
            raise ApiException.conflict(
                "PRODUCT_PUBLISHED",
                f"Withdraw {product.name} from the Developer Portal before deleting it",
            )
        # product_step and product_assignment cascade on the foreign key, but the assignments are
        # removed explicitly so the behaviour does not depend on the schema's ON DELETE clause.
        await conn.execute(
            text("DELETE FROM product_assignment WHERE product_id = :id"), {"id": str(product_id)}
        )
        await conn.execute(text("DELETE FROM product WHERE id = :id"), {"id": str(product_id)})
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="DELETE",
            object_type=AUDIT_TYPE,
            object_id=str(product_id),
            detail=f"Product {product.name} deleted",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
