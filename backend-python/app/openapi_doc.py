"""The OpenAPI document, enriched after FastAPI has generated it.

FastAPI infers a document from the handlers, and because every handler here returns
`dict[str, Any]` — deliberately, so nothing stands between a query result and the wire — that
document described 71 operations and the shape of none of them. Swagger UI listed the API and could
not say what any call returned, nor send a token.

This module fills that in *after* generation rather than through `response_model`, which would make
FastAPI filter every response through a model. A model that is subtly wrong would then drop fields
silently, and the whole point of the parity harness is that this service answers byte-for-byte as
backend-java does. Documentation that lies is a nuisance; documentation that rewrites responses is a
defect. So: the handlers are untouched, and the document is corrected to match them.

If a response shape changes, change it in `schemas.py`. The test in `tests/test_openapi.py` fails if
an operation named here no longer exists, so this cannot quietly rot into fiction.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from . import schemas as s

BEARER = "bearerAuth"
INGEST = "ingestToken"

# --------------------------------------------------------------------------- what each route returns
#
# Keyed by (method, path) exactly as FastAPI records it. A list value documents an array of that
# model. `None` means the route answers with no body.

RESPONSES: dict[tuple[str, str], Any] = {
    # --- APIs, admin side.
    #
    # Three of these no longer return an ApiView. Publishing always raises a change request, and so
    # does editing a live API or a developer withdrawing one, so the reply is the request — see
    # change_requests.py. `objectType` is what tells a caller which it received.
    ("get", "/api/admin/apis"): [s.ApiView],
    ("post", "/api/admin/apis"): s.ApiView,
    ("get", "/api/admin/apis/{api_id}"): s.ApiView,
    ("put", "/api/admin/apis/{api_id}"): s.ApiOrChangeRequest,
    ("delete", "/api/admin/apis/{api_id}"): None,
    ("post", "/api/admin/apis/{api_id}/disable"): s.ApiOrChangeRequest,
    ("post", "/api/admin/apis/{api_id}/enable"): s.ChangeRequestView,
    ("put", "/api/admin/apis/{api_id}/guest-visibility"): s.ApiView,
    # --- partners and groups
    ("get", "/api/admin/partner-groups"): [s.GroupView],
    ("post", "/api/admin/partner-groups"): s.GroupView,
    ("get", "/api/admin/partners"): [s.PartnerView],
    ("post", "/api/admin/partners"): s.IssuedCredentials,
    ("get", "/api/admin/partners/{partner_id}"): s.PartnerView,
    ("put", "/api/admin/partners/{partner_id}"): s.PartnerView,
    ("put", "/api/admin/partners/{partner_id}/status"): s.PartnerView,
    ("put", "/api/admin/partners/{partner_id}/access-tier"): s.IssuedCredentials,
    ("post", "/api/admin/partners/{partner_id}/signature"): s.IssuedCredentials,
    ("post", "/api/admin/partners/{partner_id}/ipv-salt"): s.IssuedCredentials,
    ("post", "/api/admin/partners/{partner_id}/ipv-salt/reveal"): s.RevealedSalt,
    # --- partner users
    ("get", "/api/admin/partner-users"): [s.PartnerUserView],
    ("get", "/api/admin/partner-users/{user_id}"): s.PartnerUserView,
    ("put", "/api/admin/partner-users/{user_id}"): s.PartnerUserView,
    ("delete", "/api/admin/partner-users/{user_id}"): None,
    ("post", "/api/admin/partner-users/{user_id}/access"): s.PartnerUserView,
    ("get", "/api/admin/partners/{partner_id}/users"): [s.PartnerUserView],
    ("post", "/api/admin/partners/{partner_id}/users"): s.PartnerUserView,
    # --- keys
    ("get", "/api/admin/partners/{partner_id}/keys"): [s.KeyView],
    ("post", "/api/admin/partners/{partner_id}/keys/{environment}"): s.GeneratedKey,
    ("post", "/api/admin/keys/{key_id}/revoke"): s.KeyView,
    ("get", "/api/partner/keys"): [s.KeyView],
    ("post", "/api/partner/keys/{environment}"): s.GeneratedKey,
    # --- products
    ("get", "/api/admin/products"): [s.ProductView],
    ("post", "/api/admin/products"): s.ProductView,
    ("get", "/api/admin/products/{product_id}"): s.ProductView,
    ("put", "/api/admin/products/{product_id}"): s.ProductView,
    ("delete", "/api/admin/products/{product_id}"): None,
    ("post", "/api/admin/products/{product_id}/publish"): s.ProductView,
    ("post", "/api/admin/products/{product_id}/unpublish"): s.ProductView,
    ("post", "/api/admin/products/{product_id}/assignments"): s.ProductView,
    ("delete", "/api/admin/products/{product_id}/assignments/{assignment_id}"): s.ProductView,
    # --- portal content
    ("get", "/api/admin/pages"): [s.PageView],
    ("post", "/api/admin/pages"): s.PageView,
    ("get", "/api/admin/pages/{page_id}"): s.PageView,
    ("put", "/api/admin/pages/{page_id}"): s.PageView,
    ("delete", "/api/admin/pages/{page_id}"): None,
    ("post", "/api/admin/pages/{page_id}/publish"): s.PageView,
    ("post", "/api/admin/pages/{page_id}/unpublish"): s.PageView,
    # --- dashboards, audit, errors
    ("get", "/api/admin/dashboard"): s.Dashboard,
    ("get", "/api/admin/audit"): [s.AuditView],
    ("get", "/api/admin/audit/actors"): [s.AuditActor],
    ("get", "/api/admin/errors"): [s.ErrorView],
    # --- usage
    ("get", "/api/admin/usage/report"): s.UsageReport,
    ("get", "/api/admin/usage/logs"): [s.LogEntry],
    ("get", "/api/admin/usage/apis/{api_id}/consumers"): [s.PartnerUsage],
    ("post", "/internal/usage/batch"): s.IngestResult,
    # --- sign-in and identity
    ("post", "/api/auth/captcha"): s.Captcha,
    ("post", "/api/auth/otp/request"): s.CodeRequested,
    ("post", "/api/auth/otp/verify"): s.SignedIn,
    ("get", "/api/auth/me"): s.Me,
    ("get", "/api/me"): s.Me,
    # --- the partner portal
    ("get", "/api/partner/me"): s.PartnerMe,
    ("get", "/api/partner/dashboard"): s.PartnerDashboard,
    ("get", "/api/partner/apis"): [s.CatalogueApi],
    ("get", "/api/partner/apis/{api_id}"): s.ApiDetail,
    ("get", "/api/partner/products"): [s.PartnerProductView],
    ("get", "/api/partner/products/{slug}"): s.PartnerProductView,
    ("get", "/api/partner/pages"): [s.PageLink],
    ("get", "/api/partner/pages/{slug}"): s.PublishedPageView,
    ("get", "/api/partner/usage"): s.UsageReport,
    ("get", "/api/partner/usage/logs"): [s.LogEntry],
    # --- approvals
    ("get", "/api/admin/change-requests"): [s.ChangeRequestView],
    ("get", "/api/admin/change-requests/{request_id}"): s.ChangeRequestView,
    ("post", "/api/admin/change-requests/{request_id}/approve"): s.ChangeRequestView,
    ("post", "/api/admin/change-requests/{request_id}/reject"): s.ChangeRequestView,
    ("post", "/api/admin/change-requests/{request_id}/withdraw"): s.ChangeRequestView,
    # --- APIM users and roles
    ("get", "/api/admin/platform-users"): [s.PlatformUserView],
    ("post", "/api/admin/platform-users"): s.PlatformUserView,
    ("get", "/api/admin/platform-users/{user_id}"): s.PlatformUserView,
    ("put", "/api/admin/platform-users/{user_id}"): s.PlatformUserView,
    ("put", "/api/admin/platform-users/{user_id}/role"): s.PlatformUserView,
    ("put", "/api/admin/platform-users/{user_id}/status"): s.PlatformUserView,
    ("delete", "/api/admin/platform-users/{user_id}"): None,
    # --- payload encryption
    ("get", "/api/crypto/public-key"): s.PublicKey,
    # --- probe
    ("get", "/actuator/health"): s.Health,
}

# Routes that take no session token. Everything else gets the bearer scheme, which is what puts a
# padlock beside it in Swagger UI and makes "Authorize" apply.
PUBLIC = {
    ("post", "/api/auth/captcha"),
    ("post", "/api/auth/otp/request"),
    ("post", "/api/auth/otp/verify"),
    ("get", "/actuator/health"),
    # Necessarily open: a client cannot encrypt its first request until it has this key, and has no
    # session yet either.
    ("get", "/api/crypto/public-key"),
}

# Carries the shared ingest token rather than a session, so it gets its own scheme.
INGEST_ROUTES = {("post", "/internal/usage/batch")}

TAGS = [
    {
        "name": "auth",
        "description": (
            "Sign-in. Request a CAPTCHA, request a one-time code for an email address, then exchange "
            "the two for a session token. The token is an HS256 JWT that **backend-java accepts as "
            "well** — both services sign with the same secret, so a session works whichever one "
            "answers the next request."
        ),
    },
    {"name": "apis", "description": "The API catalogue, as an administrator maintains it."},
    {"name": "partners", "description": "Partner organizations, their groups, credentials and signing keys."},
    {"name": "partner-users", "description": "The people inside a partner organization, and their roles."},
    {
        "name": "keys",
        "description": "Security keys. A key is shown once at creation; only its hash is stored.",
    },
    {
        "name": "products",
        "description": "API products: an ordered journey through several APIs, assigned to partners.",
    },
    {"name": "content", "description": "Developer-portal pages, with draft and published versions."},
    {"name": "dashboard", "description": "Counts, recent traffic, the audit trail and the error log."},
    {"name": "usage", "description": "Traffic reports and call logs, from what the gateways have ingested."},
    {"name": "ingest", "description": "Written to by the gateways, not by a portal."},
    {
        "name": "partner-portal",
        "description": "What a signed-in partner sees. Scoped to their own organization throughout.",
    },
    {"name": "health", "description": "Liveness probe. Same path and shape as Spring Actuator's."},
    {
        "name": "crypto",
        "description": (
            "The public key the portals encrypt payloads to. **backend-java serves the same key** — "
            "nginx may route a request to either service, so both hold one keypair."
        ),
    },
]

DESCRIPTION = """
The control plane behind the management portal and the developer portal.

