"""Usage ingest — the batches the APISIX gateways post from their http-logger plugin.

This is the only write path the gateways themselves use, and the only endpoint not authenticated by a
session token: the gateways present a shared ingest token instead.

Two behaviours are load-bearing and easy to lose in a port:

* an entry that cannot be parsed is **skipped, not rejected**. The gateways retry a failed batch, so
  failing the whole request over one malformed row would stall every other row behind it forever.
* the response reports how many were accepted, which is what makes a silent parse failure visible.
"""

import hmac
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, Request
from sqlalchemy import text

from ..common.problem import ApiException
from ..db import engine
from ..settings import get_settings

router = APIRouter()
log = logging.getLogger(__name__)

#: Route ids the gateway sends back, as ApisixConfigFactory writes them: api-<uuid>-sbx | -prd.
ROUTE_ID = re.compile(r"^api-([0-9a-f\-]{36})-(sbx|prd)$")

ENVIRONMENTS = {"SANDBOX", "PRODUCTION"}


def _str(value: Any) -> str | None:
    """Java's String.valueOf: anything non-null becomes its string form, including numbers."""
    return None if value is None else str(value)


def _num(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        # bool is an int in Python but not a number the gateway would send; treat it as absent.
        return fallback
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip() and value != "-":
        # Deliberately not guarded: Java's Double.parseDouble throws here, which skips the whole
        # entry. Returning the fallback instead would silently store a status of 0 and a latency of
        # 0 for a row the Java service discards, so the two would disagree about what was recorded.
        return float(value)
    return fallback


def _parse_env(value: str | None) -> str | None:
    if value is None:
        return None
    upper = value.upper()
    return upper if upper in ENVIRONMENTS else None


def _to_event(entry: dict[str, Any]) -> dict[str, Any]:
    """One http-logger row to one usage_event. Raises for anything unusable; the caller skips it."""
    route_id = _str(entry.get("route_id"))
    api_id: str | None = None
    environment = _parse_env(_str(entry.get("env")))

    if route_id:
        match = ROUTE_ID.match(route_id)
        if match:
            # Validates the uuid as Java's UUID.fromString does, so a malformed id skips the row.
            api_id = str(uuid.UUID(match.group(1)))
            environment = "PRODUCTION" if match.group(2) == "prd" else "SANDBOX"

    seconds = _num(entry.get("request_time"), 0)
    msec = _num(entry.get("msec"), datetime.now(UTC).timestamp())
    client = _str(entry.get("client_id"))

    return {
        # msec is the gateway's own clock in fractional seconds; Java rounds to whole milliseconds.
        "occurred_at": datetime.fromtimestamp(round(msec * 1000) / 1000, tz=UTC),
        "api_id": api_id,
        "environment": environment,
        "client_id": client if client and client.strip() else None,
        "status_code": int(_num(entry.get("status"), 0)),
        "latency_ms": round(seconds * 1000),
    }


@router.post("/internal/usage/batch")
async def ingest(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, int]:
    expected = f"Ingest {get_settings().usage_ingest_token}"
    # Constant-time, as MessageDigest.isEqual is on the Java side: a token must not be guessable
    # one character at a time from response timing.
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise ApiException(401, "BAD_INGEST_TOKEN", "Invalid ingest token")

    entries = await request.json()
    if not isinstance(entries, list):
        raise ApiException(400, "BAD_REQUEST", "Expected a JSON array of usage entries")

    events: list[dict[str, Any]] = []
    for entry in entries:
        try:
            if not isinstance(entry, dict):
                raise TypeError("entry is not an object")
            events.append(_to_event(entry))
        except Exception as exc:  # noqa: BLE001 - one bad row must not fail the batch
            # A deliberate divergence from backend-java, which deserialises the body as a list of
            # objects and fails the whole batch with a 500 when an element is not one. APISIX never
            # sends that, but if it ever did, failing the batch would stall every good row behind it
            # through the gateway's retries. Skipping is strictly safer and is reported in the count.
            log.debug("Skipping unparseable usage entry %s: %s", entry, exc)

    if events:
        async with engine().begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO usage_event (occurred_at, api_id, environment, client_id,
                                             status_code, latency_ms)
                    VALUES (:occurred_at, CAST(:api_id AS uuid), :environment, :client_id,
                            :status_code, :latency_ms)
                    """
                ),
                events,
            )
    return {"accepted": len(events)}
