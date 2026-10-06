"""Phase 1 gate: a gateway batch posted to Python lands rows Java reads back identically.

The ingest endpoint is the only write path the APISIX gateways use and the only one authenticated by
a shared token rather than a session. It is also the one place where being lenient matters: an entry
the gateway sends malformed must be skipped, because the gateway retries the whole batch and a hard
failure would stall every other row behind it.

The rows this writes carry a distinctive client_id and are deleted from usage_event afterwards.
"""

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token, diff  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
TOKEN = _token(["ADMIN"])

MARKER_JAVA = "zz-ingest-java"
MARKER_PYTHON = "zz-ingest-python"

infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")
INGEST = re.search(r"^USAGE_INGEST_TOKEN=(.*)$", infra_env, re.M).group(1).strip()

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def call(base: str, method: str, path: str, body=None, auth: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)
    request.add_header("Authorization", auth if auth is not None else f"Bearer {TOKEN}")
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


def psql(sql: str) -> str:
    password = re.search(r"^DB_PASSWORD=(.*)$", infra_env, re.M).group(1).strip()
    # A throwaway client container on the host network; no service image here ships psql.
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "host",
         "-e", f"PGPASSWORD={password}",
         # Docker env flags must precede the image name; psql reads a stray -e as a connection option.
         "-e", "PGOPTIONS=--search_path=apim",
         "postgres:17-alpine", "psql",
         "postgresql://apigw@host.docker.internal:5432/apigw", "-Atc", sql],
        capture_output=True, text=True, timeout=180,
    )
    return (result.stdout + result.stderr).strip()


def batch_for(marker: str, api_id: str) -> list[dict]:
    """One well-formed entry per shape the gateway actually sends, plus rows that must be skipped."""
    now = datetime.now(UTC).timestamp()
    return [
        # A normal sandbox call: route id carries the API and the environment.
        {"route_id": f"api-{api_id}-sbx", "client_id": marker, "status": 200,
         "request_time": 0.123, "msec": now},
        # Production, and a numeric status sent as a string, which the gateway does.
        {"route_id": f"api-{api_id}-prd", "client_id": marker, "status": "503",
         "request_time": "1.5", "msec": now},
        # No route id: env falls back to the explicit field, api stays null.
        {"env": "sandbox", "client_id": marker, "status": 404, "request_time": 0.01, "msec": now},
        # "-" is what the logger writes for a missing value; it must read as the fallback, not fail.
        {"route_id": f"api-{api_id}-sbx", "client_id": marker, "status": 201,
         "request_time": "-", "msec": now},
        # Unparseable row: a status that is not a number. Both services skip it.
        {"route_id": "api-not-a-uuid-sbx", "client_id": marker, "status": "oops",
         "request_time": None, "msec": "nonsense"},
    ]


try:
    _, apis = call(JAVA, "GET", "/api/admin/apis")
    api_id = apis[0]["id"]

    print("--- authentication")
    code, problem = call(PYTHON, "POST", "/internal/usage/batch", [], auth="Ingest wrong-token")
    check("python rejects a wrong ingest token",
          code == 401 and problem.get("code") == "BAD_INGEST_TOKEN", f"{code} {problem}")
    code, problem = call(JAVA, "POST", "/internal/usage/batch", [], auth="Ingest wrong-token")
    check("java rejects it the same way",
          code == 401 and problem.get("code") == "BAD_INGEST_TOKEN", f"{code} {problem}")
    code, problem = call(PYTHON, "POST", "/internal/usage/batch", [], auth=None)
    check("python rejects a session token on the ingest path", code == 401, f"{code} {problem}")

    print("--- ingest")
    code, py_result = call(PYTHON, "POST", "/internal/usage/batch", batch_for(MARKER_PYTHON, api_id),
                           auth=f"Ingest {INGEST}")
    check("python accepts the batch", code == 200, f"{code} {py_result}")
    check("python skipped the unusable row, kept four",
          py_result == {"accepted": 4}, json.dumps(py_result))

    code, java_result = call(JAVA, "POST", "/internal/usage/batch", batch_for(MARKER_JAVA, api_id),
                             auth=f"Ingest {INGEST}")
    check("java accepts the same batch", code == 200, f"{code} {java_result}")
    check("java accepted the same count", java_result == py_result,
          f"java={java_result} python={py_result}")

    print("--- what landed in the database")
    columns = ("status_code, latency_ms, environment, "
               "coalesce(api_id::text,'null'), to_char(occurred_at,'YYYY-MM-DD HH24:MI')")
    rows_py = psql(f"select {columns} from usage_event where client_id='{MARKER_PYTHON}'"
                   f" order by status_code;")
    rows_java = psql(f"select {columns} from usage_event where client_id='{MARKER_JAVA}'"
                     f" order by status_code;")
    check("python wrote the same rows java did", rows_py == rows_java,
          f"\n      python: {rows_py}\n      java:   {rows_java}")

    expected_statuses = {"200", "201", "404", "503"}
    got = {line.split("|")[0] for line in rows_py.splitlines() if line}
    check("every well-formed row landed", got == expected_statuses, f"got {sorted(got)}")

    print("--- read back through the API")
    frm = (datetime.now(UTC).replace(microsecond=0)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Widen the window backwards so the rows just written are inside it.
    frm = f"{frm[:11]}00:00:00Z"
    for marker in (MARKER_PYTHON, MARKER_JAVA):
        path = f"/api/admin/usage/logs?from={frm}&clientId={marker}&limit=50"
        _, from_java = call(JAVA, "GET", path)
        _, from_python = call(PYTHON, "GET", path)
        d = diff(from_java, from_python)
        check(f"both services read the {marker.split('-')[-1]}-written rows identically",
              not d, "; ".join(d[:6]))
        check(f"{marker} rows are visible in the log ({len(from_java)} found)",
              len(from_java) == 4, f"{len(from_java)}")

finally:
    print("--- cleanup")
    deleted = psql(
        f"delete from usage_event where client_id in ('{MARKER_PYTHON}','{MARKER_JAVA}');"
    )
    print(f"  removed the test rows: {deleted}")
    left = psql(
        f"select count(*) from usage_event where client_id in ('{MARKER_PYTHON}','{MARKER_JAVA}');"
    )
    check("no test usage rows left behind", left.endswith("0"), left)

print()
print("FAILED" if failures else "all usage ingest checks passed")
sys.exit(1 if failures else 0)
