# Change history

Every change to the platform, newest first. Each entry says what changed, why, and anything you must do
after pulling it (a migration runs itself, but configuration and restarts do not).

Database changes are Flyway migrations in `backend/src/main/resources/db/migration/`; they run at startup,
in order, and are recorded in `apim.flyway_schema_history`. The one-time PostgreSQL setup script is
`infra/postgres/local-setup.sql`.

## 2026-09-29

### The container stack now uses your own PostgreSQL, not a database of its own

The bundled PostgreSQL container was a second, empty database with its own seeded demo data, which
meant the containerised portals showed different records from the ones you had been working on.

- `DB_HOST`, `DB_PORT` and `DB_SCHEMA` in `infra/.env` decide which database the stack talks to. The
  defaults are now `host.docker.internal:5432` and schema `apim` — the developer machine's own
  server. Both control planes read the same three settings, so they cannot drift apart.
- The bundled `postgres` service moved behind its own `bundled-db` profile and no longer starts:
  `docker compose --profile app --profile bundled-db up -d`, with `DB_HOST=postgres` and
  `DB_SCHEMA=public`, brings it back for a machine that has no PostgreSQL.
- The schema is named through `SPRING_FLYWAY_SCHEMAS` and Hibernate's `default_schema` rather than by
  activating the `local` profile, which would also switch on header-based dev authentication and
  switch off gateway sync — neither of which belongs in a container.
- **`CRYPTO_MASTER_KEY` is deliberately empty.** The IPV salts already in that database were encrypted
  with the built-in development key, because `backend-java` sets no master key; a different key
  cannot decrypt them. Setting a real one means re-encrypting the existing salts first. Until then
  those secrets are protected only by a key that is published in the source.
- Verified on the real database: Flyway validated all 7 migrations and changed nothing, the demo
  seeder skipped a populated schema, and both control planes serve the real partners and users.
- Recreating a backend container gives nginx a new IP that it does not re-resolve, so a `502` after
  `up -d --force-recreate` is stale DNS, not a broken backend. `docker compose restart nginx` clears it.

## 2026-09-28

### The whole platform in Docker, behind one nginx with TLS

Verified end to end: thirteen containers, both portals served over TLS, and the same session token
accepted by both control planes through nginx.

The stack answers on **`apigw.com`** names: `admin.`, `developer.`, `api.` and `sandbox-api.`.

`apigw.com` is a registered domain that belongs to someone else, so these names only reach the local
stack because the hosts file says so. Every one of them needs its own line — a hosts file has no
wildcards, and a missing line silently reaches the real internet instead of failing:

```
127.0.0.1  apigw.com
127.0.0.1  admin.apigw.com
127.0.0.1  developer.apigw.com
127.0.0.1  api.apigw.com
127.0.0.1  sandbox-api.apigw.com
```

- **`infra/nginx/make-certs.sh`** creates a local certificate authority and one certificate covering
  `apigw.com`, `admin.`, `developer.`, `api.`, `sandbox-api.` and `127.0.0.1`. Output goes to
  `infra/docker/certs/`, which is git-ignored — it holds a private key that can sign any name, so
  trust the CA while you need it and delete it afterwards. Handles two Windows quirks: a machine-wide
  `OPENSSL_CONF` left behind by PostgreSQL's ODBC driver, and Git Bash rewriting the `/C=IN/...`
  subject into a filesystem path.
- **One nginx terminates TLS** and routes by hostname; it is the only service publishing a port.
  Plain HTTP is redirected, and an unknown name gets a closed connection rather than a portal.
- **A service per container**: `backend-java`, `backend-node`, `management-portal`,
  `developer-portal`, `nginx`, alongside the existing PostgreSQL, Valkey, etcd, two APISIX
  deployments, Keycloak and the WireMock stand-ins.
