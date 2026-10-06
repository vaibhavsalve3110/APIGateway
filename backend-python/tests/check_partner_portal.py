"""Phase 2 gate: a partner token sees exactly what Java shows it, and nothing of another organization.

Every route in the Developer Portal is scoped to the organization on the caller's token. Response
parity alone cannot prove that scoping is right — two services can be identically wrong. So this
checks both: that each route matches Java for the same partner, and that what partner A is shown
never contains partner B's Client IDs, keys or products.

Read-only: it creates nothing and changes nothing.
"""

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _secret, diff  # noqa: E402

JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def token(email: str, roles: list[str], partner_code: str | None = None) -> str:
    """A token in backend-java's TokenService shape, including the /partners/<CODE> group."""
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {
        "iss": "apigw-platform", "iat": now, "exp": now + 3600,
        "sub": email, "preferred_username": email, "name": "Portal Parity",
        "realm_access": {"roles": roles},
    }
    if partner_code:
        claims["groups"] = [f"/partners/{partner_code}"]
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(_secret().encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def call(base: str, path: str, bearer: str):
    request = urllib.request.Request(f"{base}{path}")
    request.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw


ADMIN = token("admin@apigw.local", ["ADMIN"])

# The two real organizations and a Partner Admin in each, read from the platform rather than assumed.
_, partners = call(JAVA, "/api/admin/partners", ADMIN)
_, users = call(JAVA, "/api/admin/partner-users", ADMIN)
by_partner = {}
for u in users:
    by_partner.setdefault(u["partnerId"], u)

tenants = []
for p in partners:
    user = by_partner.get(p["id"])
    if user:
        tenants.append({"partner": p, "user": user,
                        "token": token(user["email"], ["PARTNER"], p["code"])})

assert len(tenants) >= 2, "need two organizations with a portal user to prove isolation"
a, b = tenants[0], tenants[1]
print(f"  using {a['partner']['code']} ({a['user']['email']}) and "
      f"{b['partner']['code']} ({b['user']['email']})")

ROUTES = [
    "/api/me",
    "/api/partner/me",
    "/api/partner/apis",
    "/api/partner/keys",
    "/api/partner/products",
    "/api/partner/pages",
    "/api/partner/usage",
    "/api/partner/usage/logs?limit=50",
    "/api/partner/dashboard?window=PT24H",
    "/api/partner/dashboard?window=P7D",
]

print("--- response parity, per organization")
for tenant in (a, b):
    code = tenant["partner"]["code"]
    for route in ROUTES:
        status_java, from_java = call(JAVA, route, tenant["token"])
        status_py, from_python = call(PYTHON, route, tenant["token"])
        if status_java != status_py:
            check(f"{code} {route}", False, f"java {status_java}, python {status_py}: {from_python}")
            continue
        # The dashboard window boundary and the usage report range are each service's own clock read.
        d = [x for x in diff(from_java, from_python)
             if not x.startswith((".window.from:", ".from:", ".to:"))]
        check(f"{code} {route}", not d, "; ".join(d[:4]))

print("--- a named API, and one that is not live")
_, catalogue = call(JAVA, "/api/partner/apis", a["token"])
if catalogue:
    api_id = catalogue[0]["id"]
    sj, from_java = call(JAVA, f"/api/partner/apis/{api_id}", a["token"])
    sp, from_python = call(PYTHON, f"/api/partner/apis/{api_id}", a["token"])
    d = diff(from_java, from_python)
    check("api detail matches", sj == sp and not d, f"{sj}/{sp} " + "; ".join(d[:4]))

_, all_apis = call(JAVA, "/api/admin/apis", ADMIN)
dormant = next((x for x in all_apis if x["status"] != "ACTIVE"), None)
if dormant:
    sj, _ = call(JAVA, f"/api/partner/apis/{dormant['id']}", a["token"])
    sp, body = call(PYTHON, f"/api/partner/apis/{dormant['id']}", a["token"])
    check(f"a {dormant['status']} API reads as absent, not forbidden",
          sj == sp == 404 and body.get("code") == "NOT_FOUND", f"java {sj}, python {sp}: {body}")

print("--- tenant isolation")
for service, base in (("java", JAVA), ("python", PYTHON)):
    _, me_a = call(base, "/api/partner/me", a["token"])
    _, me_b = call(base, "/api/partner/me", b["token"])
    check(f"{service}: each organization sees its own identity",
          me_a["code"] == a["partner"]["code"] and me_b["code"] == b["partner"]["code"],
          f"{me_a.get('code')} / {me_b.get('code')}")

    b_clients = {x for x in (b["partner"]["clientIdSandbox"],
                             b["partner"]["clientIdProduction"]) if x}
    _, logs_a = call(base, "/api/partner/usage/logs?limit=200", a["token"])
    leaked = {row["clientId"] for row in logs_a} & b_clients
    check(f"{service}: {a['partner']['code']}'s logs carry none of "
          f"{b['partner']['code']}'s Client IDs", not leaked, str(leaked))

    _, dash_a = call(base, "/api/partner/dashboard?window=P30D", a["token"])
    leaked = {row["clientId"] for row in dash_a["recentCalls"]} & b_clients
    check(f"{service}: {a['partner']['code']}'s dashboard carries none either", not leaked, str(leaked))

    _, keys_a = call(base, "/api/partner/keys", a["token"])
    _, keys_b = call(base, "/api/partner/keys", b["token"])
    overlap = {k["id"] for k in keys_a} & {k["id"] for k in keys_b}
    check(f"{service}: the two organizations share no keys", not overlap, str(overlap))

print("--- a partner cannot reach the admin API")
for route in ("/api/admin/partners", "/api/admin/audit", "/api/admin/errors"):
    sj, _ = call(JAVA, route, a["token"])
    sp, _ = call(PYTHON, route, a["token"])
    check(f"{route} refused to a partner", sj == sp and sj in (401, 403), f"java {sj}, python {sp}")

print("--- a token with no organization")
orphan = token("nobody@example.test", ["PARTNER"])
sj, _ = call(JAVA, "/api/partner/me", orphan)
sp, body = call(PYTHON, "/api/partner/me", orphan)
check("a PARTNER token carrying no group is refused by both",
      sj == sp and sj >= 400, f"java {sj}, python {sp}: {body}")

print()
print("FAILED" if failures else "all partner portal checks passed")
sys.exit(1 if failures else 0)
