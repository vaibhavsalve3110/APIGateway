"""Developer Portal pages (BRD CP-API-10): write and edit here, publish when ready.

Editing never changes what partners see. Each save adds a version; publishing points the live page at
one. That means a half-written FAQ cannot appear on the portal by accident, and there is a record of
what was published and by whom.
"""

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
from .products import _slugify

router = APIRouter(prefix="/api/admin/pages")

AUDIT_TYPE = "PORTAL_PAGE"


class PageRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=60)
    bodyMarkdown: str | None = Field(default=None, max_length=100_000)  # noqa: N815
    position: int | None = None


async def _unique_slug(conn: AsyncConnection, title: str, keeping_id: uuid.UUID | None) -> str:
    base = _slugify(title) or "page"
    attempt = 1
    while True:
        candidate = base if attempt == 1 else f"{base}-{attempt}"
        row = (
            await conn.execute(text("SELECT id FROM portal_page WHERE slug = :slug"), {"slug": candidate})
        ).first()
        if row is None or (keeping_id is not None and row.id == keeping_id):
            return candidate
        attempt += 1


async def _require(conn: AsyncConnection, page_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text(
                "SELECT id, slug, title, category, status, position, published_version"
                "  FROM portal_page WHERE id = :id"
            ),
            {"id": str(page_id)},
        )
    ).first()
    if row is None:
        raise ApiException.not_found("Page", page_id)
    return row


async def _latest_version(conn: AsyncConnection, page_id: uuid.UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT id, version, body_markdown FROM portal_page_version"
                " WHERE page_id = :id ORDER BY version DESC LIMIT 1"
            ),
            {"id": str(page_id)},
        )
    ).first()


