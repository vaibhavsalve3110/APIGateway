"""Gate: the ADMIN/DEVELOPER split, and the approval a publish has to go through.

The properties that matter, in the order it would hurt to get them wrong:

* **a developer cannot publish.** Not through enable, and not by editing a live API either — if the
  second one worked, the approval would be decorative, because a developer could leave the API in
  draft and change the live one instead.
* **nobody approves their own request**, administrators included. That is the entire value of the
  step.
* **a developer cannot reach partner organizations, credentials, products, portal content, or the
  APIM users and roles.** The last one matters most: if they could, they would simply make
  themselves an admin.
* a developer *can* do their job — draft and edit APIs, and read every log.
* the platform cannot be left with no administrator.
* an approved change applies exactly what was proposed, and the trail names both the requester and
  the approver.

Tokens are minted directly rather than signed in for, as the other gates do. Everything created here
is removed at the end.

Needs the stack up:  python tests/check_roles_and_approvals.py
"""

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PYTHON = "http://127.0.0.1:18090"
infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")

ADMIN = _token(["ADMIN"])
# A second administrator, so an approval has somebody other than the requester to come from.
OTHER_ADMIN = _token(["ADMIN"], username="second.admin@apigw.local")
DEV = _token(["DEVELOPER"], username="dev.person@apigw.local")

failures = 0
created_apis: list[str] = []
created_users: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


def call(token: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(PYTHON + path, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode() or "{}"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}


def psql(sql: str) -> str:
    password = re.search(r"^DB_PASSWORD=(.*)$", infra_env, re.M).group(1).strip()
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "host",
         "-e", f"PGPASSWORD={password}", "-e", "PGOPTIONS=--search_path=apim",
         "postgres:17-alpine", "psql",
         "postgresql://apigw@host.docker.internal:5432/apigw", "-Atc", sql],
        capture_output=True, text=True, timeout=180,
    )
    return (result.stdout + result.stderr).strip()


def new_api(token: str, name: str, path: str) -> tuple[int, dict]:
    return call(token, "POST", "/api/admin/apis", {
        "name": name,
        "category": "ZZ Approvals",
        "httpMethod": "GET",
        "proxyPath": path,
        "backendUrlSandbox": "http://mock-sandbox:8080/zz",
        "rateLimitCount": 10,
        "rateLimitWindow": "MINUTE",
    })


