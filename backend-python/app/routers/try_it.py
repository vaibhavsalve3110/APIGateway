"""Try it live (BRD DP-03) — a partner calling their own API from the Developer Portal.

**Sandbox only, always.** The service holds the sandbox gateway's address and nothing else, and the
key the partner pastes must be one of their own live sandbox keys. A production key is refused
rather than used, so there is no path from this screen to production traffic.

Two modes, decided by `TRY_IT_MODE`:

* `GATEWAY` — the call really goes to the sandbox gateway, through the same route a partner's own
  system would use. What comes back is what the gateway said.
* `SIMULATE` — answered from the API's own documentation, for an environment with no gateway
  running. The required-parameter check still runs, so a missing parameter gives the documented 400
  rather than a success the real gateway would never have returned.

Ported from backend-java's `TryItService`, whose behaviour `TryItTest` pins; the wording of each
refusal is kept identical, because the portal shows these messages to partners verbatim.
"""

import asyncio
import random
import re
import time
import urllib.parse
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..auth import Principal, requires
from ..common.problem import ApiException
from ..db import connection
from ..gateway import KEY_HEADER
from ..settings import get_settings
from .catalogue import normalise_documentation
from .keys import sha256_hex

router = APIRouter(tags=["partner-portal"])

_PATH_PARAM = re.compile(r"\{([A-Za-z0-9_\-.]+)\}")

#: 256 KB. A partner's own backend could return anything; the portal has to render it.
MAX_BODY = 256 * 1024

#: Headers a partner may not set. The gateway address and the key header are the platform's to
#: decide, and the rest are connection-level headers that are not a caller's to forge.
BLOCKED_HEADERS = frozenset({
    "host", "content-length", "connection", "transfer-encoding", "upgrade", "expect", "te",
    "trailer", "keep-alive", "proxy-authorization", KEY_HEADER.lower(),
})

#: Hop-by-hop headers are about one connection, so they are meaningless to show for another.
HOP_BY_HOP = frozenset({"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade"})


class TryItRequest(BaseModel):
    apiKey: str = Field(min_length=1, max_length=200)  # noqa: N815 - field names are the contract
    pathParams: dict[str, str] | None = None  # noqa: N815
    query: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    body: str | None = Field(default=None, max_length=100_000)


def fill_path(proxy_path: str, params: dict[str, str]) -> str:
    """Replace `{param}` segments, encoding each value as a single path segment.

    Encoded with `quote` and no safe characters, so a value containing a slash becomes one segment
    rather than silently reaching a different route than the one documented.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = (params or {}).get(name)
        if value is None or not value.strip():
            raise ApiException.bad_request(
                "MISSING_PATH_PARAMETER", f"Enter a value for the path parameter '{name}'"
            )
        return urllib.parse.quote(value.strip(), safe="")

    return _PATH_PARAM.sub(replace, proxy_path)


async def _assert_usable_sandbox_key(conn: AsyncConnection, partner_id: Any, plaintext: str) -> None:
    """The key must be this partner's own, sandbox, and live. Same wording as backend-java."""
    row = (
        await conn.execute(
            text(
                "SELECT partner_id, environment, status FROM security_key WHERE key_hash = :hash"
            ),
            {"hash": sha256_hex(plaintext.strip())},
        )
    ).first()
    if row is None or str(row.partner_id) != str(partner_id):
        raise ApiException(
            401, "INVALID_KEY",
            "This key is not valid for your account. Paste the Sandbox key you stored when you "
            "created it.",
        )
    if row.environment != "SANDBOX":
        raise ApiException(
            403, "SANDBOX_ONLY",
            "Production keys cannot be used from the portal — use a Sandbox key. Test calls only "
            "reach the Sandbox.",
        )
    if row.status not in ("ACTIVE", "EXPIRING"):
        raise ApiException(
            401, "KEY_NOT_ACTIVE",
            f"This key is {row.status.lower()}. Use your current Sandbox key.",
        )


def _shown_url(base: str, path: str, query: dict[str, str] | None) -> str:
    """The URL a partner would call from their own system, which is what the screen displays."""
    url = base.rstrip("/") + path
    pairs = [
        (k.strip(), v)
        for k, v in (query or {}).items()
        if k and k.strip() and v is not None and v.strip()
    ]
    if pairs:
        url += "?" + urllib.parse.urlencode(pairs)
    return url