async def _save_version(conn: AsyncConnection, page_id: uuid.UUID, body: str, actor: Principal) -> None:
    latest = await _latest_version(conn, page_id)
    await conn.execute(
        text(
            """
            INSERT INTO portal_page_version (id, page_id, version, body_markdown, edited_by, edited_at)
            VALUES (:id, :page_id, :version, :body, :by, :now)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "page_id": str(page_id),
            "version": (latest.version + 1) if latest else 1,
            "body": body,
            "by": actor.username,
            "now": datetime.now(UTC),
        },
    )


async def _view(conn: AsyncConnection, page_id: uuid.UUID) -> dict[str, Any]:
    page = (
        await conn.execute(
            text(
                f"""
                SELECT id, slug, title, category, status, position, published_version,
                       {instant_column('created_at', 'created_at')}, created_by,
                       {instant_column('updated_at', 'updated_at')},
                       {instant_column('published_at', 'published_at')}
                  FROM portal_page WHERE id = :id
                """
            ),
            {"id": str(page_id)},
        )
    ).first()
    if page is None:
        raise ApiException.not_found("Page", page_id)

    history = list(
        await conn.execute(
            text(
                f"""
                SELECT id, version, body_markdown, edited_by,
                       {instant_column('edited_at', 'edited_at')}
                  FROM portal_page_version
                 WHERE page_id = :id
                 ORDER BY version DESC
                """
            ),
            {"id": str(page_id)},
        )
    )
    latest = history[0] if history else None
    # The flag the editor needs: published, but the newest draft is not the live one.
    unpublished_changes = (
        page.status == "PUBLISHED" and latest is not None and latest.id != page.published_version
    )
    return {
        "id": str(page.id),
        "slug": page.slug,
        "title": page.title,
        "category": page.category,
        "status": page.status,
        "position": page.position,
        "bodyMarkdown": latest.body_markdown if latest else "",
        "unpublishedChanges": unpublished_changes,
        "createdAt": java_instant(page.created_at),
        "createdBy": page.created_by,
        "updatedAt": java_instant(page.updated_at),
        "publishedAt": java_instant(page.published_at),
        "versions": [
            {
                "id": str(v.id),
                "version": v.version,
                "editedBy": v.edited_by,
                "editedAt": java_instant(v.edited_at),
                "live": v.id == page.published_version,
            }
            for v in history
        ],
    }


@router.get("", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def list_pages() -> list[dict[str, Any]]:
    async with engine().connect() as conn:
        ids = [
            r.id
            for r in await conn.execute(
                text("SELECT id FROM portal_page ORDER BY category ASC, position ASC, title ASC")
            )
        ]
        return [await _view(conn, i) for i in ids]


@router.get("/{page_id}", dependencies=[Depends(requires("ADMIN", "EDITOR", "VIEWER"))])
async def get_page(page_id: uuid.UUID) -> dict[str, Any]:
    async with engine().connect() as conn:
        return await _view(conn, page_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_page(
    request: PageRequest, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    async with engine().begin() as conn:
        title = request.title.strip()
        page_id = uuid.uuid4()
        now = datetime.now(UTC)
        await conn.execute(
            text(
                """
                INSERT INTO portal_page (id, slug, title, category, status, position,
                                         created_at, created_by, updated_at)
                VALUES (:id, :slug, :title, :category, 'DRAFT', :position, :now, :by, :now)
                """
            ),
            {
                "id": str(page_id),
                "slug": await _unique_slug(conn, title, None),
                "title": title,
                "category": request.category.strip(),
                "position": request.position if request.position is not None else 0,
                "now": now,
                "by": actor.username,
            },
        )
        await _save_version(conn, page_id, request.bodyMarkdown or "", actor)
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="CREATE",
            object_type=AUDIT_TYPE,
            object_id=str(page_id),
            detail=f"Portal page {title} created as a draft",
        )
        return await _view(conn, page_id)


@router.put("/{page_id}")
async def update_page(
    page_id: uuid.UUID,
    request: PageRequest,
    actor: Principal = Depends(requires("ADMIN", "EDITOR")),
) -> dict[str, Any]:
    """Saves the text as a new version and updates the page's details; the live page is untouched."""
    async with engine().begin() as conn:
        page = await _require(conn, page_id)
        title = request.title.strip()
        slug = page.slug if title.lower() == page.title.lower() else await _unique_slug(conn, title, page_id)
        await conn.execute(
            text(
                """
                UPDATE portal_page
                   SET slug = :slug, title = :title, category = :category, position = :position,
                       updated_at = :now
                 WHERE id = :id
                """
            ),
            {
                "id": str(page_id),
                "slug": slug,
                "title": title,
                "category": request.category.strip(),
                "position": request.position if request.position is not None else page.position,
                "now": datetime.now(UTC),
            },
        )

        body = request.bodyMarkdown or ""
        latest = await _latest_version(conn, page_id)
        # Saving the same text again would otherwise fill the history with identical versions.
        text_changed = latest is None or latest.body_markdown != body
        if text_changed:
            await _save_version(conn, page_id, body, actor)
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="UPDATE",
            object_type=AUDIT_TYPE,
            object_id=str(page_id),
            detail=f"Portal page {title} edited"
            + (" (new version saved)" if text_changed else " (details only)"),
        )
        return await _view(conn, page_id)


@router.post("/{page_id}/publish")
async def publish_page(
    page_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    """CP-API-10: makes the latest saved text the one partners see."""
    async with engine().begin() as conn:
        page = await _require(conn, page_id)
        latest = await _latest_version(conn, page_id)
        if latest is None or not latest.body_markdown.strip():
            raise ApiException.conflict("PAGE_EMPTY", "Write something before publishing this page")
        now = datetime.now(UTC)
        await conn.execute(
            text(
                "UPDATE portal_page SET published_version = :version, status = 'PUBLISHED',"
                " published_at = :now, updated_at = :now WHERE id = :id"
            ),
            {"id": str(page_id), "version": str(latest.id), "now": now},
        )
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="PUBLISH",
            object_type=AUDIT_TYPE,
            object_id=str(page_id),
            detail=f"Portal page {page.title} published (version {latest.version})",
        )
        return await _view(conn, page_id)


@router.post("/{page_id}/unpublish")
async def unpublish_page(
    page_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> dict[str, Any]:
    async with engine().begin() as conn:
        page = await _require(conn, page_id)
        await conn.execute(
            text(
                "UPDATE portal_page SET status = 'DRAFT', published_version = NULL, updated_at = :now"
                " WHERE id = :id"
            ),
            {"id": str(page_id), "now": datetime.now(UTC)},
        )
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="UNPUBLISH",
            object_type=AUDIT_TYPE,
            object_id=str(page_id),
            detail=f"Portal page {page.title} withdrawn from the Developer Portal",
        )
        return await _view(conn, page_id)


@router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(
    page_id: uuid.UUID, actor: Principal = Depends(requires("ADMIN", "EDITOR"))
) -> Response:
    async with engine().begin() as conn:
        page = await _require(conn, page_id)
        if page.status == "PUBLISHED":
            raise ApiException.conflict(
                "PAGE_PUBLISHED",
                f"Withdraw {page.title} from the Developer Portal before deleting it",
            )
        # portal_page_version cascades on the foreign key.
        await conn.execute(text("DELETE FROM portal_page WHERE id = :id"), {"id": str(page_id)})
        await audit.record(
            conn,
            actor=actor.username,
            actor_role=actor.roles[0] if actor.roles else None,
            action="DELETE",
            object_type=AUDIT_TYPE,
            object_id=str(page_id),
            detail=f"Portal page {page.title} deleted",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

