"""Proves the ported Products module against the Java one, using temporary data it removes again.

Three things are checked that an empty table cannot show:
  1. a product created by JAVA reads identically from both services;
  2. a product created by PYTHON reads identically from both services, so the write path produces
     the same stored shape;
  3. the business rules refuse the same things with the same codes.

Everything it creates is deleted at the end. Audit rows are left behind on purpose — that is what an
audit log is for.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token, diff  # noqa: E402

JAVA = "http://127.0.0.1:8088"
PYTHON = "http://127.0.0.1:8090"
TOKEN = _token(["ADMIN"])


def call(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
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


failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


# ---------------------------------------------------------------- fixtures
_, apis = call(JAVA, "GET", "/api/admin/apis")
assert isinstance(apis, list) and len(apis) >= 2, "need at least two APIs to build a journey"
api_a, api_b = apis[0]["id"], apis[1]["id"]
_, partners = call(JAVA, "GET", "/api/admin/partners")
partner_id = partners[0]["id"]

created: list[tuple[str, str]] = []  # (base that created it, id)

try:
    # ------------------------------------------------------------ 1. created by Java
    body = {
        "name": "ZZ Parity Journey Java",
        "summary": "temporary, created by a parity check",
        "description": "two steps with a dependency",
        "journeyMarkdown": "# Flow\n1. balance\n2. transfer",
        "steps": [
            {"apiId": api_a, "note": "check the balance first"},
            {"apiId": api_b, "note": "then move the money", "dependsOnApiId": api_a},
        ],
    }
    code, java_made = call(JAVA, "POST", "/api/admin/products", body)
    check("java creates a product", code == 201, f"status {code}: {java_made}")
    created.append((JAVA, java_made["id"]))

    _, from_java = call(JAVA, "GET", f"/api/admin/products/{java_made['id']}")
    _, from_python = call(PYTHON, "GET", f"/api/admin/products/{java_made['id']}")
    differences = diff(from_java, from_python)
    check("both services read a java-created product identically", not differences, "; ".join(differences[:6]))

    _, list_java = call(JAVA, "GET", "/api/admin/products")
    _, list_python = call(PYTHON, "GET", "/api/admin/products")
    differences = diff(list_java, list_python)
    check("product lists match", not differences, "; ".join(differences[:6]))

    # ------------------------------------------------------------ 2. created by Python
    body["name"] = "ZZ Parity Journey Python"
    code, py_made = call(PYTHON, "POST", "/api/admin/products", body)
    check("python creates a product", code == 201, f"status {code}: {py_made}")
    created.append((PYTHON, py_made["id"]))

    _, from_java = call(JAVA, "GET", f"/api/admin/products/{py_made['id']}")
    _, from_python = call(PYTHON, "GET", f"/api/admin/products/{py_made['id']}")
    differences = diff(from_java, from_python)
    check("java reads a python-created product identically", not differences, "; ".join(differences[:6]))
    check("python wrote a slug", py_made["slug"] == "zz-parity-journey-python", py_made["slug"])
    check("python wrote both steps in order",
          [s["step"] for s in py_made["steps"]] == [1, 2], json.dumps(py_made["steps"])[:200])
    check("python resolved the dependency name",
          py_made["steps"][1]["dependsOnApiName"] is not None, json.dumps(py_made["steps"][1])[:200])

    # ------------------------------------------------------------ 3. business rules
    code, problem = call(PYTHON, "POST", "/api/admin/products",
                         {"name": "ZZ Self Dep", "steps": [{"apiId": api_a, "dependsOnApiId": api_a}]})
    check("python refuses a self-dependency", code == 409 and problem.get("code") == "SELF_DEPENDENCY",
          f"{code} {problem}")
    code, problem = call(JAVA, "POST", "/api/admin/products",
                         {"name": "ZZ Self Dep", "steps": [{"apiId": api_a, "dependsOnApiId": api_a}]})
    check("java refuses it the same way", code == 409 and problem.get("code") == "SELF_DEPENDENCY",
          f"{code} {problem}")

    code, problem = call(PYTHON, "POST", "/api/admin/products",
                         {"name": "ZZ Bad Dep", "steps": [{"apiId": api_a, "dependsOnApiId": api_b}]})
    check("python refuses a dependency outside the product",
          code == 409 and problem.get("code") == "DEPENDENCY_NOT_IN_PRODUCT", f"{code} {problem}")

    # Publish, assign, unassign, unpublish — the whole lifecycle on the python-created product.
    code, published = call(PYTHON, "POST", f"/api/admin/products/{py_made['id']}/publish")
    check("python publishes", code == 200 and published["status"] == "PUBLISHED", f"{code} {published}")

    code, problem = call(PYTHON, "DELETE", f"/api/admin/products/{py_made['id']}")
    check("python refuses to delete a published product",
          code == 409 and problem.get("code") == "PRODUCT_PUBLISHED", f"{code} {problem}")

    code, assigned = call(PYTHON, "POST", f"/api/admin/products/{py_made['id']}/assignments",
                          {"partnerId": partner_id})
    check("python assigns to an organization", code == 200 and len(assigned["assignments"]) == 1,
          f"{code} {assigned}")

    code, problem = call(PYTHON, "POST", f"/api/admin/products/{py_made['id']}/assignments",
                         {"partnerId": partner_id})
    check("python refuses a duplicate assignment",
          code == 409 and problem.get("code") == "ALREADY_ASSIGNED", f"{code} {problem}")

    _, from_java = call(JAVA, "GET", f"/api/admin/products/{py_made['id']}")
    differences = diff(from_java, assigned)
    check("java sees the assignment identically", not differences, "; ".join(differences[:6]))

    assignment_id = assigned["assignments"][0]["id"]
    code, unassigned = call(PYTHON, "DELETE",
                            f"/api/admin/products/{py_made['id']}/assignments/{assignment_id}")
    check("python unassigns", code == 200 and unassigned["assignments"] == [], f"{code} {unassigned}")

    code, draft = call(PYTHON, "POST", f"/api/admin/products/{py_made['id']}/unpublish")
    check("python unpublishes", code == 200 and draft["status"] == "DRAFT", f"{code} {draft}")

finally:
    # ------------------------------------------------------------ clean up
    for base, product_id in created:
        call(base, "POST", f"/api/admin/products/{product_id}/unpublish")
        code, _ = call(base, "DELETE", f"/api/admin/products/{product_id}")
        print(f"  cleanup: deleted {product_id} -> {code}")
    _, left = call(JAVA, "GET", "/api/admin/products")
    stragglers = [p["name"] for p in left if p["name"].startswith("ZZ ")]
    check("no test products left behind", not stragglers, ", ".join(stragglers))

print()
print("FAILED" if failures else "all product checks passed")
sys.exit(1 if failures else 0)
