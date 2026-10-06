"""The audit trail — appends to the same ``audit_event`` table backend-java writes.

The Management Portal's audit view must not be able to tell which service performed an action, so
the column widths and trimming match the Java side exactly.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_MAX = {"actor": 120, "actor_role": 30, "action": 40, "object_type": 40, "object_id": 80, "detail": 1000}

_INSERT = text(
    """
    INSERT INTO audit_event (occurred_at, actor, actor_role, action, object_type, object_id, detail)
    VALUES (now(), :actor, :actor_role, :action, :object_type, :object_id, :detail)
    """
)


def _trim(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 3] + "..."


async def record(
    conn: AsyncConnection,
    *,
    actor: str,
    action: str,
    object_type: str,
    actor_role: str | None = None,
    object_id: str | None = None,
    detail: str | None = None,
) -> None:
    """Write an audit row on the caller's connection, so it commits with the change it describes."""
    await conn.execute(
        _INSERT,
        {
            "actor": _trim(actor, _MAX["actor"]),
            "actor_role": _trim(actor_role, _MAX["actor_role"]),
            "action": _trim(action, _MAX["action"]),
            "object_type": _trim(object_type, _MAX["object_type"]),
            "object_id": _trim(object_id, _MAX["object_id"]),
            "detail": _trim(detail, _MAX["detail"]),
        },
    )
