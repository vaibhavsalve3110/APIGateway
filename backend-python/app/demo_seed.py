"""Demo data: the partners, APIs and traffic the screen designs show.

Runs **only outside production, and only into an empty database**. Both guards matter. The profile
check is the one people think of; the empty check is the one that saves you, because a profile is a
string somebody can get wrong and an existing row is a fact.

Partner codes are deterministic — Acme is always PTN-00001 — because the designs and the Keycloak
demo realm both refer to them by code.

This is a port of backend-java's `DemoDataSeeder`. It writes the same shapes rather than the same
bytes: nothing asserts the content of demo data, so the fixtures here are authored to match the
designs rather than transcribed line by line. What is kept exactly is the ordering, because the
codes depend on it.

Traffic is synthetic and relative to now, so a freshly seeded environment always shows a populated
dashboard rather than a flat line from whenever the fixture was written.
"""

import json
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .db import engine
from .settings import get_settings

log = logging.getLogger(__name__)

GROUPS = [
    ("Tier-1 Aggregators", "Large payment aggregators"),
    ("Tier-2 Partners", "Regional fintech partners"),
    ("Broking Partners", "Stock-broking integrations"),
    ("Internal Consumers", "In-house channels using the gateway"),
]

#: (name, group, contact, sandbox client id). Order fixes the codes: the first is PTN-00001.
PARTNERS = [
    ("Acme Fintech Pvt Ltd", "Tier-1 Aggregators", "integrations@acmefintech.in", "acme-fintech-sbx"),
    ("Kavery Payments", "Tier-2 Partners", "tech@kaverypay.in", "kavery-payments-sbx"),
    ("Northstar Capital", "Tier-1 Aggregators", "api@northstar.in", "northstar-capital-sbx"),
    ("Meridian Broking", "Broking Partners", "dev@meridianbroking.in", "meridian-broking-sbx"),
]

PLATFORM_USERS = [
    ("vaibhav.admin@apigw.local", "Vaibhav Salve", "ADMIN"),
    # A second administrator on purpose: approving a change needs one other than the requester, so
    # a demo with a single admin could not publish anything at all.
    ("priya.admin@apigw.local", "Priya Nair", "ADMIN"),
    ("ravi.developer@apigw.local", "Ravi Kumar", "DEVELOPER"),
]

#: (name, category, method, path, backend, status, rate limit, description)
APIS = [
    ("Account Balance Enquiry", "Accounts", "GET", "/v1/accounts/balance",
     "http://mock-sandbox:8080/core/balance", "ACTIVE", 120,
     "Current and available balance for an account linked to the partner."),
    ("Statement Download", "Accounts", "GET", "/v1/accounts/statement",
     "http://mock-sandbox:8080/core/statement", "ACTIVE", 60,
     "Transaction statement for a period, up to 90 days."),
    ("Fund Transfer — IMPS", "Payments", "POST", "/v1/payments/imps",
     "http://mock-sandbox:8080/core/imps", "ACTIVE", 300,
     "Initiates an immediate IMPS credit to a beneficiary registered under the partner's own account."),
    ("Fund Transfer — NEFT", "Payments", "POST", "/v1/payments/neft",
     "http://mock-sandbox:8080/core/neft", "ACTIVE", 300,
     "Queues an NEFT credit for the next settlement batch."),
    ("Mandate Registration", "Payments", "POST", "/v1/mandates/register",
     "http://mock-sandbox:8080/core/mandate", "DISABLED", 60,
     "Registers an e-mandate. Withdrawn pending the revised NPCI flow."),
    ("IFSC Branch Lookup", "Reference", "GET", "/v1/reference/ifsc",
     "http://mock-sandbox:8080/core/ifsc", "ACTIVE", 600,
     "Branch and bank details for an IFSC code."),
]

PARTNER_USERS = [
    ("Acme Fintech Pvt Ltd", "Priya Sharma", "priya.sharma@acmefintech.in", "PARTNER_ADMIN"),
    ("Acme Fintech Pvt Ltd", "Rahul Shetty", "rahul.shetty@acmefintech.in", "PARTNER_DEVELOPER"),
    ("Kavery Payments", "Anil Nair", "anil.nair@kaverypay.in", "PARTNER_ADMIN"),
]

DOCUMENTATION = {
    "Account Balance Enquiry": {
        "source": "MANUAL",
        "queryParameters": [
            {"name": "accountNumber", "type": "string", "required": True,
             "example": "50100123456789", "description": "The account to read."},
        ],
        "requestHeaders": [],
        "requestBodyFields": [],
        "requestBodyExample": None,
        "responseHeaders": [
            {"name": "X-RateLimit-Remaining", "type": "integer", "required": False,
             "example": "119", "description": "Calls left in the current window."},
        ],
        "responses": [
            {"statusCode": 200, "description": "Balance found",
             "bodyExample": '{\n  "accountNumber" : "50100123456789",\n'
                            '  "available" : 48250.75,\n  "currency" : "INR"\n}',
             "bodyFields": [
                 {"name": "available", "type": "number", "required": True, "example": "48250.75",
                  "description": "Balance available to draw on."},
             ]},
            {"statusCode": 404, "description": "No such account",
             "bodyExample": '{\n  "code" : "ACCOUNT_NOT_FOUND"\n}', "bodyFields": []},
        ],
    },
}


async def _is_empty(conn: AsyncConnection) -> bool:
    row = (
        await conn.execute(
            text("SELECT (SELECT count(*) FROM partner) + (SELECT count(*) FROM api_definition) AS n")
        )
    ).first()
    return int(row.n) == 0