try:
    print("--- the role rename reached the database")
    left = psql("select count(*) from platform_user where role = 'EDITOR';")
    check("no user still holds EDITOR", left == "0", f"{left} rows")
    roles_held = psql("select distinct role from platform_user order by role;")
    check("only ADMIN and DEVELOPER exist", set(roles_held.split()) <= {"ADMIN", "DEVELOPER"}, roles_held)

    print()
    print("--- a developer can do their own job")
    code, drafted = new_api(DEV, "ZZ Approvals Draft", f"/zz-approvals/{uuid.uuid4().hex[:8]}")
    check("a developer creates an API", code == 201, f"{code} {drafted}")
    if code == 201:
        created_apis.append(drafted["id"])
        check("it is a draft, not live", drafted["status"] == "DRAFT", drafted["status"])

        api_id = drafted["id"]
        code, edited = call(DEV, "PUT", f"/api/admin/apis/{api_id}", {
            "name": "ZZ Approvals Draft Renamed",
            "category": "ZZ Approvals",
            "httpMethod": "GET",
            "proxyPath": drafted["proxyPath"],
            "backendUrlSandbox": "http://mock-sandbox:8080/zz2",
            "rateLimitCount": 20,
            "rateLimitWindow": "MINUTE",
        })
        check("a developer edits a draft, and it applies at once",
              code == 200 and edited.get("name") == "ZZ Approvals Draft Renamed", f"{code} {edited}")

    for path, what in (
        ("/api/admin/apis", "the API catalogue"),
        ("/api/admin/dashboard", "the dashboard"),
        ("/api/admin/usage/logs", "the call logs"),
        ("/api/admin/usage/report", "the usage report"),
        ("/api/admin/errors", "the system errors"),
        ("/api/admin/audit", "the audit trail"),
    ):
        code, _ = call(DEV, "GET", path)
        check(f"a developer reads {what}", code == 200, str(code))

    print()
    print("--- what a developer must not reach")
    for method, path, what in (
        ("GET", "/api/admin/partners", "partner organizations"),
        ("GET", "/api/admin/partner-groups", "partner groups"),
        ("GET", "/api/admin/partner-users", "Developer Portal users"),
        ("GET", "/api/admin/products", "API products"),
        ("GET", "/api/admin/pages", "portal content"),
        ("GET", "/api/admin/platform-users", "the APIM users list"),
    ):
        code, _ = call(DEV, method, path)
        check(f"a developer is refused {what}", code == 403, str(code))

    code, problem = call(DEV, "POST", "/api/admin/platform-users", {
        "fullName": "ZZ Self Promoted", "email": "zz-self@promoted.test", "role": "ADMIN"})
    check("a developer cannot create an APIM user, let alone an admin", code == 403, f"{code} {problem}")

    print()
    print("--- publishing needs somebody else")
    if created_apis:
        api_id = created_apis[0]
        code, request = call(DEV, "POST", f"/api/admin/apis/{api_id}/enable")
        check("a developer's publish is accepted as a request, not done", code == 202, f"{code} {request}")
        check("the reply is a change request", request.get("objectType") == "API", str(request)[:120])
        check("it is pending", request.get("status") == "PENDING", str(request.get("status")))
        request_id = request.get("id")

        live = psql(f"select status from api_definition where id = '{api_id}';")
        check("the API is still a draft while the request waits", live == "DRAFT", live)

        code, _ = call(DEV, "POST", f"/api/admin/change-requests/{request_id}/approve")
        check("a developer cannot approve", code == 403, str(code))

        code, second = call(DEV, "POST", f"/api/admin/apis/{api_id}/enable")
        check("a second request for the same API is refused",
              code == 409 and second.get("code") == "CHANGE_ALREADY_PENDING", f"{code} {second}")

        code, approved = call(OTHER_ADMIN, "POST", f"/api/admin/change-requests/{request_id}/approve",
                              {"note": "looks fine"})
        check("another administrator approves it", code == 200, f"{code} {approved}")
        check("the request is recorded as approved", approved.get("status") == "APPROVED",
              str(approved.get("status")))
        check("and the API is now live", approved.get("applied", {}).get("status") == "ACTIVE",
              str(approved.get("applied", {}).get("status")))
        live = psql(f"select status from api_definition where id = '{api_id}';")
        check("the database agrees", live == "ACTIVE", live)

        print()
        print("--- an admin cannot approve their own request")
        code, own = call(ADMIN, "POST", f"/api/admin/apis/{api_id}/disable")
        check("an admin's disable is immediate (CP-API-03, not queued)", code == 200, f"{code} {own}")
        code, own_request = call(ADMIN, "POST", f"/api/admin/apis/{api_id}/enable")
        check("an admin's publish still raises a request", code == 202, f"{code} {own_request}")
        own_id = own_request.get("id")
        code, refused = call(ADMIN, "POST", f"/api/admin/change-requests/{own_id}/approve")
        check("and they cannot approve it themselves",
              code == 403 and refused.get("code") == "SELF_APPROVAL_FORBIDDEN", f"{code} {refused}")
        code, refused = call(ADMIN, "POST", f"/api/admin/change-requests/{own_id}/reject")
        check("nor reject it themselves", code == 403, str(code))
        code, withdrawn = call(ADMIN, "POST", f"/api/admin/change-requests/{own_id}/withdraw")
        check("but they can withdraw it", code == 200 and withdrawn.get("status") == "WITHDRAWN",
              f"{code} {withdrawn}")

        print()
        print("--- editing a live API is reviewed too")
        # Raised by one administrator and approved by the other, deliberately: asking and approving
        # as the same person is exactly what the rule above forbids, and doing it here by accident
        # left the API disabled and made the rest of this section test nothing.
        code, republish = call(ADMIN, "POST", f"/api/admin/apis/{api_id}/enable")
        check("re-publish requested for the live-edit checks", code == 202, f"{code} {republish}")
        code, _ = call(OTHER_ADMIN, "POST", f"/api/admin/change-requests/{republish['id']}/approve")
        check("and approved by the other administrator", code == 200, str(code))
        live = psql(f"select status from api_definition where id = '{api_id}';")
        check("the API is live again for this part", live == "ACTIVE", live)

        code, proposal = call(DEV, "PUT", f"/api/admin/apis/{api_id}", {
            "name": "ZZ Approvals Live Edit",
            "category": "ZZ Approvals",
            "httpMethod": "GET",
            "proxyPath": drafted["proxyPath"],
            "backendUrlSandbox": "http://mock-sandbox:8080/changed",
            "rateLimitCount": 99,
            "rateLimitWindow": "MINUTE",
        })
        check("a developer's edit to a live API becomes a request", code == 202, f"{code} {proposal}")
        check("the summary says what would change",
              "backend URL" in proposal.get("summary", "") and "rate limit" in proposal.get("summary", ""),
              proposal.get("summary", ""))
        still = psql(f"select backend_url_sandbox, rate_limit_count from api_definition where id='{api_id}';")
        check("the live API is untouched while it waits", "changed" not in still and "99" not in still, still)

        code, applied = call(OTHER_ADMIN, "POST",
                             f"/api/admin/change-requests/{proposal['id']}/approve")
        check("approving applies exactly what was proposed",
              code == 200 and applied.get("applied", {}).get("backendUrlSandbox")
              == "http://mock-sandbox:8080/changed"
              and applied.get("applied", {}).get("rateLimitCount") == 99,
              f"{code} {applied.get('applied', {})}")

        print()
        print("--- the trail names both people")
        trail = call(ADMIN, "GET", "/api/admin/audit?limit=60")[1]
        actions = {(e["action"], e["actor"]) for e in trail}
        check("the requester is recorded as having asked",
              any(a.startswith("REQUEST_") and actor == "dev.person@apigw.local"
                  for a, actor in actions), str(sorted(actions))[:200])
        check("the approver is recorded as having allowed it",
              any(a.startswith("APPROVE_") and actor == "second.admin@apigw.local"
                  for a, actor in actions), str(sorted(actions))[:200])
        check("and the change itself is attributed to the requester",
              any(a == "UPDATE" and actor == "dev.person@apigw.local" for a, actor in actions),
              str(sorted(actions))[:200])

    print()
    print("--- APIM users and roles")
    code, made = call(ADMIN, "POST", "/api/admin/platform-users", {
        "fullName": "ZZ New Developer", "email": "zz-new.dev@apigw.test", "role": "DEVELOPER"})
    check("an admin creates an APIM user", code == 201, f"{code} {made}")
    if code == 201:
        created_users.append(made["id"])
        check("they start active, with no sign-in yet",
              made["status"] == "ACTIVE" and made["lastLoginAt"] is None, str(made))
        code, promoted = call(ADMIN, "PUT", f"/api/admin/platform-users/{made['id']}/role",
                              {"role": "ADMIN"})
        check("an admin sets their role", code == 200 and promoted["role"] == "ADMIN", f"{code} {promoted}")
        code, suspended = call(ADMIN, "PUT", f"/api/admin/platform-users/{made['id']}/status",
                               {"status": "DISABLED"})
        check("and can suspend them", code == 200 and suspended["status"] == "DISABLED", str(code))

    # An address cannot be both a portal user and an APIM user.
    existing = psql("select email from partner_user limit 1;")
    if existing and "@" in existing:
        code, clash = call(ADMIN, "POST", "/api/admin/platform-users", {
            "fullName": "ZZ Clash", "email": existing, "role": "DEVELOPER"})
        check("an address already used in the Developer Portal is refused",
              code == 409 and clash.get("code") == "EMAIL_IN_USE", f"{code} {clash}")

    print()
    print("--- the platform cannot be left without an administrator")
    admins = psql("select id from platform_user where role='ADMIN' and status='ACTIVE';").split()
    if len(admins) == 1:
        code, refused = call(ADMIN, "PUT", f"/api/admin/platform-users/{admins[0]}/role",
                             {"role": "DEVELOPER"})
        check("demoting the only admin is refused",
              code == 409 and refused.get("code") == "LAST_ADMIN", f"{code} {refused}")
    else:
        print(f"  skip  there are {len(admins)} active admins, so this cannot be provoked safely")

finally:
    print()
    print("--- cleanup")
    for user_id in created_users:
        psql(f"delete from platform_user where id = '{user_id}';")
        print(f"  removed APIM user {user_id}")
    for api_id in created_apis:
        psql(f"delete from change_request where object_id = '{api_id}';")
        psql(f"delete from api_definition where id = '{api_id}';")
        print(f"  removed API {api_id} and its requests")
    psql("delete from platform_user where email like 'zz-%';")
    psql("delete from api_definition where category = 'ZZ Approvals';")
    leftover = psql("select count(*) from api_definition where category = 'ZZ Approvals';")
    check("no test APIs left behind", leftover == "0", leftover)
    leftover = psql("select count(*) from platform_user where email like 'zz-%';")
    check("no test APIM users left behind", leftover == "0", leftover)

print()
print("FAILED" if failures else "all role and approval checks passed")
sys.exit(1 if failures else 0)
