# BRD traceability — v1.3

Status of each requirement in `ProjectDocs/BRD_API_Gateway_Developer_Portal_v1.3.docx` against this codebase.

**Done** = implemented and covered by an automated test or verified end to end · **Partial** = the core is in, a named
piece is outstanding · **Planned** = not started · ⚠ = implemented but not yet run against a live APISIX gateway.

## 5.1.1 Login

| ID | Status | Where / what is left |
|---|---|---|
| CP-LOG-01 Admin login | Done | Keycloak realm role `ADMIN`; `SecurityConfig` |
| CP-LOG-02 Manage internal users | Planned | Keycloak admin console for now; in-portal user screen to follow |
| CP-LOG-03 Editor login | Done | Realm role `EDITOR` — read APIs and usage |
| CP-LOG-04 Role-based access | Done | `SecurityConfig` URL rules; `ApiLifecycleTest.rolesAreEnforced` |
| CP-LOG-05 Audit trail | Partial | All configuration and key actions → `audit_event`. Login attempts: enable Keycloak login events |

## 5.1.2 API management

| ID | Status | Where / what is left |
|---|---|---|
| CP-API-01 Add API | Done | `ApiService.create`, Management Portal › APIs |
| CP-API-02 Update API | Done | `ApiService.update` |
| CP-API-03 Disable API | Done ⚠ | Removes the gateway routes immediately |
| CP-API-04 Delete API | Partial | Cooling-period guard done; "no active subscriptions" check needs access mapping |
| CP-API-05 Guest flag | Done | Defaults to No; `ApiLifecycleTest` |
| CP-API-06 Swagger import | Planned | |
| CP-API-07 Manual documentation | Planned | Tables proposed in the ER diagram |
| CP-API-08 Rate limit per API | Done ⚠ | `limit-count` per route, counted per Client ID |
| CP-API-09 Products | Planned | |
| CP-API-10 Portal content | Planned | |

## 5.1.3 Partner management

| ID | Status | Where / what is left |
|---|---|---|
| CP-PTN-01 Partner groups | Partial | Create and list; update / disable / delete to follow |
| CP-PTN-02 Partners | Partial | Add, disable / re-enable; edit and delete to follow |
| CP-PTN-03 Map Products/APIs | Planned | Catalogue currently lists every active API |
| CP-PTN-04 Portal account access | Partial | Disabling a partner revokes all keys; portal users live in Keycloak |
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
| CP-RPT-01 Success/failure & latency | Done | `UsageService.report`; `UsageReportTest` |
| CP-RPT-02 Filters, 15-minute default | Partial | Date range and Client ID done; API-name filter to follow |
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
| DP-01 Partner login | Done | Keycloak group `/partners/<code>` → partner scope |
| DP-02 My APIs | Partial | Lists active APIs until mapping exists; full documentation to follow |
| DP-03 Sandbox testing | Planned | |
| DP-04 Key status | Done | Masked keys with overlap countdown |
| DP-05 Self-service regeneration | Done | Warning, then show-once dialog |
| DP-06 Token APIs | Planned | Keycloak client-credentials clients per partner |
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