async def seed() -> bool:
    """Seed the demo data. Returns whether anything was written."""
    settings = get_settings()
    if settings.environment == "production" or not settings.demo_seed_enabled:
        return False

    now = datetime.now(UTC)
    async with engine().begin() as conn:
        # One instance at a time, and only ever into an empty database.
        await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": 8_241_907_553_110_004})
        if not await _is_empty(conn):
            return False

        log.info("Empty database under a non-production profile — seeding demo data")
        groups: dict[str, str] = {}
        for name, description in GROUPS:
            group_id = str(uuid.uuid4())
            groups[name] = group_id
            await conn.execute(
                text(
                    "INSERT INTO partner_group (id, name, description, status, created_at)"
                    " VALUES (:id, :name, :d, 'ACTIVE', :now)"
                ),
                {"id": group_id, "name": name, "d": description, "now": now},
            )

        partners: dict[str, str] = {}
        for index, (name, group, contact, client_id) in enumerate(PARTNERS, start=1):
            partner_id = str(uuid.uuid4())
            partners[name] = partner_id
            await conn.execute(
                text(
                    "INSERT INTO partner (id, code, name, group_id, access_tier, status,"
                    " contact_email, client_id_sandbox, created_at, updated_at)"
                    " VALUES (:id, :code, :name, :g, 'UAT_ONLY', 'ACTIVE', :contact, :cid,"
                    "         :now, :now)"
                ),
                {"id": partner_id, "code": f"PTN-{index:05d}", "name": name,
                 "g": groups[group], "contact": contact, "cid": client_id, "now": now},
            )

        for email, full_name, role in PLATFORM_USERS:
            await conn.execute(
                text(
                    "INSERT INTO platform_user (id, email, full_name, role, status, created_at,"
                    " created_by, updated_at)"
                    " VALUES (:id, :email, :n, :r, 'ACTIVE', :now, 'demo-seed', :now)"
                ),
                {"id": str(uuid.uuid4()), "email": email, "n": full_name, "r": role, "now": now},
            )

        api_ids: list[tuple[str, str]] = []
        for name, category, method, path, backend, status, rate, description in APIS:
            api_id = str(uuid.uuid4())
            api_ids.append((api_id, name))
            documentation = DOCUMENTATION.get(name)
            await conn.execute(
                text(
                    "INSERT INTO api_definition (id, name, category, http_method, proxy_path,"
                    " backend_url_sandbox, status, guest_visible, rate_limit_count,"
                    " rate_limit_window, description, documentation, disabled_at, created_at,"
                    " updated_at)"
                    " VALUES (:id, :name, :c, :m, :p, :b, :s, false, :rate, 'MINUTE', :d,"
                    "         :doc, :disabled, :now, :now)"
                ),
                {"id": api_id, "name": name, "c": category, "m": method, "p": path, "b": backend,
                 "s": status, "rate": rate, "d": description,
                 "doc": json.dumps(documentation, separators=(",", ":")) if documentation else None,
                 "disabled": now if status == "DISABLED" else None, "now": now},
            )

        for partner_name, full_name, email, role in PARTNER_USERS:
            await conn.execute(
                text(
                    "INSERT INTO partner_user (id, partner_id, full_name, email, role, status,"
                    " created_at, created_by, updated_at)"
                    " VALUES (:id, :p, :n, :e, :r, 'ACTIVE', :now, 'demo-seed', :now)"
                ),
                {"id": str(uuid.uuid4()), "p": partners[partner_name], "n": full_name,
                 "e": email, "r": role, "now": now},
            )

        await _seed_traffic(conn, api_ids, now)

    log.info("Seeded %d partners and %d APIs with a day of traffic", len(PARTNERS), len(APIS))
    return True


async def _seed_traffic(conn: AsyncConnection, api_ids: list[tuple[str, str]], now: datetime) -> None:
    """A day of synthetic calls, so a fresh environment shows a populated dashboard.

    Relative to now rather than to fixed timestamps: a dashboard that reads "no traffic in the last
    hour" on a freshly seeded demo looks broken, and the reader cannot tell that from a real outage.
    """
    rng = random.Random(20260914)  # noqa: S311 - a repeatable shape, not a secret
    live = [(api_id, name) for api_id, name in api_ids if "Mandate" not in name]
    client_ids = [client for *_, client in ((p[0], p[3]) for p in PARTNERS)]
    rows: list[dict[str, Any]] = []
    for minutes in range(24 * 60):
        occurred = now - timedelta(minutes=minutes)
        # Busier in the working day, which is what makes the usage chart worth looking at.
        hour = occurred.astimezone(UTC).hour
        volume = 3 if 4 <= hour <= 13 else 1
        for _ in range(rng.randint(0, volume)):
            api_id, _ = rng.choice(live)
            failed = rng.random() < 0.04
            rows.append({
                "at": occurred, "api": api_id, "env": "SANDBOX",
                "client": rng.choice(client_ids),
                "status": rng.choice([400, 401, 429, 500]) if failed else 200,
                "latency": rng.randint(180, 900) if failed else rng.randint(40, 260),
            })
    for start in range(0, len(rows), 500):
        await conn.execute(
            text(
                "INSERT INTO usage_event (occurred_at, api_id, environment, client_id,"
                " status_code, latency_ms)"
                " VALUES (:at, CAST(:api AS uuid), :env, :client, :status, :latency)"
            ),
            rows[start:start + 500],
        )