### Trying a call from this page

1. `POST /api/auth/captcha` — returns a `challengeId` and a PNG to read.
2. `POST /api/auth/otp/request` with the email address, the `challengeId` and the CAPTCHA answer.
   Where no mail server is reachable the response carries `devCode`, so a developer machine needs no
   mailbox.
3. `POST /api/auth/otp/verify` — returns `token`.
4. Press **Authorize**, paste the token, and every other operation is callable.

### Conventions

**Errors** are RFC 9457 problem documents sent as `application/problem+json`, never a bare string.
Portals switch on `code`; `fields` carries a message per invalid input; a 5xx carries a `reference`
that finds the entry in the error log.

**Timestamps** are ISO-8601 instants with a `Z` offset, rendered to match Java's `Instant.toString()`
exactly — 0, 3 or 6 fractional digits, never padded. The portals compare these as strings.

**Secrets are returned once.** A generated key, a private key and an IPV salt appear in the response
that creates them and never again; only a hash or an encrypted form is stored.

### Payload encryption

The portals encrypt every request body and receive every response encrypted, on top of TLS. Per
request they generate an AES-256 key, wrap it with the platform's RSA public key
(`GET /api/crypto/public-key`) and send it in `X-Encrypt-Key`; bodies and replies are AES-256-GCM
under that key, as `{"iv": ..., "data": ...}`. Error bodies are encrypted too, so a validation
failure's `fields` does not travel in the clear. Query strings are not encrypted.

