"""The error log — the same ``error_event`` table backend-java writes, with the same references."""

import logging
import uuid

from sqlalchemy import text

from ..db import engine

log = logging.getLogger(__name__)

SMTP = "SMTP"
GATEWAY = "GATEWAY"
SCHEDULER = "SCHEDULER"
API = "API"

# Column widths from V6__error_event.sql. Writing past them fails the insert, which would lose the
# very error being recorded.
_MAX = {"source": 40, "code": 60, "message": 1000, "detail": 8000, "actor": 120, "request": 300, "ip": 60}

_INSERT = text(
    """
    INSERT INTO error_event (occurred_at, source, code, message, detail, actor, request, client_ip, reference)
    VALUES (now(), :source, :code, :message, :detail, :actor, :request, :client_ip, :reference)
    """
)


def _trim(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 3] + "..."


async def record(
    source: str,
    code: str,
    message: str,
    detail: str | None = None,
    actor: str | None = None,
    request: str | None = None,
    client_ip: str | None = None,
) -> str | None:
    """Record a failure and return the reference shown to the caller, or None if it could not be stored.

    Recording must never raise: an error log that takes the request down with it is worse than no
    error log at all.
    """
    reference = f"ERR-{uuid.uuid4().hex[:8].upper()}"
    try:
        async with engine().begin() as conn:
            await conn.execute(
                _INSERT,
                {
                    "source": _trim(source, _MAX["source"]),
                    "code": _trim(code, _MAX["code"]),
                    "message": _trim(message, _MAX["message"]),
                    "detail": _trim(detail, _MAX["detail"]),
                    "actor": _trim(actor, _MAX["actor"]),
                    "request": _trim(request, _MAX["request"]),
                    "client_ip": _trim(client_ip, _MAX["ip"]),
                    "reference": reference,
                },
            )
        return reference
    except Exception as exc:  # noqa: BLE001 - deliberately swallowed, see docstring
        log.error("Could not record error %s: %s", reference, exc)
        return None