- **nginx is the migration switch.** `/api/admin/usage/*` and `/api/admin/audit` already go to the
  Node service; everything else goes to Java. Moving an endpoint between backends is one line here,
  with no change to either portal.
- `AUTH_JWT_SECRET` is now **required** for the app profile and shared by both control planes — that
  is what lets one session work against either.
- `backend-node` waits for `backend-java` to report healthy, because Flyway runs there and owns the
  schema. The Java image gained `curl` so that health check works.
- Portals build from the repository root (npm workspaces share `packages/ui`) and are served by nginx
  with an SPA fallback, so refreshing a deep link no longer 404s.
- The container PostgreSQL publishes **55432**, because a developer machine usually already has
  PostgreSQL on 5432. It is a separate, empty database — not the one the host services use.

Four things had to be fixed to get the first run green, all worth knowing if you build elsewhere:

- The portal image never copied `tsconfig.base.json`, so `extends` resolved to nothing, `jsx` was
  lost and the shared `.tsx` components failed with TS6142 — while building fine on a developer
  machine, where the file is simply there.
- `npm prune --omit=dev` deletes `node_modules/.prisma` along with the dev packages, leaving the Node
  service without a query engine. The prune step is gone; `binaryTargets` now names the container's
  platform explicitly.
- The Node service's raw SQL no longer names a schema. Which schema holds the tables is a deployment
  choice — `apim` under the Java service's `local` profile, `public` by default — and Prisma sets the
  search_path from `?schema=` in `DATABASE_URL`. `DB_SCHEMA` selects it for the container.
- `CRYPTO_MASTER_KEY` must be **standard** base64. The URL-safe alphabet (`-`, `_`) is rejected by
  the cipher at startup with `Illegal base64 character 2d`.

### Backend migration to Node begins — `backend/` is now `backend-java/`

Work happens on the `node-migration` branch; `main` is untouched until the port is proven.

- **`backend/` is renamed `backend-java/`.** Nothing inside it changed. The Java service stays the
  system of record and stays runnable, so the decision is reversible at any point. Documentation, the
  PostgreSQL setup script and `.gitignore` follow the new path; if you have a local checkout, your
  `backend/config/` moved with it and needs no edits.
- **New `backend-node/`: NestJS 11 on Fastify, Prisma 6, TypeScript 5.9.** It runs against the *same*
  database and the *same* signing secret as the Java service, on port 8089.
- **The schema stays Flyway's.** Prisma is introspection-only (`npm run db:pull`); `prisma migrate` is
  never run, because two tools writing DDL to one database is how environments drift apart.
- **Tokens are interchangeable.** The Node service verifies exactly what `TokenService` mints — HS256,
  issuer `apigw-platform`, roles under `realm_access.roles`, a partner's organization as
  `groups: ["/partners/<CODE>"]`. One portal session works against either backend, which is what makes
  a gradual cutover possible. Both must share `AUTH_JWT_SECRET`.
