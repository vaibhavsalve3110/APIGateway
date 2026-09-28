# BRD traceability — v1.3

Status of each requirement in `ProjectDocs/BRD_API_Gateway_Developer_Portal_v1.3.docx` against this codebase.

**Done** = implemented and covered by an automated test or verified end to end · **Partial** = the core is in, a named
piece is outstanding · **Planned** = not started · ⚠ = implemented but not yet run against a live APISIX gateway.

## 5.1.1 Login

| ID | Status | Where / what is left |
|---|---|---|
| CP-LOG-01 Admin login | Done | CAPTCHA, then a one-time code e-mailed to the address; the platform holds no passwords. `OtpService`, `AuthController`, `OtpSignInTest` |
| CP-LOG-02 Manage internal users | Partial | Internal accounts live in `platform_user` (ADMIN / EDITOR, active or disabled) and the first one is created at startup; an in-portal screen to add the rest is still to come |
| CP-LOG-03 Editor login | Done | Same sign-in; role EDITOR reads APIs and usage |
| CP-LOG-04 Role-based access | Done | `SecurityConfig` URL rules; `ApiLifecycleTest.rolesAreEnforced` |
| CP-LOG-05 Audit trail | Done | Configuration, key and credential actions plus every sign-in, failed code and throttled request → `audit_event`. Operational failures go to `error_event` and are read in Management Portal › System Errors |

## 5.1.2 API management

| ID | Status | Where / what is left |
|---|---|---|
| CP-API-01 Add API | Done | `ApiService.create`, Management Portal › APIs › Add API (full-page editor) |
| CP-API-02 Update API | Done | `ApiService.update` |
| CP-API-03 Disable API | Done ⚠ | Removes the gateway routes immediately |
| CP-API-04 Delete API | Partial | Cooling-period guard done; "no active subscriptions" check needs access mapping |
| CP-API-05 Guest flag | Done | Defaults to No; `ApiLifecycleTest` |
| CP-API-06 Swagger import | Done | Swagger 2 / OpenAPI 3 (JSON, YAML) and Postman v2.x: `ImportService`, `POST /api/admin/apis/import`. Load one operation into the editor, or import many as drafts |
| CP-API-07 Manual documentation | Done | Editor tabs: Request (query parameters, request headers, body fields + JSON example) and Responses (one body per HTTP status code, response headers). Stored in `api_definition.documentation` (V2) |
| CP-API-08 Rate limit per API | Done ⚠ | `limit-count` per route, counted per Client ID |
| CP-API-09 Products | Planned | |
| CP-API-10 Portal content | Planned | |

## 5.1.3 Partner management

| ID | Status | Where / what is left |
|---|---|---|
| CP-PTN-01 Partner groups | Partial | Create and list; update / disable / delete to follow |
| CP-PTN-02 Partners | Partial | Add, disable / re-enable; edit and delete to follow |
| CP-PTN-03 Map Products/APIs | Planned | Catalogue currently lists every active API |
| CP-PTN-04 Portal account access | Done | Management Portal › Partner Users: several logins per organization, each with a correctable e-mail (their sign-in address), name and role; access granted or revoked per user, and a revoked user gets no further sign-in code. A revoked login can then be deleted (refused while access is still granted, `ACCESS_NOT_REVOKED`); the audit trail of what they did remains |
| CP-PTN-05 UAT-only tier | Done | Default tier; Production keys refused (`KeyLifecycleTest`) |
| CP-PTN-06 Production tier | Done | Issues a Production Client ID; withdrawing revokes Production keys |
| CP-PTN-07 Status visibility | Done | Partners list and detail |

## 5.1.4 Security keys (v1.3 rules)

| ID | Status | Where / what is left |
|---|---|---|
| CP-SEC-01 Guest key | Planned | |
| CP-SEC-02 Sandbox key | Done | |
| CP-SEC-03 Production key | Done | |
| CP-SEC-04 20-minute overlap | Done | `SecurityKeyService`, `KeyExpiryJob`; `KeyLifecycleTest` |
| CP-SEC-05 Regeneration, one window at a time | Done | `ROTATION_WINDOW_OPEN` |
| CP-SEC-06 Revoke new key in window | Done | Admin only; `REVOKE_WINDOW_CLOSED` after the window |
| CP-SEC-07 Key audit log | Done | Automatic expiry recorded as "System" |
| CP-SEC-08 One-time display | Done | Plaintext only in the generate response; `KeyLifecycleTest` |
| CP-SEC-09 Non-reversible storage | Done ⚠ | SHA-256 in the database; the gateway hashes the presented key before `key-auth` |

## 5.1.5 Usage reporting

