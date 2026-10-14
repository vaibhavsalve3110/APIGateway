"""Gate: the OpenAPI document describes this service, and goes on describing it.

The response shapes in `app/schemas.py` are attached to the document after FastAPI generates it
rather than through `response_model`, which keeps them from filtering real responses — see
`app/openapi_doc.py` for why that matters here. The cost of that choice is that nothing in the
framework notices when a route is added, removed or renamed and the registry is not updated. This
gate is what notices.

What it enforces:

* every route has an entry, and every entry names a route that exists. A new endpoint fails this
  until someone says what it returns.
* every documented response model exists in the components, so no operation points at a `$ref`
  that Swagger UI cannot resolve.
* the document is valid OpenAPI 3.1, which the Swagger UI and any generated client assume.
* a session scheme is declared, applied to everything that needs one, and applied to nothing that
  does not. A padlock on a public route tells a reader to go and find a token they do not need.
* no operation declares a 422. The validation handler in `main.py` answers 400 to match
  backend-java, so FastAPI's default entry would document a status this service never sends.

Needs nothing running: it reads the app object. Run it before committing a router change.

    python tests/check_openapi.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402
from app.openapi_doc import BEARER, INGEST, INGEST_ROUTES, PUBLIC, RESPONSES  # noqa: E402

# FastAPI's own documentation endpoints, which describe the document rather than the API.
DOCS_PATHS = {"/v3/api-docs", "/swagger-ui.html", "/docs/oauth2-redirect", "/redoc"}

failures = 0


def report(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


print("--- routes and registry agree")

actual: set[tuple[str, str]] = set()
for route in app.routes:
    methods = getattr(route, "methods", None)
    if not methods or route.path in DOCS_PATHS or route.path.startswith("/ui"):
        continue
    for method in methods:
        if method not in ("HEAD", "OPTIONS"):
            actual.add((method.lower(), route.path))

missing = sorted(f"{m.upper()} {p}" for m, p in actual - set(RESPONSES))
report(
    f"every one of the {len(actual)} routes has a documented response",
    not missing,
    "add to RESPONSES in app/openapi_doc.py: " + ", ".join(missing),
)

stale = sorted(f"{m.upper()} {p}" for m, p in set(RESPONSES) - actual)
report(
    "no entry names a route that no longer exists",
    not stale,
    "remove from RESPONSES: " + ", ".join(stale),
)

orphan_public = sorted(f"{m.upper()} {p}" for m, p in (PUBLIC | INGEST_ROUTES) - actual)
report("PUBLIC and INGEST_ROUTES name real routes", not orphan_public, ", ".join(orphan_public))

print()
print("--- the document itself")

document = app.openapi()
schemas = document["components"]["schemas"]
operations = [(m.lower(), p, o) for p, item in document["paths"].items() for m, o in item.items()]

try:
    from openapi_spec_validator import validate
except ImportError:
    print("  skip  openapi-spec-validator is not installed; structural validation skipped")
else:
    try:
        validate(document)
    except Exception as exc:  # noqa: BLE001 - whatever it objects to, the document is wrong
        report("the document is valid OpenAPI 3.1", False, str(exc).splitlines()[0])
    else:
        report("the document is valid OpenAPI 3.1", True)

report(
    "no operation was left undescribed",
    "x-undocumented-operations" not in document["info"],
    str(document["info"].get("x-undocumented-operations")),
)

described = [
    f"{m.upper()} {p}"
    for m, p, o in operations
    if not any(
        code.startswith("2") and ("content" in body or code == "204")
        for code, body in o["responses"].items()
    )
]
report("every operation documents what it returns", not described, ", ".join(described))

undocumented_prose = [f"{m.upper()} {p}" for m, p, o in operations if not o.get("description")]
report(
    "every operation has prose describing it (a handler docstring)",
    not undocumented_prose,
    ", ".join(undocumented_prose),
)

print()
print("--- every $ref resolves")

dangling: list[str] = []


def walk(node: object, where: str) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[1]
            if name not in schemas:
                dangling.append(f"{where} -> {name}")
        for key, value in node.items():
            walk(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk(value, f"{where}[{index}]")


walk(document["paths"], "paths")
walk(schemas, "components.schemas")
report(f"all schema references resolve ({len(schemas)} components)", not dangling, ", ".join(dangling))

print()
print("--- sessions")

declared = document["components"].get("securitySchemes", {})
report("a bearer scheme is declared, so Swagger UI can send a token", BEARER in declared)
report("the gateways' ingest token has its own scheme", INGEST in declared)

unprotected = [
    f"{m.upper()} {p}"
    for m, p, o in operations
    if not o.get("security") and (m, p) not in PUBLIC and p not in DOCS_PATHS
]
report("every route that needs a session declares one", not unprotected, ", ".join(unprotected))

over_protected = [f"{m.upper()} {p}" for m, p, o in operations if o.get("security") and (m, p) in PUBLIC]
report("no public route is marked as needing a session", not over_protected, ", ".join(over_protected))

wrong_scheme = [
    f"{m.upper()} {p}"
    for m, p, o in operations
    if (m, p) in INGEST_ROUTES and o.get("security") != [{INGEST: []}]
]
report("the ingest route asks for the ingest token, not a session", not wrong_scheme, ", ".join(wrong_scheme))

print()
print("--- error documentation")

no_problem = [
    f"{m.upper()} {p}"
    for m, p, o in operations
    if "application/problem+json" not in o["responses"].get("500", {}).get("content", {})
]
report("every operation documents the problem document it fails with", not no_problem, ", ".join(no_problem))

has_422 = [f"{m.upper()} {p}" for m, p, o in operations if "422" in o["responses"]]
report(
    "no operation claims a 422: validation failures answer 400 here, as backend-java does",
    not has_422,
    ", ".join(has_422),
)

print()
print(f"{len(operations)} operations, {len(schemas)} schemas")
print("FAILED" if failures else "the OpenAPI document matches this service")
sys.exit(1 if failures else 0)