**On a developer machine this is optional** — a request without the headers is answered in plaintext,
which is what keeps this page's Try-it-out, `curl` and the test harness usable. A production
deployment refuses unencrypted `/api` requests.

### Two services, one contract

Routes are moving from `backend-java` to this service one at a time, and nginx decides per method and
path which one answers. Both read the same database and honour the same tokens, so this document
describes the contract rather than the implementation.
""".strip()


def _schema_components() -> dict[str, Any]:
    """Every model in `schemas.py`, as OpenAPI component schemas sharing one set of refs."""
    models = [
        value
        for value in vars(s).values()
        if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel
    ]
    _, generated = models_json_schema(
        [(model, "serialization") for model in models],
        ref_template="#/components/schemas/{model}",
    )
    return generated.get("$defs", {})


def _ref(model: Any) -> dict[str, Any]:
    if isinstance(model, list):
        return {"type": "array", "items": {"$ref": f"#/components/schemas/{model[0].__name__}"}}
    return {"$ref": f"#/components/schemas/{model.__name__}"}


def _problem(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}},
    }


def _success_code(operation: dict[str, Any], model: Any) -> str:
    """Which status the route actually answers with.

    The Java service is not uniform about this — some creates answer 201, some 200, deletes answer
    204 — and each route was read rather than assumed when it was ported. FastAPI already recorded
    the right one from `status_code`, so take it from the generated document instead of guessing.
    """
    declared = [code for code in operation.get("responses", {}) if code.startswith("2")]
    if declared:
        return declared[0]
    return "204" if model is None else "200"


def build(app: FastAPI) -> dict[str, Any]:
    document = get_openapi(
        title=app.title,
        version=app.version,
        description=DESCRIPTION,
        routes=app.routes,
        tags=TAGS,
    )

    components = document.setdefault("components", {})
    components.setdefault("schemas", {}).update(_schema_components())
    components["securitySchemes"] = {
        BEARER: {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "The `token` from `POST /api/auth/otp/verify`. Paste it alone — Swagger UI adds the "
                "`Bearer ` prefix."
            ),
        },
        INGEST: {
            "type": "apiKey",
            "in": "header",
            "name": "X-Ingest-Token",
            "description": "The shared token the gateways present. Not a session, and not a user.",
        },
    }

    undocumented: list[str] = []
    for path, operations in document.get("paths", {}).items():
        for method, operation in operations.items():
            key = (method.lower(), path)

            if key in INGEST_ROUTES:
                operation["security"] = [{INGEST: []}]
            elif key not in PUBLIC:
                operation["security"] = [{BEARER: []}]

            responses = operation.setdefault("responses", {})
            if key in RESPONSES:
                model = RESPONSES[key]
                code = _success_code(operation, model)
                if model is None:
                    responses[code] = {"description": "Done. No body."}
                else:
                    existing = responses.get(code, {}).get("description")
                    responses[code] = {
                        "description": existing or "Successful response",
                        "content": {"application/json": {"schema": _ref(model)}},
                    }
            else:
                undocumented.append(f"{method.upper()} {path}")

            # FastAPI's own 422 entry is wrong for this service: the handler in main.py turns a
            # validation failure into a 400 problem document, to answer as backend-java does.
            responses.pop("422", None)
            if key not in PUBLIC:
                responses["401"] = _problem("No token, or one that has expired")
                responses["403"] = _problem("Signed in, but not permitted to do this")
            if "{" in path:
                responses["404"] = _problem("No such record")
            if method.lower() in ("post", "put"):
                responses["400"] = _problem("A field is missing or invalid; see `fields`")
                responses["409"] = _problem("A name, path or Client ID is already in use")
            responses["500"] = _problem("Unexpected failure; `reference` finds it in the error log")

    if undocumented:  # pragma: no cover - a route nobody has described yet
        document["info"]["x-undocumented-operations"] = sorted(undocumented)

    return document


def install(app: FastAPI) -> None:
    """Replace `app.openapi` with the enriched document, generated once and cached."""
    cached: dict[str, Any] = {}

    def openapi() -> dict[str, Any]:
        if not cached:
            cached.update(build(app))
        return cached

    app.openapi = openapi  # type: ignore[method-assign]