| ID | Status | Where / what is left |
|---|---|---|
| CP-RPT-01 Success/failure & latency | Done | `UsageService.report`; `UsageReportTest`. Dashboard adds the last hour at a glance — calls, errors, success rate, average latency, busiest APIs and partners (`ApiLogsTest`) |
| CP-RPT-02 Filters, 15-minute default | Done | Usage report filters by date range and Client ID; API Logs lists individual calls filtered by time window, status bucket (success / 4xx / 5xx), API name or path, and partner |
| CP-RPT-03 30-day retention | Done | `UsageRetentionJob` (partition before go-live — see ER notes) |
| CP-RPT-04 Dependency view | Partial | API → consuming Client IDs from traffic; mapping-based view and UI to follow |
| CP-RPT-05 Delete cooling period | Done | 7 days, `apigw.apis.delete-cooling-period` |
| CP-RPT-06 Approval evidence | Planned | With access mapping |

## 5.1.6 Domains

| ID | Status | Where / what is left |
|---|---|---|
| CP-DOM-01 … 10 | Planned | Route `hosts` are configured per environment today; ER tables proposed |

## 5.2 Developer Portal

| ID | Status | Where / what is left |
|---|---|---|
| DP-01 Partner login | Done | Same OTP sign-in; the token carries `/partners/<code>`, so a partner sees only their own organization |
| DP-02 My APIs | Partial | Catalogue → API page with the full contract and a cURL sample. Lists all active APIs until access mapping exists |
| DP-03 Sandbox testing | Done | *Try it live* on each API page with the partner's own Sandbox key (checked against that partner): path, query, header and body inputs; shows status, latency, headers and body. Production is never callable. `TRY_IT_MODE=SIMULATE` answers from the documented examples when no gateway runs |
| DP-04 Key status | Done | Masked keys with overlap countdown |
| DP-05 Self-service regeneration | Done | Warning, then show-once dialog |
| DP-06 Token APIs | Planned | Machine-to-machine tokens per Client ID (Keycloak or in-house), separate from portal sign-in |
| DP-07 Encryption guide | Planned | |
| DP-08 Account scoping | Done | Partner derived from the token, never from the request |

## 5.3 API Gateway

| ID | Status | Where / what is left |
|---|---|---|
| GW-01 Reverse proxy | Done ⚠ | Route per API per environment |
| GW-02 Token check | Planned | Add `openid-connect` (JWKS) on routes, and check the token's Client ID matches the key's consumer |
| GW-03 Key & environment check | Done ⚠ | `key-auth` on hashed credentials; separate gateway per environment |
| GW-04 Rate limit per Client ID | Done ⚠ | `limit-count` keyed on consumer name, counters in Valkey |
| GW-05 Environment segregation | Done | Structural: sandbox credentials only exist on the Sandbox gateway |
| GW-06 Overlap-window validation | Done ⚠ | Old credential deleted at window end |
| GW-07 Standard errors | Partial | APISIX defaults; custom error bodies to follow |
| GW-08 Metadata logging | Done ⚠ | `http-logger` global rule, no payloads |
| GW-09 Multi-domain routing | Partial | Static hosts per environment; per-domain certificates with CP-DOM |

## Beyond BRD v1.3

Built on request, not yet written into the BRD — add them at the next revision:

| What | Where | Note |
|---|---|---|
| Organization signature key pair | `partner.signature_public_key` | RSA-2048/SHA-256 per organization, issued at registration and shared by its users. The private key is returned once and never stored, matching the security-key rule (CP-SEC-08/09). An Admin can recreate the pair; the previous public key stops being accepted immediately, with no overlap window. |
| Organization IPV salt | `partner.ipv_salt_cipher` | 256-bit salt for the organization's payload encryption. Both sides need the value, so it is stored encrypted (AES-256-GCM, `apigw.crypto.master-key`) rather than hashed, and can be revealed again by an Admin — which is audited. |
| System error log | `errors/` package, `error_event` | Failures recorded in the database with their stack trace and a reference shown to the caller: SMTP rejections, gateway admin calls, scheduled jobs and unhandled requests. Written in its own transaction, so a rollback cannot take the record away, and never throws — a failing log must not hide the failure it describes. |
| E-mail OTP sign-in with CAPTCHA | `auth/` package, `otp_challenge` | Replaces passwords for both portals: a self-hosted CAPTCHA, a six-digit code valid for five minutes and usable once, five wrong guesses per code, a resend cooldown and a rolling per-address cap. Whether an address exists is never revealed. Sessions are HS256 tokens signed by the platform (`apigw.auth.jwt-secret`). |
| Secret encryption at rest | `crypto/SecretCipher` | Master key from `CRYPTO_MASTER_KEY`; required under the `prod` profile, with a development fallback that logs a warning elsewhere. |