- **First endpoints ported**, read-only and verified against live data: `/api/admin/usage/report`,
  `/api/admin/usage/logs`, `/api/admin/usage/apis/{id}/consumers`, `/api/admin/audit` and
  `/actuator/health` (same shape as Actuator's, so probes do not care which backend answers).
  Window defaults, the 30-day retention clamp and the `INVALID_RANGE` error match the Java service.
- Copy `backend-node/.env.example` to `backend-node/.env` and fill it in before running.

### Security keys: Partner Admin only, confirmed before, announced after

Rotating a key breaks every live integration that has not switched over, so it is now a deliberate act with
witnesses.

- **Only a Partner Admin may create or rotate a key in the Developer Portal.** Anyone else gets
  `403 NOT_PARTNER_ADMIN` and is told who can do it. `/api/partner/me` now returns `role` and
  `canGenerateKeys`, so the portal disables the button and explains why rather than failing the click.
  APIM Admins can still rotate on a partner's behalf from the Management Portal.
- **Both portals ask first.** The dialog states that the current key keeps working for the configured grace
  period (20 minutes) and then stops, and that the rotation will be e-mailed and notified. Cancel does
  nothing at all — no key is created.
- **Three notices go out once the key is committed**, whoever rotated it:
  1. the new key, to the organization's Partner Admins (`Your new <env> security key`);
  2. a change notice to *every* active portal user of that organization, Partner Admins included, which
     does **not** contain the key and says to contact the APIM Admin team immediately if it was not them;
  3. an alert to every active APIM Admin naming the partner, the environment and who did it.
- Notices are sent after the transaction commits, so a rotation that failed never announces itself, and a
  mail failure never rolls back a key that has already been issued (it lands in the error log instead).
- New setting `apigw.keys.email-key-to-admin` (default `true`). Set it to `false` to send the change notice
  without the key itself, if your policy is that a live credential must never travel by e-mail.

### Developer Portal: the partner's own dashboard

- New landing page for partners: calls, errors, success rate and average latency over the last hour, 24 hours,
  7 or 30 days, with a per-API breakdown and the 25 most recent calls. Scoped to the partner's own Client IDs,
  taken from the token, so one organization never sees another's traffic.
- `/api/partner/dashboard` and `/api/partner/usage/logs` (the partner's own call history, filtered like the
  Management Portal's).
- **Empty means zero, not blank.** Both dashboards show 0 for every figure when there is no traffic, with a
  line explaining why rather than an empty table.
- Fixed: the new endpoint read the wall clock instead of the application's `Clock`, so the window start
  disagreed with the rest of the service and every request failed with `INVALID_RANGE`.

### Developer Portal: Sandbox menu removed

- The standalone Sandbox entry is gone from the partner menu. Sandbox testing happens on each API's own page
  through *Try it live*, so a separate console was a dead end. `/sandbox` redirects to the catalogue, so an
  old bookmark still lands somewhere sensible.
- Menu is now: My APIs · Security keys · Guides.

### Products as API journeys (CP-API-09) and Developer Portal content (CP-API-10) — backend

- **Products.** A Product is a journey: the ordered set of APIs a partner calls to complete one business
  outcome. Each step carries a note and an optional dependency on an earlier step ("confirm needs the txnId
  that initiate returns"), plus a flow document (Markdown) explaining how the APIs fit together.
- **Assignment.** A Product is assigned to an organization, or to named users inside it. Partners see only
  the Products assigned to them, and only once published. Visibility is not permission — what a partner may
  call is still decided by their security key at the gateway.
- **Portal pages.** Onboarding guides, FAQs and terms of use are written in the Management Portal and
  published when ready. Editing a live page saves a new version without changing what partners see; every
  version is kept, with who wrote it and when.
- New endpoints: `/api/admin/products`, `/api/admin/pages`, `/api/partner/products`, `/api/partner/pages`.
- Migration **V7**: `product`, `product_step`, `product_assignment`, `portal_page`, `portal_page_version`.
- Tests: 8 new (59 total).

## 2026-09-27

### Dashboard and API logs (CP-RPT-01, CP-RPT-02)

- **Dashboard** replaces the placeholder landing page: APIs by status, partners, Production partners and
  portal users, plus the last hour of traffic — calls, errors, success rate, average latency — with the
  busiest APIs and partners. Refreshes every 30 seconds.
- **API logs**: every call the gateways reported, newest first, filtered by time window, status bucket
  (success / 4xx / 5xx), API name or path, and the partner that called. Calls are attributed to the
  partner's Client ID, which is what the gateway authenticates; portal actions remain in the audit log.

### Partner user deletion

- A portal login can be deleted once its access has been revoked (`409 ACCESS_NOT_REVOKED` otherwise).
  The audit trail of what that user did stays behind.

### Error handling

- A missing endpoint now answers `404 ENDPOINT_NOT_FOUND` and a wrong verb `405 METHOD_NOT_ALLOWED`, both
  explaining that the backend may be running an older build. Neither is recorded as a defect, so path
  scanning cannot fill the error log.
- Fixed: the OTP cleanup job called its own `@Transactional` method, so the proxy never applied and the
  hourly purge failed every time. The error log caught this within minutes of being switched on.

### System error log (CP-LOG-05)

- Operational failures are written to the database and read in the portal: rejected sign-in e-mails,
  unanswered gateway admin calls, background jobs that threw, and unhandled requests. Each row holds the
  stack trace and a reference shown to the caller, so a support report maps to a row.
- Recording runs in its own transaction (the failure usually just rolled one back) and never throws.
- Migration **V6**: `error_event`. Kept 30 days (`apigw.errors.retention`); audit rows are never purged.

### Gmail SMTP

- Sign-in codes are sent over SMTP; settings live in `backend/config/application.yml` (git-ignored) so they
  apply to every profile. A Google App Password pasted with the spaces Google displays is accepted.
- A rejected send no longer locks anyone out: outside production the code is shown in the portal and the
  reason logged. Under `prod` the failure is raised instead.
- Tests never reach a mail server (`spring.mail.host` is cleared for the suite).

## 2026-09-26

### Sign-in by e-mail OTP with CAPTCHA (CP-LOG-01, DP-01)

- Both portals sign in with a CAPTCHA drawn by the platform, then a six-digit code e-mailed to the address.
  No passwords are stored anywhere; Keycloak is no longer used for portal sign-in.
- Codes last five minutes, work once, allow five wrong guesses, and are rate-limited per address with a
  resend cooldown. Sessions are HS256 tokens the platform signs and verifies itself.
- Unregistered addresses are told so (`apigw.auth.reveal-unknown-email`, on by default). Set it to `false`
  for an internet-facing portal so accounts cannot be discovered from the sign-in screen.
- The first Management Portal account is created at startup from `BOOTSTRAP_ADMIN` when none exists.
- Migration **V5**: `platform_user`, `otp_challenge`.

### Organization-based partner registration

- Registration is per organization. Its name and contact address can be corrected afterwards.
- The signature key pair and IPV salt moved from the portal user to the organization, alongside its security
  keys and Client IDs, so several users share one set of credentials and adding a user never disturbs an
  integration. Both can be re-issued by an Admin.
- Partner users are logins: as many per organization as needed, each with their own correctable e-mail.
- Migration **V4**: organization credentials, carrying over each organization's first user's material.

## 2026-09-24

### Partner users and organization credentials (CP-PTN-04)

- Developer Portal logins managed in the Management Portal, with access granted or revoked per user.
- RSA-2048 signature key pair (private key shown once, never stored) and a 256-bit IPV salt (encrypted with
  AES-256-GCM, revealable by an Admin, every reveal audited).
- Migration **V3**: `partner_user`.

### Local PostgreSQL

- `infra/postgres/local-setup.sql` creates the role, database and schema `apim`; the `local` profile points
  the backend at it. Data survives restarts, unlike the in-memory `h2` profile.

## 2026-09-19

### API documentation, Swagger/Postman import and Try it live (CP-API-06, CP-API-07, DP-02, DP-03)

- The Add/Edit API page documents the full contract: query parameters, request headers, body fields with a
  JSON example, and a response body per HTTP status code.
- Import from Swagger 2 / OpenAPI 3 (JSON or YAML) or a Postman v2.x collection — one operation into the
  form, or many at once as drafts.
- The Developer Portal shows the contract with a cURL sample and a *Try it live* panel that calls the
  Sandbox with the partner's own key. Production is never callable from the portal.
- Migration **V2**: `api_definition.documentation`.

## 2026-09-14

### Initial vertical slice

- API inventory, partner groups and partners, security keys with the 20-minute rotation overlap, usage
  reporting, audit log, and both portals.
- Migration **V1**: baseline schema.
