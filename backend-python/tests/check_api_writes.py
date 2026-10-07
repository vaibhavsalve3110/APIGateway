"""Phase 3 gate: an API written by either service produces the same record and the same gateway config.

The record is the easy half. The gateway is the half that matters: APISIX accepts almost any JSON it
is handed, so a wrong route is not rejected — it is applied, and the gateway then quietly misroutes,
stops rate-limiting, or stops checking keys. So this reads the route back out of both APISIX
deployments and compares what each service actually published, plugin by plugin.

Everything it creates is deleted. Deleting an API needs a cooling period to have passed, so the test
removes its fixtures straight from the database and withdraws their gateway routes by hand.
"""

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token, diff  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
TOKEN = _token(["ADMIN"])

infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")


def env_value(key: str, fallback: str) -> str:
    m = re.search(rf"^{key}=(.*)$", infra_env, re.M)
    return (m.group(1).strip() or fallback) if m else fallback


APISIX = {
    "SANDBOX": ("http://127.0.0.1:9180", env_value("APISIX_SANDBOX_ADMIN_KEY", "change-me-sandbox-admin-key")),
    "PRODUCTION": ("http://127.0.0.1:9181", env_value("APISIX_PRODUCTION_ADMIN_KEY", "change-me-production-admin-key")),
}
SHORT = {"SANDBOX": "sbx", "PRODUCTION": "prd"}

