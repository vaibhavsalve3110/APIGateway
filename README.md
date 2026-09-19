# API Gateway Platform

Management Portal, Developer Portal and gateway configuration for the platform specified in
`../ProjectDocs/BRD_API_Gateway_Developer_Portal_v1.3.docx`, built from the screen designs in `../design`.

| Folder | What it is |
|---|---|
| `backend/` | Spring Boot 4.1 (Java 21) control plane — APIs, partners, security keys, usage, audit |
| `frontend/apps/management-portal` | Internal portal for Admin / Editor users (React 19, TypeScript, Vite) |
| `frontend/apps/developer-portal` | Partner-facing portal |
| `frontend/packages/ui` | Shared design tokens, components, API client and sign-in |
| `infra/` | Docker Compose: two APISIX gateways, etcd, Valkey, PostgreSQL, Keycloak, mock core APIs |
| `docs/` | [Architecture](docs/architecture.md), [ER diagram](docs/database/er-diagram.md), [BRD traceability](docs/brd-traceability.md) |

## What works today

The first vertical slice, with BRD v1.3 key rules end to end:

- **API inventory:** add, edit, disable and enable APIs; a guest-visibility flag that defaults to off; per-API rate limits; and deletion blocked until the API has been disabled for 7 days.
- **Partner groups and partners:** UAT-only or Production access tier, one Client ID per environment, and disabling a partner revokes its keys.
- **Security keys:**
  - shown once and stored only as a SHA-256 hash
  - a new key starts a 20-minute overlap window; the old key then expires automatically
  - no third key can be created while a window is open
  - an Admin can revoke the new key while the window is still open
  - Production keys are refused for UAT-only partners
- **Usage report:** success and failure counts plus min/max/average latency per API, over a 15-minute default window, filterable by Client ID, with 30-day retention.
- **Audit log** for every configuration and key action.
- **API documentation:** the Add / Edit API page documents the full contract:
  - query parameters, request headers, request body fields and a JSON example, with *Generate fields from example*
  - a response body for each HTTP status code, plus response headers
  - or import it: **Swagger 2 / OpenAPI 3** (JSON or YAML) or a **Postman v2.x collection**. Load one operation
    into the form, or import many at once as drafts that stay off the gateways until enabled.
- **Developer Portal:** API catalogue; clicking an API opens its page with the full contract, a cURL sample and a
  **Try it live** panel that calls the Sandbox with the partner's own key (never Production). Key management is scoped
  to the partner's own account.

See [docs/brd-traceability.md](docs/brd-traceability.md) for every requirement's status and what is planned next.

## Run it without Docker (quickest)

Needs Java 21+, Maven 3.9+ and Node 20+.

```bash
cd backend
mvn spring-boot:run -Dspring-boot.run.profiles=h2,demo
```

This uses an in-memory database, seeds demo data, signs in through dev headers and does not sync to a gateway.
With no gateway running, *Try it live* runs in `SIMULATE` mode: it still checks the partner's key, then answers from
the documented examples and says so on screen. With the full stack, set `TRY_IT_MODE=GATEWAY` (the default) so calls go
through the Sandbox APISIX.
Then, in two more terminals:

```bash
cd frontend && npm install && npm run dev:admin     # http://localhost:5173
cd frontend && npm run dev:partner                  # http://localhost:5174
```

Pick an identity on the sign-in screen: Admin or Editor in the Management Portal; Acme Fintech (UAT-only) or
Kavery Payments (Production) in the Developer Portal.

## Run the full stack

Needs a container runtime. Docker Engine on Linux/WSL2, Rancher Desktop and Podman are free.
**Docker Desktop requires a paid subscription** in organisations over 250 staff or $10M revenue.

```bash
cd infra && cp .env.example .env && docker compose up -d
cd ../backend && mvn spring-boot:run -Dspring-boot.run.profiles=demo
cd ../frontend && cp apps/management-portal/.env.example apps/management-portal/.env.local   # set VITE_AUTH_MODE=oidc
```

| Service | URL | Sign-in |
|---|---|---|
| Management Portal | http://localhost:5173 | `vaibhav.admin` / `Admin@12345`, `ravi.editor` / `Editor@12345` |
| Developer Portal | http://localhost:5174 | `acme.dev` / `Partner@12345`, `kavery.dev` / `Partner@12345` |
| Backend API + Swagger UI | http://localhost:8088/swagger-ui.html | |
| Keycloak admin | http://localhost:8180 | `admin` / `admin` |
| Sandbox gateway | http://localhost:9080 (host `sandbox-api.apigw.localhost`) | partner key |
| Production gateway | http://localhost:9081 (host `api.apigw.localhost`) | partner key |

The backend listens on **8088**, because 8080 is commonly taken (on this machine, by an Apache `httpd` service).

### Gateway smoke test

After generating a Sandbox key for Acme in the Developer Portal:

```bash
curl -i http://localhost:9080/v1/accounts/balance -H "Host: sandbox-api.apigw.localhost" -H "X-Security-Key: agw_sbx_…"
```

- **200** from the mock backend, with `X-RateLimit-Remaining` headers.
- Without the key → **401**.
- The same key against the Production gateway on :9081 → **401**, because the credential doesn't exist there.

## Tests

```bash
cd backend && mvn test          # 30 tests: key lifecycle, cooling period, RBAC, usage, gateway payloads, documentation, import, try-it
cd frontend && npm test         # 11 tests: formatting, error handling, field inference, path parameters
cd frontend && npm run typecheck && npm run build
```
