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
- **Sign-in (both portals):** a CAPTCHA drawn by the platform, then a six-digit code e-mailed to the address given. No
  passwords are stored anywhere. Codes last five minutes, work once, and are rate-limited per address; an unknown
  address gets the same answer as a known one, so accounts cannot be enumerated.
- **Organizations (partners):** registered once, with their name and contact address correctable afterwards. Each
  organization is issued, and can be re-issued at any time:
  - an **RSA-2048 signature key pair** — the private key is shown once and never stored, only the public key and its
    fingerprint are kept
  - a 256-bit **IPV salt** — stored encrypted (AES-256-GCM) because both sides need it, revealable by an Admin
- **Partner users:** as many Developer Portal logins per organization as needed, each with their own e-mail (their
  sign-in address, correctable), name and role, and access that can be granted or revoked per user. A login can be
  deleted once its access has been revoked — deliberately a second step, as with deleting an API. They share the
  organization's credentials and security keys, which deletion never touches.

  Every issue, recreation, reveal, sign-in and access change is audited.
- **Security keys:**
  - shown once and stored only as a SHA-256 hash
  - a new key starts a 20-minute overlap window; the old key then expires automatically
  - no third key can be created while a window is open
  - an Admin can revoke the new key while the window is still open
  - Production keys are refused for UAT-only partners
- **Dashboard:** how much is configured (APIs by status, partners, Production partners, portal users) and what the
  gateways did in the last hour — calls, errors, success rate, average latency — with the busiest APIs and
  partners. Refreshes every 30 seconds; each tile links to the page behind it.
- **API logs:** every call the gateways reported, newest first, filtered by time window, status bucket
  (success / 4xx / 5xx), API name or path, and the partner that called. Kept for 30 days.
- **Usage report:** success and failure counts plus min/max/average latency per API, over a 15-minute default window, filterable by Client ID, with 30-day retention.
- **Audit log** for every configuration and key action.
- **System errors:** failures are written to the database and read in the portal — rejected sign-in e-mails,
  gateway admin calls that did not answer, background jobs that threw, and any unhandled request. Each row
  carries the stack trace and a reference the caller is shown, so a report can be matched to a row. Kept 30 days.
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

This uses an in-memory database, seeds demo data and does not sync to a gateway.
With no gateway running, *Try it live* runs in `SIMULATE` mode: it still checks the partner's key, then answers from
the documented examples and says so on screen. With the full stack, set `TRY_IT_MODE=GATEWAY` (the default) so calls go
through the Sandbox APISIX.
Then, in two more terminals:

```bash
cd frontend && npm install && npm run dev:admin     # http://localhost:5173
cd frontend && npm run dev:partner                  # http://localhost:5175
```

Sign in with one of the seeded addresses: `vaibhav.admin@apigw.local` or `ravi.editor@apigw.local` in the Management
Portal, `priya.nair@acmefintech.in` (Acme, UAT-only) or `anita.rao@kaverypayments.in` (Kavery, Production) in the
Developer Portal. With no SMTP server configured the one-time code is written to the backend log **and shown on the
sign-in screen**, so the demo works end to end; set `SMTP_HOST` (and the rest of `spring.mail.*`) to send real mail.
On a database that already has data, the first Management Portal account is created at startup from
`BOOTSTRAP_ADMIN` (default `admin@apigw.local`).

## Run with a local PostgreSQL (no Docker)

Data persists across restarts. Tables live in schema `apim` of database `apigw`.

1. One-time setup, as the PostgreSQL superuser. It creates the role `apigw`, the database `apigw` and the schema `apim`
   (it does not set a password):
   ```bash
   "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -f infra/postgres/local-setup.sql
   ```
2. Give the role a password, in an **interactive** psql as `postgres` — `\password` is silently skipped when psql runs a file:
   ```sql
   ALTER ROLE apigw WITH PASSWORD 'your-password';
   ```
3. Copy `backend/config.example/application-local.yml` to `backend/config/application-local.yml` (git-ignored) and put the same
   password in it, or set `DB_PASSWORD` instead. Spring reads `backend/config/` after the packaged settings, so that copy wins.
4. Start the backend. Flyway creates every table in `apim` (history in `apim.flyway_schema_history`), and the demo seed runs
   once, into the empty schema:
   ```bash
   cd backend
   mvn spring-boot:run -Dspring-boot.run.profiles=local,demo
   ```

The portals are started the same way as above.

## Run the full stack

Needs a container runtime. Docker Engine on Linux/WSL2, Rancher Desktop and Podman are free.
**Docker Desktop requires a paid subscription** in organisations over 250 staff or $10M revenue.

```bash
cd infra && cp .env.example .env && docker compose up -d
cd ../backend && mvn spring-boot:run -Dspring-boot.run.profiles=demo
cd ../frontend && npm run dev:admin
```

| Service | URL | Sign-in |
|---|---|---|
| Management Portal | http://localhost:5173 | `vaibhav.admin@apigw.local` or `ravi.editor@apigw.local` (one-time code) |
| Developer Portal | http://localhost:5175 | `priya.nair@acmefintech.in`, `rahul.shetty@acmefintech.in`, `anita.rao@kaverypayments.in` |
| Backend API + Swagger UI | http://localhost:8088/swagger-ui.html | |
| Keycloak admin | http://localhost:8180 | `admin` / `admin` — not used for portal sign-in; kept for the DP-06 token APIs |
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
cd backend && mvn test          # 50 tests: key lifecycle, cooling period, RBAC, usage, gateway payloads, documentation,
                                #           import, try-it, organization credentials, partner users, OTP sign-in, error log, dashboard, API logs
cd frontend && npm test         # 11 tests: formatting, error handling, field inference, path parameters
cd frontend && npm run typecheck && npm run build
```
