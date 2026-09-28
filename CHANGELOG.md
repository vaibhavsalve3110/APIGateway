# Change history

Every change to the platform, newest first. Each entry says what changed, why, and anything you must do
after pulling it (a migration runs itself, but configuration and restarts do not).

Database changes are Flyway migrations in `backend/src/main/resources/db/migration/`; they run at startup,
in order, and are recorded in `apim.flyway_schema_history`. The one-time PostgreSQL setup script is
`infra/postgres/local-setup.sql`.

## 2026-09-28

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
