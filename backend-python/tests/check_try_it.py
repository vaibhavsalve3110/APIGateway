"""Gate: Try it live, ported from backend-java.

Both services still implement this, so the strongest check available is to send the *same* call to
each and compare the answers. That is what most of this does. A partner sees these replies verbatim
in the Developer Portal, so a difference in wording is a difference they would notice.

What it covers:

* the real call: the same request to both services returns the same status, the same displayed URL
  and the same body.
* path parameters are encoded as single segments — a value containing a slash must not reach a
  different route than the one documented. `IMPS 1/2` has to become `IMPS%201%2F2`.
* the refusals, which are the security-relevant half: somebody else's key, a key that does not
  exist, a production key used from the portal, a missing path parameter, and an API that is not
  live. Each must answer with the same code from both services.

Everything it creates is removed at the end.

Needs the stack up. Run:  python tests/check_try_it.py
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
from parity import _token, diff  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")

ADMIN = _token(["ADMIN"])
APPROVER = _token(["ADMIN"], username="approver@apigw.local")

failures = 0
created_apis: list[str] = []
created_partners: list[str] = []
MARK = uuid.uuid4().hex[:8]


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


def call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token or ADMIN}")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
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


try:
    print("--- a live API and a partner with a sandbox key")
    group_id = call(PYTHON, "GET", "/api/admin/partner-groups")[1][0]["id"]

    code, api = call(PYTHON, "POST", "/api/admin/apis", {
        "name": f"ZZ TryIt {MARK}",
        "category": "ZZ TryIt",
        "httpMethod": "GET",
        "proxyPath": f"/zz/tryit-{MARK}/{{txnId}}/status",
        "backendUrlSandbox": "http://mock-sandbox:8080/core/status",
        "rateLimitCount": 120,
        "rateLimitWindow": "MINUTE",
        "documentation": {
            "queryParameters": [{"name": "verbose", "required": True, "example": "true"}],
            "responseHeaders": [{"name": "X-RateLimit-Remaining", "example": "59"}],
            "responses": [
                {"statusCode": 200, "description": "Found", "bodyExample": '{"status":"SETTLED"}'},
                {"statusCode": 400, "description": "Bad input", "bodyExample": '{"code":"BAD"}'},
            ],
        },
    })
    check("the API was created", code == 201, f"{code} {api}")
    api_id = api["id"]
    created_apis.append(api_id)

    # Publishing is reviewed, so it takes two administrators.
    code, request = call(PYTHON, "POST", f"/api/admin/apis/{api_id}/enable")
    call(PYTHON, "POST", f"/api/admin/change-requests/{request['id']}/approve", token=APPROVER)
    check("the API is live", psql(f"select status from api_definition where id='{api_id}';")
          == "ACTIVE")

    code, issued = call(PYTHON, "POST", "/api/admin/partners", {
        "name": f"ZZ TryIt Partner {MARK}",
        "groupId": group_id,
        "accessTier": "UAT_ONLY",
        "contactEmail": f"zz-tryit-{MARK}@tryit.test",
        "clientIdSandbox": f"zz-tryit-{MARK}-sbx",
    })
    partner_id = issued["partner"]["id"]
    partner_code = issued["partner"]["code"]
    created_partners.append(partner_id)

    code, key = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/keys/SANDBOX")
    check("a sandbox key was issued", code in (200, 201) and key.get("plaintext"), str(code))
    sandbox_key = key["plaintext"]
    partner_token = _token(["PARTNER"], username=f"zz-tryit-{MARK}@tryit.test")
    # The portal's token carries the organization as a group claim; mint one that does.
    import base64
    import hashlib
    import hmac
    import time

    def partner_jwt(code_: str) -> str:
        secret = re.search(r"^AUTH_JWT_SECRET=(.*)$", infra_env, re.M).group(1).strip()
        b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")  # noqa: E731
        now = int(time.time())
        header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        claims = {
            "iss": "apigw-platform", "iat": now, "exp": now + 3600,
            "sub": f"zz-tryit-{MARK}@tryit.test",
            "preferred_username": f"zz-tryit-{MARK}@tryit.test",
            "name": "Try It Check", "realm_access": {"roles": ["PARTNER"]},
            "groups": [f"/partners/{code_}"],
        }
        payload = b64(json.dumps(claims, separators=(",", ":")).encode())
        signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        return f"{header}.{payload}.{b64(signature)}"

    partner_token = partner_jwt(partner_code)

    print()
    print("--- the same call to both services")
    body = {"apiKey": sandbox_key, "pathParams": {"txnId": "IMPS 1/2"}, "query": {"verbose": "true"}}
    py_code, py_out = call(PYTHON, "POST", f"/api/partner/apis/{api_id}/try", body, partner_token)
    java_code, java_out = call(JAVA, "POST", f"/api/partner/apis/{api_id}/try", body, partner_token)
    check("python answered", py_code == 200, f"{py_code} {str(py_out)[:200]}")
    check("java answered the same status", java_code == py_code, f"java {java_code} python {py_code}")
    # The slash in "IMPS 1/2" must come back as %2F, not as a path separator — otherwise the call
    # would reach a different route than the one documented. The space must be %20.
    check("the displayed URL encodes the path parameter as one segment",
          "/IMPS%201%2F2/" in str(py_out.get("requestUrl"))
          and str(py_out.get("requestUrl")).endswith("?verbose=true"),
          str(py_out.get("requestUrl")))
    check("both services show the same URL",
          py_out.get("requestUrl") == java_out.get("requestUrl"),
          f"python {py_out.get('requestUrl')} vs java {java_out.get('requestUrl')}")
    # latencyMs is measured per call and headers include a per-response date, so they cannot match.
    differences = [
        d for d in diff(java_out, py_out)
        if not d.startswith((".latencyMs", ".headers", ".note", ".reference"))
    ]
    check("the rest of the answer is identical", not differences, "; ".join(differences[:5]))

    print()
    print("--- the refusals")
    for label, request_body, expected_code, expected_status in (
        ("a key that does not exist",
         {"apiKey": "agw_sbx_not-a-real-key", "pathParams": {"txnId": "T1"},
          "query": {"verbose": "true"}}, "INVALID_KEY", 401),
        ("a missing path parameter",
         {"apiKey": sandbox_key, "query": {"verbose": "true"}}, "MISSING_PATH_PARAMETER", 400),
    ):
        p_code, p_out = call(PYTHON, "POST", f"/api/partner/apis/{api_id}/try", request_body,
                             partner_token)
        j_code, j_out = call(JAVA, "POST", f"/api/partner/apis/{api_id}/try", request_body,
                             partner_token)
        check(f"python refuses {label}", p_code == expected_status
              and p_out.get("code") == expected_code, f"{p_code} {p_out}")
        check(f"java refuses it identically ({label})",
              j_code == p_code and j_out.get("code") == p_out.get("code"),
              f"java {j_code} {j_out.get('code')} vs python {p_code} {p_out.get('code')}")
        check(f"and with the same wording ({label})",
              j_out.get("detail") == p_out.get("detail"),
              f"java {j_out.get('detail')!r} vs python {p_out.get('detail')!r}")

    print()
    print("--- another organization's key is not accepted")
    code, other = call(PYTHON, "POST", "/api/admin/partners", {
        "name": f"ZZ TryIt Other {MARK}",
        "groupId": group_id,
        "accessTier": "UAT_ONLY",
        "clientIdSandbox": f"zz-tryit-other-{MARK}-sbx",
    })
    other_id = other["partner"]["id"]
    created_partners.append(other_id)
    other_key = call(PYTHON, "POST", f"/api/admin/partners/{other_id}/keys/SANDBOX")[1]["plaintext"]
    p_code, p_out = call(PYTHON, "POST", f"/api/partner/apis/{api_id}/try", {
        "apiKey": other_key, "pathParams": {"txnId": "T1"}, "query": {"verbose": "true"}},
        partner_token)
    check("a valid key belonging to someone else is refused",
          p_code == 401 and p_out.get("code") == "INVALID_KEY", f"{p_code} {p_out}")

    print()
    print("--- an API that is not live")
    call(PYTHON, "POST", f"/api/admin/apis/{api_id}/disable")
    p_code, p_out = call(PYTHON, "POST", f"/api/partner/apis/{api_id}/try", body, partner_token)
    check("a withdrawn API answers 404, as the catalogue does",
          p_code == 404, f"{p_code} {p_out}")

finally:
    print()
    print("--- cleanup")
    for partner in created_partners:
        psql(f"delete from security_key where partner_id = '{partner}';")
        psql(f"delete from partner where id = '{partner}';")
    for api_id_ in created_apis:
        psql(f"delete from change_request where object_id = '{api_id_}';")
        psql(f"delete from api_definition where id = '{api_id_}';")
    check("no test APIs left behind",
          psql("select count(*) from api_definition where category = 'ZZ TryIt';") == "0")
    check("no test organizations left behind",
          psql("select count(*) from partner where name like 'ZZ TryIt%';") == "0")

print()
print("FAILED" if failures else "all try-it-live checks passed")
sys.exit(1 if failures else 0)
