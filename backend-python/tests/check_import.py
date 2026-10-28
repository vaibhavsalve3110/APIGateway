"""Gate: importing a Swagger / OpenAPI file or a Postman collection (CP-API-06).

Java reads these with `swagger-parser`; this service does it by hand, because there is no single
Python equivalent and because following a remote `$ref` would be a server-side request forgery. So
the two implementations are genuinely different code, and the only way to know they agree is to
feed both the same files and compare.

Three specifications, each chosen for what it would catch:

* **OpenAPI 3 with a `$ref`** — the resolution this service had to write itself.
* **Swagger 2.0** — a different shape entirely: the type sits on the parameter, the body is a
  parameter, and the response schema is not under `content`. `swagger-parser` converts it; this
  service handles both shapes directly.
* **a Postman collection** — folders, saved responses, and a `{{baseUrl}}` variable.

Plus the two refusals that matter, and the one that is a security decision: a remote `$ref` must be
*refused with a warning*, never fetched.

Needs both services up. Run:  python tests/check_import.py
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token, diff  # noqa: E402

JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
ADMIN = _token(["ADMIN"])
DEVELOPER = _token(["DEVELOPER"], username="dev.person@apigw.local")

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


def post(base: str, content: str, token: str = ADMIN):
    data = json.dumps({"fileName": "spec", "content": content}).encode()
    request = urllib.request.Request(base + "/api/admin/apis/import", data=data, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() or "{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}


OPENAPI_3 = """
openapi: 3.0.3
info:
  title: Core Banking
  version: "1"
servers:
  - url: https://core.example.in
paths:
  /v1/payments/{txnId}:
    get:
      summary: Fetch a payment
      tags: [Payments]
      parameters:
        - name: verbose
          in: query
          required: true
          schema: {type: string}
        - name: X-Trace
          in: header
          schema: {type: string}
      responses:
        "200":
          description: Found
          headers:
            X-RateLimit-Remaining: {schema: {type: integer}}
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Payment"}
        "404": {description: Missing}
    post:
      summary: Replay a payment
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [amount]
              properties:
                amount: {type: number, example: 100.5}
                note: {type: string}
      responses:
        "202": {description: Accepted}
components:
  schemas:
    Payment:
      type: object
      required: [status]
      properties:
        status: {type: string, example: SETTLED}
        amount: {type: number}
"""

SWAGGER_2 = """
{"swagger":"2.0","info":{"title":"Legacy","version":"1"},"host":"legacy.example.in","basePath":"/api",
 "paths":{"/balance":{"get":{"summary":"Balance","produces":["application/json"],
   "parameters":[{"name":"account","in":"query","required":true,"type":"string"}],
   "responses":{"200":{"description":"OK","schema":{"type":"object","properties":{"balance":{"type":"number"}}}}}}}}}
"""

POSTMAN = """
{"info":{"_postman_id":"x1","name":"Partner APIs",
  "schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
 "variable":[{"key":"baseUrl","value":"https://core.example.in"}],
 "item":[{"name":"Payments","item":[
   {"name":"Create payment","request":{"method":"POST",
     "header":[{"key":"X-Trace","value":"abc"}],
     "body":{"mode":"raw","raw":"{\\"amount\\": 10}"},
     "url":{"raw":"{{baseUrl}}/v1/payments","path":["v1","payments"],
            "query":[{"key":"dryRun","value":"true"}]}},
    "response":[{"name":"Created","code":201,"body":"{\\"id\\": \\"p1\\"}"}]}]}]}
"""

REMOTE_REF = """
openapi: 3.0.3
info: {title: Hostile, version: "1"}
paths:
  /x:
    get:
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema: {$ref: "http://169.254.169.254/latest/meta-data"}
"""

try:
    for label, spec in (("OpenAPI 3 with a $ref", OPENAPI_3),
                        ("Swagger 2.0", SWAGGER_2),
                        ("a Postman collection", POSTMAN)):
        print(f"--- {label}")
        py_code, py_out = post(PYTHON, spec)
        java_code, java_out = post(JAVA, spec)
        check("python read it", py_code == 200, f"{py_code} {str(py_out)[:160]}")
        check("java read it", java_code == 200, f"{java_code} {str(java_out)[:160]}")
        if py_code != 200 or java_code != 200:
            print()
            continue

        check("both found the same format and the same number of operations",
              py_out["format"] == java_out["format"]
              and len(py_out["operations"]) == len(java_out["operations"]),
              f"python {py_out['format']}/{len(py_out['operations'])} vs "
              f"java {java_out['format']}/{len(java_out['operations'])}")

        # Two exclusions, both deliberate:
        #   .warnings — each implementation's own commentary; swagger-parser emits different text.
        #   .suggestedBackendBaseUrl on Swagger 2 — swagger-parser leaves it scheme-relative
        #     ("//host/api") when the file declares no schemes, and that value is then rejected by
        #     the backend-URL field it pre-fills. This service emits https:// instead, on purpose.
        # Everything else a person acts on has to match.
        differences = [
            d for d in diff(java_out, py_out)
            if not d.startswith(".warnings")
            and not (label == "Swagger 2.0" and d.startswith(".suggestedBackendBaseUrl"))
        ]
        check("every imported operation is identical", not differences,
              "; ".join(differences[:6]))
        print()

    print("--- a remote $ref is refused, not fetched")
    py_code, py_out = post(PYTHON, REMOTE_REF)
    # The operation still imports; what the reference pointed at simply is not there.
    check("the file is still read", py_code == 200, f"{py_code} {str(py_out)[:160]}")
    if py_code == 200:
        check("and a warning says the reference was not followed",
              any("not followed" in w for w in py_out.get("warnings", [])),
              str(py_out.get("warnings")))

    print()
    print("--- refusals")
    for label, content, expected in (
        ("a file that is not a specification", "this is not a specification",
         ("UNREADABLE_SPECIFICATION", "NO_OPERATIONS")),
        ("a specification with no operations", "openapi: 3.0.0",
         ("UNREADABLE_SPECIFICATION", "NO_OPERATIONS")),
        ("an empty file", "   ", ("EMPTY_FILE",)),
    ):
        py_code, py_out = post(PYTHON, content)
        check(f"python refuses {label}",
              py_code == 400 and py_out.get("code") in expected, f"{py_code} {py_out.get('code')}")
        if label != "an empty file":
            java_code, java_out = post(JAVA, content)
            check(f"java refuses it too ({label})",
                  java_code == 400 and java_out.get("code") in expected,
                  f"{java_code} {java_out.get('code')}")

    print()
    print("--- access")
    py_code, _ = post(PYTHON, OPENAPI_3, token=DEVELOPER)
    java_code, _ = post(JAVA, OPENAPI_3, token=DEVELOPER)
    check("a developer is refused, as on java", py_code == 403 and java_code == 403,
          f"python {py_code} java {java_code}")

finally:
    # Nothing is created by an import, so there is nothing to clean up — which is the point of it
    # returning operations rather than saving them.
    pass

print()
print("FAILED" if failures else "all import checks passed")
sys.exit(1 if failures else 0)