def _simulate(documentation: dict[str, Any], request: TryItRequest, shown_url: str) -> dict[str, Any]:
    """Answer from the documentation, applying the required-parameter check the gateway would."""
    latency = random.randint(35, 179)  # noqa: S311 - a plausible-looking number, not a secret
    note = (
        "Simulated from the API documentation — the Sandbox gateway is not connected in this "
        "environment."
    )
    for parameter in documentation.get("queryParameters") or []:
        if not parameter.get("required"):
            continue
        value = (request.query or {}).get(parameter.get("name", ""))
        if value is None or not value.strip():
            documented = next(
                (r for r in documentation.get("responses") or [] if r.get("statusCode") == 400), None
            )
            body = (documented or {}).get("bodyExample") or (
                '{\n  "code": "MISSING_PARAMETER",\n  "detail": "Query parameter '
                f"'{parameter.get('name')}' is required\"\n}}"
            )
            return {
                "status": 400, "latencyMs": latency,
                "headers": {"Content-Type": "application/json"},
                "body": body, "simulated": True, "requestUrl": shown_url, "note": note,
            }

    headers = {"Content-Type": "application/json"}
    for header in documentation.get("responseHeaders") or []:
        headers[header.get("name", "")] = header.get("example") or ""

    success = next(
        (r for r in documentation.get("responses") or [] if 200 <= (r.get("statusCode") or 0) < 300),
        None,
    )
    if success is None:
        return {
            "status": 200, "latencyMs": latency, "headers": headers, "body": "{}",
            "simulated": True, "requestUrl": shown_url,
            "note": note + " No success response is documented for this API yet.",
        }
    return {
        "status": success.get("statusCode"), "latencyMs": latency, "headers": headers,
        "body": success.get("bodyExample") or "", "simulated": True, "requestUrl": shown_url,
        "note": note,
    }


async def _via_gateway(
    api: Any, request: TryItRequest, path: str, shown_url: str
) -> dict[str, Any]:
    settings = get_settings()
    target = settings.try_it_sandbox_url.rstrip("/") + path
    pairs = [
        (k.strip(), v)
        for k, v in (request.query or {}).items()
        if k and k.strip() and v is not None and v.strip()
    ]

    headers: dict[str, str] = {}
    hosts = settings.gateway_sandbox_hosts
    if hosts:
        # The gateway routes by Host, and this call reaches it by container name or IP.
        headers["Host"] = hosts[0]
    headers[KEY_HEADER] = request.apiKey.strip()

    content_type_set = False
    for name, value in (request.headers or {}).items():
        clean = (name or "").strip()
        if not clean or value is None or clean.lower() in BLOCKED_HEADERS:
            continue
        content_type_set = content_type_set or clean.lower() == "content-type"
        headers[clean] = value

    has_body = bool(request.body and request.body.strip())
    if has_body and not content_type_set:
        headers["Content-Type"] = "application/json"

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.try_it_timeout_seconds,
                                     follow_redirects=False) as client:
            response = await client.request(
                api.http_method,
                target,
                params=pairs or None,
                headers=headers,
                content=request.body.encode() if has_body and api.http_method != "GET" else None,
            )
    except httpx.HTTPError as exc:
        raise ApiException(
            502, "SANDBOX_UNREACHABLE",
            f"The Sandbox gateway did not answer ({type(exc).__name__}). Try again shortly.",
        ) from exc

    latency = int((time.monotonic() - started) * 1000)
    out_headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in HOP_BY_HOP and value
    }
    raw = response.content
    truncated = len(raw) > MAX_BODY
    return {
        "status": response.status_code,
        "latencyMs": latency,
        "headers": out_headers,
        "body": raw[:MAX_BODY].decode("utf-8", errors="replace"),
        "simulated": False,
        "requestUrl": shown_url,
        "note": "Response truncated to 256 KB." if truncated else None,
    }


@router.post("/api/partner/apis/{api_id}/try")
async def try_it(
    api_id: uuid.UUID,
    request: TryItRequest,
    principal: Principal = Depends(requires("PARTNER")),
    conn: AsyncConnection = Depends(connection),
) -> dict[str, Any]:
    """Call this API in the sandbox, as the partner's own system would.

    The API has to be live and the key has to be one of this organization's own sandbox keys. A
    draft or withdrawn API is a 404 here, the same answer the catalogue gives, so this screen never
    reveals an API the partner cannot otherwise see.
    """
    partner = (
        await conn.execute(
            text("SELECT id FROM partner WHERE code = :code"), {"code": principal.partner_code}
        )
    ).first()
    if partner is None:
        raise ApiException(403, "NO_ORGANIZATION", "Your account is not linked to an organization")

    api = (
        await conn.execute(
            text(
                "SELECT id, name, status, http_method, proxy_path, documentation"
                "  FROM api_definition WHERE id = :id"
            ),
            {"id": str(api_id)},
        )
    ).first()
    if api is None or api.status != "ACTIVE":
        raise ApiException.not_found("API", api_id)

    await _assert_usable_sandbox_key(conn, partner.id, request.apiKey)

    path = fill_path(api.proxy_path, request.pathParams or {})
    settings = get_settings()
    shown_url = _shown_url(settings.public_sandbox_url, path, request.query)

    if settings.try_it_mode.upper() == "SIMULATE":
        documentation = normalise_documentation(
            api.documentation if isinstance(api.documentation, dict) else None
        )
        # Simulated, so nothing leaves this process — but the shape of the answer is the same.
        await asyncio.sleep(0)
        return _simulate(documentation, request, shown_url)

    return await _via_gateway(api, request, path, shown_url)