failures = 0
created: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def call(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        request.add_header("Content-Type", "application/json")
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


def apisix_route(environment: str, api_id: str):
    """The route as the gateway itself holds it, or None when there is none."""
    base, key = APISIX[environment]
    request = urllib.request.Request(
        f"{base}/apisix/admin/routes/api-{api_id}-{SHORT[environment]}"
    )
    request.add_header("X-API-KEY", key)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    # APISIX wraps the stored object and adds its own bookkeeping; compare only what we sent.
    value = body.get("value", body)
    return {k: v for k, v in value.items() if k not in ("id", "create_time", "update_time", "status", "priority")}


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


def body(name: str, proxy_path: str, backend: str, production: str | None = None) -> dict:
    return {
        "name": name,
        "category": "ZZ Parity",
        "httpMethod": "GET",
        "proxyPath": proxy_path,
        "backendUrlSandbox": backend,
        "backendUrlProduction": production,
        "rateLimitCount": 120,
        "rateLimitWindow": "MINUTE",
        "ownerTeam": "Platform",
        "description": "temporary, created by a parity check",
    }


try:
    print("--- create")
    # The backend URL carries no {param}: java's URI.create rejects braces outright and answers 500,
    # so that shape cannot be onboarded through either service today. Checked explicitly further down.
    java_body = body("ZZ Parity API Java", "/zz/parity/{accountId}/balance",
                     "http://mock-sandbox:8080/accounts",
                     "http://mock-production:8080/accounts")
    code, java_api = call(JAVA, "POST", "/api/admin/apis", java_body)
    check("java creates an API", code == 201 and java_api.get("id"), f"{code} {java_api}")
    if java_api.get("id"):
        created.append(java_api["id"])

    py_body = dict(java_body, name="ZZ Parity API Python", proxyPath="/zz/parity-py/{accountId}/balance")
    code, py_api = call(PYTHON, "POST", "/api/admin/apis", py_body)
    check("python creates an API", code == 201 and py_api.get("id"), f"{code} {py_api}")
    if py_api.get("id"):
        created.append(py_api["id"])

    if java_api.get("id") and py_api.get("id"):
        _, java_read = call(JAVA, "GET", f"/api/admin/apis/{py_api['id']}")
        d = diff(java_read, py_api)
        check("java reads a python-created API identically", not d, "; ".join(d[:6]))

        print("--- gateway configuration, as APISIX actually holds it")
        for environment in ("SANDBOX", "PRODUCTION"):
            java_route = apisix_route(environment, java_api["id"])
            py_route = apisix_route(environment, py_api["id"])
            check(f"{environment}: java published a route", java_route is not None)
            check(f"{environment}: python published a route", py_route is not None)
            if java_route and py_route:
                # The two APIs differ only in name and proxy path, so normalise those before diffing.
                normalised_java = json.loads(
                    json.dumps(java_route)
                    .replace("ZZ Parity API Java", "NAME")
                    .replace("/zz/parity/", "/zz/PATH/")
                    .replace(java_api["id"], "API_ID")
                )
                normalised_py = json.loads(
                    json.dumps(py_route)
                    .replace("ZZ Parity API Python", "NAME")
                    .replace("/zz/parity-py/", "/zz/PATH/")
                    .replace(py_api["id"], "API_ID")
                )
                d = diff(normalised_java, normalised_py)
                check(f"{environment}: both services published identical config", not d,
                      "; ".join(d[:8]))

        print("--- the path rewrite both produced")
        # A static backend path maps straight through. The regex_uri branch needs a {param} in the
        # backend URL, which java rejects outright (see the known defect below), so it is unreachable
        # through the API on either service and is covered by the unit-level checks instead.
        rewrite = (apisix_route("SANDBOX", py_api["id"]) or {}).get("plugins", {}).get("proxy-rewrite")
        check("python wrote the static path rewrite",
              rewrite == {"uri": "/accounts"}, json.dumps(rewrite))

        print("--- status changes move the gateway route")
        call(PYTHON, "POST", f"/api/admin/apis/{py_api['id']}/disable")
        check("disabling removes the sandbox route",
              apisix_route("SANDBOX", py_api["id"]) is None, "route still present")
        call(PYTHON, "POST", f"/api/admin/apis/{py_api['id']}/enable")
        check("enabling puts it back",
              apisix_route("SANDBOX", py_api["id"]) is not None, "route missing")

        print("--- the cooling period")
        code, problem = call(PYTHON, "DELETE", f"/api/admin/apis/{py_api['id']}")
        check("python refuses to delete an API that is not disabled",
              code == 409 and problem.get("code") == "API_NOT_DISABLED", f"{code} {problem}")
        call(PYTHON, "POST", f"/api/admin/apis/{py_api['id']}/disable")
        code, problem = call(PYTHON, "DELETE", f"/api/admin/apis/{py_api['id']}")
        check("python refuses to delete inside the cooling period",
              code == 409 and problem.get("code") == "COOLING_PERIOD_ACTIVE", f"{code} {problem}")
        code, problem = call(JAVA, "DELETE", f"/api/admin/apis/{py_api['id']}")
        check("java refuses it the same way",
              code == 409 and problem.get("code") == "COOLING_PERIOD_ACTIVE", f"{code} {problem}")

        print("--- edits and guest visibility")
        code, edited = call(PYTHON, "PUT", f"/api/admin/apis/{py_api['id']}",
                            dict(py_body, rateLimitCount=500, description="edited by the check"))
        check("python updates an API", code == 200 and edited["rateLimitCount"] == 500,
              f"{code} {edited}")
        code, visible = call(PYTHON, "PUT", f"/api/admin/apis/{py_api['id']}/guest-visibility",
                             {"guestVisible": True})
        check("python sets guest visibility", code == 200 and visible["guestVisible"] is True,
              f"{code} {visible}")

        _, list_java = call(JAVA, "GET", "/api/admin/apis")
        _, list_python = call(PYTHON, "GET", "/api/admin/apis")
        d = diff(list_java, list_python)
        check("api lists still match", not d, "; ".join(d[:6]))

    print("--- a backend URL containing a path parameter")
    # Pre-existing defect in backend-java, not something this port introduced: URI.create rejects
    # braces, so onboarding such an API answers 500 instead of a validation error. Python tolerates
    # it, which is why the two are asserted separately rather than for parity.
    braced = dict(java_body, name="ZZ Parity Braced", proxyPath="/zz/braced/{id}",
                  backendUrlSandbox="http://mock-sandbox:8080/accounts/{id}",
                  backendUrlProduction=None)
    code, problem = call(JAVA, "POST", "/api/admin/apis", braced)
    check("java still answers 500 for a braced backend URL (known defect)",
          code == 500, f"{code} {problem}")

    print("--- validation")
    code, problem = call(PYTHON, "POST", "/api/admin/apis", dict(java_body, proxyPath="no-leading-slash"))
    check("python rejects a proxy path with no leading slash",
          code == 400 and problem.get("code") == "VALIDATION_FAILED", f"{code} {problem}")
    code, problem = call(JAVA, "POST", "/api/admin/apis", dict(java_body, proxyPath="no-leading-slash"))
    check("java rejects it the same way",
          code == 400 and problem.get("code") == "VALIDATION_FAILED", f"{code} {problem}")

finally:
    print("--- cleanup")
    for api_id in created:
        for environment in ("SANDBOX", "PRODUCTION"):
            base, key = APISIX[environment]
            request = urllib.request.Request(
                f"{base}/apisix/admin/routes/api-{api_id}-{SHORT[environment]}", method="DELETE"
            )
            request.add_header("X-API-KEY", key)
            try:
                urllib.request.urlopen(request, timeout=15)  # noqa: S310
            except urllib.error.HTTPError:
                pass
        # The cooling period makes the API unusable, so the row goes directly.
        psql(f"delete from api_definition where id = '{api_id}';")
        print(f"  removed {api_id} and its gateway routes")

    left = psql("select count(*) from api_definition where category = 'ZZ Parity';")
    check("no test APIs left behind", left.endswith("0"), left)
    for api_id in created:
        for environment in ("SANDBOX", "PRODUCTION"):
            check(f"{environment} route for {api_id[:8]} is gone",
                  apisix_route(environment, api_id) is None)

print()
print("FAILED" if failures else "all API write checks passed")
sys.exit(1 if failures else 0)
