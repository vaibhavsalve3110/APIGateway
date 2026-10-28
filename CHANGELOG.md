# Change history

Every change to the platform, newest first. Each entry says what changed, why, and anything you must do
after pulling it (a migration runs itself, but configuration and restarts do not).

Database changes are Flyway migrations in `backend/src/main/resources/db/migration/`; they run at startup,
in order, and are recorded in `apim.flyway_schema_history`. The one-time PostgreSQL setup script is
`infra/postgres/local-setup.sql`.

## 2026-10-28

### backend-java is retired

Everything it still owned is in `backend-python`, and it no longer starts with the stack. nginx
routes nothing to it, its port is not listening, and the platform serves every screen without it —
22 of 22 sanity checks and every admin route answering 200 with the service stopped.

| What moved | Where it is now |
| --- | --- |
| Flyway and the nine migrations | `app/migrations.py`, files in `backend-python/migrations/` |
| Key expiry, sign-in code cleanup, error-log retention | `app/jobs.py` |
| Try it live | `app/routers/try_it.py` |
| Swagger / OpenAPI and Postman import | `app/importer.py` |
| Demo seeder | `app/demo_seed.py` |

**It is kept on its own compose profile rather than deleted**, because twelve gates cross-check
`backend-python` against it and those comparisons have caught real defects all the way through this
port — including, this week, a Try-it-live URL that could never have worked and an importer whose
examples differed by a space. Removing 95 assertions is a separate decision with a real cost, so the
service stays startable for testing and absent from everything else:

```
docker compose --profile app --profile java up -d     # only to run the parity gates
```

Three improvements over what Java did, rather than like-for-like ports:

- **The scheduled jobs take an advisory lock.** Java had no guard at all, so two replicas would have
  expired every key twice and purged the error log from two transactions at once — and the
  production sizing calls for two control-plane nodes.
- **Key expiry withdraws the credential inside the transaction.** Committing first and failing to
  withdraw leaves the platform believing a key is dead while the gateway still honours it. The other
  way round costs a partner a few minutes of a key that was about to expire, and the next tick puts
  the record right.
- **The importer resolves `$ref` locally only and parses YAML with `safe_load`.** A specification
  pointing at `http://169.254.169.254/...` would otherwise have the platform fetch a URL of the
  uploader's choosing from inside the network, and the unsafe YAML loader on an uploaded file is
  remote code execution. `swagger-parser` does neither of those safely.

Two defects surfaced by porting, both pre-existing and in **both** services:

- `TRY_IT_SANDBOX_URL` defaulted to `localhost:9080` and compose never set it, so Try it live could
  not have worked in this stack on either control plane. The first run of the new gate found it:
  Java and Python failed identically.
- A Swagger 2.0 file declaring no schemes made `swagger-parser` suggest `//host/path`, which the
  backend-URL field it pre-fills then rejects as invalid. The port emits `https://host/path`.

**After pulling:** `docker compose --profile app up -d --build`. `backend-java` will not start and
nothing needs it to. The schema is applied by `backend-python` at startup; its ledger is unchanged
at V9.

## 2026-10-25

### The payload keypair could not be configured at all

Writing the operations runbook turned up three configuration defects, all of which would have been
found the hard way during a production deployment.

**`PAYLOAD_PRIVATE_KEY` and `PAYLOAD_ENCRYPTION_ENFORCED` never reached the containers.** Both
services read them — added with payload encryption on 2026-10-21 — but `docker-compose.yml` passed
neither. So a containerised deployment had no way to supply the keypair: it silently used the
development one committed to this repository, and under a production profile both services simply
refused to start. Now passed to both, from `infra/.env`.

**`SPRING_PROFILES_ACTIVE` was hardcoded to `demo`** while `ENVIRONMENT` on backend-python was
overridable. The two decide the same things — whether a missing secret is fatal, and whether payload
encryption is enforced — so a stack could be switched to production on one service and not the
other, which is exactly what the comment beside `ENVIRONMENT` warns against. Now overridable.

**`infra/.env.example` was four values and a comment**, missing `AUTH_JWT_SECRET` — which compose
marks required, so copying the example and starting the stack failed immediately — along with the
database host, the schema, every mail setting and all three secrets. Rewritten: every value the
stack reads, what it does, how to generate it, and what breaks when the two services disagree.

Verified by generating a real RSA keypair, configuring it, and confirming both services then
reported the **same new key id** rather than the development one — which also demonstrates the two
deriving an identical key id from a configured key, not just from the fallback.

One trap worth knowing, found while testing this: a PEM pasted into `.env` with its real newlines
does not merely fail to load. `.env` takes one `KEY=VALUE` per line, so **every `docker compose`
command then fails** with a parse error naming a line of base64, and the stack can be neither
started nor stopped until it is fixed. Both `awk` and `sed` turned the `
` escape back into real
newlines when escaping it; the runbook gives a one-liner that does not.

### An operations runbook

Three documents in `docs/operations/` — configuring the platform from nothing, watching it once it
runs, and what has to change before production. Also published as a shared document at
https://claude.ai/artifact/XNVaCsEKsxnpfgJKH7SNqY; the copies in the repository are the ones that
version with the code.

Writing them corrected a count this project had been repeating: **backend-python has no scheduler at
all**, so all three of Java's background jobs are load-bearing, not just the key-expiry one.
`OtpCleanupJob` clears expired sign-in codes hourly and `ErrorRetentionJob` prunes the error log on
a cron; without them the OTP table grows without bound and the error log never ages out. What is
actually unported is two endpoints — the Swagger/Postman import and Try it live — plus Flyway,
those three jobs and the demo seeder.

The production tab ends with the open gaps, stated plainly: the approval workflow can be bypassed on
backend-java's port, `KeyExpiryJob` ownership is unsettled, Flyway lives in a service that cannot
therefore be dropped, outbound SMTP is blocked, and nothing can be published until a second
administrator exists.

## 2026-10-25 — products

### Products and access mapping, with the authority for every grant

The backend for API products was complete and had no screens: `/products` and `/mapping` were both
`ComingSoon`, and the Developer Portal had no products page at all — so anything mapped to a partner
was invisible to them. Three screens now, and the mapping carries its evidence.

**Products** (CP-API-09) — list, create and edit. A product is an ordered journey through several
APIs: the order of the steps *is* the journey, so moving a row is the whole interaction. Each step
takes a note saying why it is there and may name an earlier step it depends on; the dependency
dropdown offers only *earlier* steps, because a dependency on a later one describes a journey that
cannot be followed in the order given. Publishing is not reviewed — a product is documentation and an
access grouping, not a route on the gateway, and products are administrator-only.

The list flags a published product whose steps are not all live APIs. A partner's view lists only
live steps, so that combination shows them an empty journey, which looks like a broken page rather
than an incomplete product.

**Access mapping** (CP-PTN-03) — which organizations may use which product, to a whole organization
or to one named person inside it for a pilot. **Every mapping requires an approval reference**:
migration `V9` adds `product_assignment.approval_reference` as `NOT NULL`, and both services refuse a
mapping without one. Free text on purpose — the platform cannot verify a ticket number, and
validating a format that will change would buy nothing. What it can do is refuse to save without
one, which is what makes the trail answer *who authorised this* rather than only who clicked. The
reference is stored on the mapping, shown in the mapping list, and written into the audit trail;
withdrawing a mapping records the authority it had been granted under, since the row holding it is
then gone.

Mapping a draft product is allowed deliberately: the access decision and the publishing decision are
separate, and lining mappings up before launch is the normal order of work. The table says plainly
when a product is not published.

**Developer Portal → Products** — the partner's side, without which none of the above is visible to
its audience. Only published products mapped to that organization appear, each with its steps, the
APIs they call, the dependency spelled out in words, and the integration guide.

Not group-level: `V9` keeps the existing organization-and-user model rather than adding partner
groups, which the nav text had described. A migration for groups would also need a rule for an
organization assigned both directly and through a group.

**Java was updated alongside Python**, as it must be — the two share one database and the column is
`NOT NULL`, so leaving Java's insert alone would have made its assign endpoint fail at runtime. Its
entity, request and view all carry the reference now, and `check_products.py` asserts the two
services still read a mapping identically.

**Corrections to the 2026-10-22 entry below.** Two claims there were wrong:

- it said Java's test suite passed. The final Java build that day used `-DskipTests`, and the suite
  did **not** pass: `ApiLifecycleTest` still asserted that a new API is `ACTIVE`, which the
  draft-on-create change had made false. Fixed, along with `TryItTest` and `ProductJourneyTest`,
  which created APIs and then expected partners to see them — a draft is invisible, which is the
  point of it, so those tests now publish first. All 64 Java tests pass.
- the dev-server proxy default was `http://localhost:8088`, where nothing listens once the backends
  run in containers, so `npm run dev` proxied into a closed port. Both portals now default to
  `127.0.0.1:18090` — backend-python as the stack publishes it, which is where nginx sends every
  admin route and the only service with Approvals and APIM users.

**These screens were verified in a browser**, which nothing since the Swagger work has been: a
product built through the editor, mapped to Acme Fintech with a reference, published, confirmed
visible to that partner in the Developer Portal with both steps, then unmapped and deleted. One bug
came out of it — the mapping screen rendered "no products yet, create one" while the list was still
loading, telling an administrator to create something they already had.

**After pulling:** rebuild everything (`docker compose --profile app up -d --build`); `V9` runs on
backend-java's startup. Any mapping made before this is backfilled with a reference that says
`UNRECORDED`, rather than a default implying an authority it never had.

## 2026-10-22

### A failed sign-in e-mail no longer looks like a sent one

Outbound SMTP is blocked on this network again — 25, 465 and 587 all time out, from the host and from
inside the containers, though DNS resolves and 443 is fine. Nothing in the platform changed; the
network did. What the platform did wrong was hide it:

- **the audit trail said "One-time code e-mailed to …" when the send had failed.** `delivered` was
  `bool(settings.smtp_host)`, computed before sending, so it reported whether mail was *configured*
  rather than whether the message left.
- **the fallback code was suppressed on exactly the failure it exists for.** With a host configured,
  `devCode` was withheld, so a mail-server timeout left the person waiting for an e-mail that never
  arrived, clicking Resend, with no way in.

`notifications.send()` now returns whether every message actually left. Sign-in uses that: the audit
says `COULD NOT BE E-MAILED` and points at System errors, and outside production the code comes back
in the response so a mail outage cannot lock a developer machine out. Under the production profile it
answers `502 CODE_NOT_SENT` instead, because the code must not travel over the wire there — and
clicking Resend forever is worse than being told.

A notice, by contrast, still ignores the result: a failed key-rotation notice must not fail the
rotation. That asymmetry is now stated where `send` is defined.

The sign-in screen's wording followed, since it claimed "no mail server is configured", which is only
one of the two reasons it can now appear.

**To find why a delivery failed** — the reason is recorded per message:

```sql
SELECT occurred_at, code, message FROM apim.error_event
 WHERE source = 'SMTP' ORDER BY occurred_at DESC LIMIT 20;
```

**The real fix on a network like this is an HTTPS mail provider**, not SMTP: 443 reaches
api.brevo.com, api.sendgrid.com and gmail.googleapis.com from both the host and the containers, while
every SMTP port is blocked. Until then, leave `SMTP_HOST` set — it costs a 20-second timeout per
sign-in and the code is shown on screen — or clear it to skip the wait.

### Two APIM roles, and publishing now needs a second pair of eyes

**ADMIN** does everything. **DEVELOPER** drafts and edits APIs and reads every log — and that is all.
Publishing an API, changing one that is already live, and withdrawing one go to an administrator
instead of taking effect.

`EDITOR` is renamed to `DEVELOPER` (migration `V8`). It was already the "works on APIs" role, but it
could publish an API, change a live one and manage partner organizations, their credentials and their
users with nobody else involved. The name now matches what it is, and the permissions were narrowed
to match the name. `VIEWER` is gone: the Python service accepted it in its role lists but Java never
defined it, so no row ever held it.

**After pulling, anyone holding a session token is signed out once** — their role no longer exists.

#### What waits for approval, and what does not

| | |
|---|---|
| Create an API | Applies. **Always a draft now**, whoever asks and whatever `status` the request carries |
| Edit a draft | Applies at once — a draft serves no traffic |
| **Publish** | Change request, always, **including an administrator's own** |
| **Edit a live API** | Change request; the live definition keeps serving until approved |
| Withdraw from service | Immediate for an admin (CP-API-03 — an incident is the wrong time to wait for a signature), a request for a developer |
| Delete | Administrators only, and still only after the 7-day cooling period |

Editing a live API had to be covered or the whole thing would be decorative: a developer could
leave an API in draft and simply edit the live one instead. The proposal is stored whole, as the JSON
body the endpoint would have received, and applied on approval by replaying it through the same
functions a direct call uses — so an approved change cannot do something a direct call would not.

**An approval must come from a different administrator than the requester.** Enforced in the service,
not by hiding a button. A single-administrator platform therefore cannot publish anything, so the
Users & roles screen says so plainly when it finds only one, and `LAST_ADMIN` refuses any change that
would leave none at all.

`POST /apis/{id}/enable` now answers **202 with the change request**, not 200 with the API. `PUT
/apis/{id}` answers 202 with a request when the API is live, and 200 with the API otherwise.
`objectType` is the discriminator, and the API reference documents the response as either.

#### New screens

- **Approvals** — the queue, for both roles: a developer watches their requests, an administrator
  decides them. Shows the proposed definition in full before approving, takes a note that lands in
  the audit trail, and says "needs another admin" rather than silently omitting the button on one's
  own request.
- **Users & roles** (CP-LOG-02) — was a `ComingSoon` placeholder. Create APIM users, set roles,
  suspend, reinstate and remove. No passwords: sign-in is a one-time code, so adding someone is all
  that is needed. An address already belonging to a Developer Portal user is refused — one address is
  one person, or a session's role would depend on which table was consulted.

Screens a developer cannot use are now wrapped, not merely hidden from the navigation: a bookmark or
a typed URL used to reach them and then fail as a wall of 403s.

#### Also

**The audit trail names both people.** The change is attributed to whoever requested it, with the
approver in the detail, and the approver has their own `APPROVE_*` row. It has to answer both "who
changed this" and "who allowed it".

**A known Java defect moved rather than being fixed.** `URI.create` rejects braces, so a backend URL
containing `{param}` made building the gateway configuration throw. It used to fire on create,
because a create published immediately; now that a create lands as a draft it fires on *publish*
instead. Since every publish goes through the Python control plane, which tolerates braces, the
defect is no longer reachable through the portal. `check_api_writes.py` asserts all three parts of
that, so it stays true on purpose rather than by luck.

**Java's create also lands as a draft now.** It had been left returning ACTIVE, which would have let
a caller reaching that service directly walk straight past the approval. Note the remaining boundary:
the approval itself is implemented only in the Python control plane. nginx routes every API write
there, and `backend-java`'s port is not public, but anyone who can reach that port directly can still
publish without review. Worth closing if that port is ever exposed.

New gate `check_roles_and_approvals.py`: a developer cannot publish, cannot edit a live API into
effect, and cannot reach partners, credentials, products, portal content or the APIM users list —
that last one most of all, since they could otherwise make themselves an admin. Plus: nobody approves
their own request, an approval applies exactly what was proposed, and the platform cannot be left
without an administrator.

**The demo seeder now creates two administrators**, because a demo with one could not publish
anything, and renames `ravi.editor@` to `ravi.developer@`.

Verified: 12 of 12 gates, parity unchanged on 8 endpoints, 22 of 22 stack sanity checks, Java's test
suite, and the WebCrypto interop gate. **Not** verified in a browser — the Browser pane still refuses
the self-signed host while the dev CA is untrusted, so the two new screens have been typechecked and
built but not clicked through.

## 2026-10-21

### Portal payloads are encrypted end to end (VAPT)

Every request body and every response between the portals and the platform is now AES-256-GCM under
a per-request key that the browser wraps with the platform's RSA-2048 public key (RSA-OAEP-SHA256).

    X-Encrypted:   v1
    X-Encrypt-Kid: which public key was used
    X-Encrypt-Key: base64( RSA-OAEP-SHA256( 32-byte AES key ) )

    body, and every response:  {"iv": "base64(12 bytes)", "data": "base64(ciphertext||tag)"}

The key travels in a header rather than the body so one code path covers every method: a GET has no
body to carry it, but its response still has to be encrypted. A reply reuses the request's key with a
freshly generated IV, so the browser needs no keypair and nothing is stored between requests.

**This is defence-in-depth on top of TLS, and worth describing to an auditor as such.** It keeps
payloads unreadable in an intercepting proxy, which is how these findings are raised and reproduced.
It buys nothing against someone who controls the browser: the public key is public, so anyone can
encrypt, and the page can always read its own cleartext.

Implemented in all three places, because nginx routes portal traffic between the two control planes
per method and path and the portal cannot tell which one answered:

| | |
|---|---|
| `backend-python/app/middleware.py` | raw ASGI middleware, added last so it is outermost |
| `backend-java/.../PayloadEncryptionFilter.java` | servlet filter at highest precedence, outside the Spring Security chain |
| `frontend/packages/ui/src/payloadCrypto.ts` | WebCrypto, behind the portals' single `fetch` |

Outermost matters in both directions: a body is decrypted before any route or validator parses it,
and a response is encrypted *after* the error handling has built its problem document — including
Spring Security's own 401 and 403 — so an error body does not leak field names and detail in the
clear. That was the first thing checked and it is the easiest thing to get wrong.

**One keypair serves both services**, since a payload the portal sealed once may arrive at either. It
is configured rather than generated, and outside production both fall back to the same development
keypair, committed on purpose and worthless — the same pattern as `AUTH_JWT_SECRET`. Production
refuses to start without `PAYLOAD_PRIVATE_KEY`.

**Enforcement is on in production and off on a developer machine.** Each service derives it rather
than trusting the flag — Python from `ENVIRONMENT=production`, Java from the `prod` profile — so a
deployment cannot accept plaintext because someone left a default alone. Note that the two spell
"production" differently and both must be set. Locally, a request without the headers is still
answered in plaintext, which is what keeps Swagger Try-it-out, the local console, `curl`, the parity
harness and all eleven gates working.

**Query strings are deliberately not encrypted.** Doing so would mean turning every filtered GET into
a POST, losing REST semantics and caching. Nothing sensitive travels in one today: the filters are
dates, a status, a partner id and a free-text search. Credentials, keys, salts and personal data are
all in bodies and responses, which are covered. If a tester insists, moving those GETs to POST is a
separate piece of work.

Two new gates, because the failure modes here are quiet:

- `backend-python/tests/check_payload_crypto.py` acts as the portal does, then tries what a tester
  tries: a tampered payload must be refused (it is — GCM authenticates, and a mode that decrypted it
  anyway would make this decoration), response IVs must never repeat, error bodies must be encrypted,
  a wrong or stale key must fail readably, and the decrypted body must be identical to what the
  endpoint returns unencrypted.
- `infra/tools/check-webcrypto-interop.mjs` covers the one risk the above cannot: `crypto.subtle` is
  the same API in Node and the browser, and RSA-OAEP's MGF1 digest and GCM's tag placement have to
  match what Python's `cryptography` and Java's JCE expect. Get that wrong and everything typechecks,
  every test passes, and the portal fails in the browser with "decryption failed". Both backends
  check out, for reads, writes and encrypted errors.

Verified: 11 of 11 gates, parity unchanged on 8 endpoints, 22 of 22 stack sanity checks, and the
WebCrypto interop gate against both services. **Not** verified in a real browser: the Browser pane
refuses `https://admin.apigw.com` while the dev CA is untrusted, which is still outstanding. The
interop gate exercises the identical browser API against the live backends, which is the closest
substitute.

**After pulling:** rebuild everything — `docker compose --profile app up -d --build` — because all
three pieces changed together. For a real deployment, generate a keypair and set
`PAYLOAD_PRIVATE_KEY` identically for both backends:
`openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048`. In the API reference at
`/swagger-ui.html`, the public-key endpoint and the envelope are documented under **crypto**.

### A gate that had been passing for the wrong reason

Enabling mail (below) broke `check_keys.py`, which read the key-rotation notices out of the container
log — and the bodies are only logged when no SMTP host is configured. Three of its checks survived
because the subject appears in the "Notification … sent to" line, but **"the broadcast carries no
key" started passing against a log line that never contained the body at all.** A security assertion
that cannot fail is worse than none.

The notice bodies are now built by named functions in `notifications.py`, and the gate asserts
against those rather than against log text. It no longer depends on whether mail is configured, and
it gained the opposite check: the admins' notice *does* carry the key and says it is shown only once.

### Mail works: sign-in codes and key notices are sent again

Three separate causes, found in this order:

1. **The network block is gone.** Outbound SMTP was blocked when mail was first set up, which is why
   `SMTP_HOST` was commented out. Re-tested: 587 and 465 both reach `smtp.gmail.com` from the host
   *and* from inside the containers, and the stored App Password authenticates on both. Port 25 is
   still blocked and always will be.
2. **`SMTP_HOST` was empty** in `infra/.env`, so both services took their "no mail server" branch and
   logged the notices instead of sending them.
3. **The real one: `docker-compose.yml` never passed any `SMTP_*` or `MAIL_FROM` to
   `backend-python`.** That service read its own empty defaults and logged every notice no matter
   what `infra/.env` said, while `backend-java` — which does receive them — would have sent. Since
   nginx routes all of `/api/auth/*` to Python, **portal sign-in codes could never have been
   e-mailed at all**, with or without a host configured.

`SMTP_STARTTLS` was not passed to `backend-java` either; its `application.yml` defaults it to true,
which is why 587 worked regardless.

`EMAIL_KEY_TO_ADMIN` now reaches Python as well — Java already read it from the environment, so the
two services could disagree about whether the new key itself goes to the Partner Admins.

**Deliberately still not passed to Python:** `TOKEN_TTL_HOURS`, `OTP_TTL_MINUTES`, `OTP_LENGTH`, the
OTP rate limits and `KEY_OVERLAP_MINUTES`. Python reads all of them, but Java hardcodes the
equivalents in `application.yml` (`PT8H`, `PT5M`, `PT30S`, `PT20M`). Making them settable on one side
only would mean a value in `infra/.env` that one service honours and the other ignores — and a code
minted by one service is verified by whichever answers the next request. Python's defaults already
match those four; change both services together or neither.

**Mail now verifies the server's certificate.** `smtplib`'s `starttls()` with no context does not,
and what travels immediately afterwards is the mail password. Port 465 is also handled properly now:
it speaks TLS from the first byte, so the old code would have opened it as plain SMTP and stalled
until the timeout waiting for a greeting that never comes.

Verified by sending a real message through `backend-python`'s own notifications module, inside the
container, with the live configuration — delivered, and no `SMTP` rows in the error log.

**After pulling:** set `SMTP_HOST=smtp.gmail.com` and `SMTP_STARTTLS=true` in `infra/.env` (it is
git-ignored, so this change is not in the repo), then rebuild and restart both backends:
`docker compose --profile app up -d --build backend-python backend-java`. With a host configured
there is **no more `devCode`** in the sign-in response: if a send fails, the code exists only in the
e-mail that never arrived and the failure is in Dashboard → System errors. Leave `SMTP_HOST` empty to
go back to codes in the log.

## 2026-10-14

### The API reference describes the API

`backend-python` has served a Swagger UI since it was created, and that page listed 71 operations
while describing the response of none of them. It had no **Authorize** button either, so nothing on
it could be tried. The document now carries a response schema, prose and a security scheme for every
operation.

- **New `backend-python/app/schemas.py`** — 60 models for what each endpoint returns: the catalogue
  and partner views, keys, products, portal pages, usage and audit rows, the dashboards, the
  sign-in exchange, and the RFC 9457 `Problem` every error uses.
- **New `backend-python/app/openapi_doc.py`** — attaches those models to the document *after*
  FastAPI generates it, keyed by method and path. **Deliberately not `response_model`:** that would
  make FastAPI filter every response through a model, and a model with one field missing would then
  drop that field from real responses. This service has to answer byte-for-byte as the Java one
  does, so the handlers are left alone and the document is corrected to match them. Also declares
  the bearer scheme (and a separate one for the gateways' ingest token), replaces FastAPI's default
  422 with the 400 this service actually answers, and documents the problem document on every
  operation.
- **53 handler docstrings**, which is where the prose on each operation comes from. Additions only:
  no executable line changed in any router.
- **New gate `backend-python/tests/check_openapi.py`** — the cost of enriching the document outside
  the framework is that nothing notices when a route is added or renamed and the registry is not.
  This does: it fails if a route has no entry, if an entry names a route that no longer exists, if a
  `$ref` dangles, if an operation lacks a described response or prose, or if a public route is
  marked as needing a session. It needs nothing running.

**nginx now serves the Python document** at `/swagger-ui.html` and `/v3/api-docs`, where it served
the Java one before. The springdoc document names controllers rather than resources and describes no
response bodies, so it was the poorer of the two to put in front of a reader; it stays reachable at
`/v3/api-docs-java`, and its own UI at `/swagger-ui/`, because it remains the authority on the
routes Java still owns. Worth knowing when trying a call from that page: the request goes back
through nginx, so the migration switch decides which service answers it.

**Removed the last `upstream` block.** It was only used by those two docs locations. A hostname
inside an `upstream` is resolved when the config loads and then held for the life of the process,
which is what produced 502s after a container rebuild; every `proxy_pass` in the file now goes
through a variable and resolves per request.

### A gate that had been failing since Phase 4

`tests/check_partner_writes.py` asserted that Python answers `501 NOT_MIGRATED` when asked to
withdraw production access or disable an organization. Both were ported in commit `95961b9`, the
same commit that shipped those assertions, and `NOT_MIGRATED` appears nowhere in the service — so
the gate could not have passed since the code it tests was written.

Both services were probed before the expectations were changed, rather than transcribing whatever
Python happened to return: they agree exactly — `200`, tier back to `UAT_ONLY`, the production
Client ID **kept**, then `DISABLED`. The two checks now run each operation against the Java-created
organization too and compare the results, so this stays a parity check rather than becoming a record
of one service's behaviour. The production Client ID being kept is deliberate and now stated in the
test: it is the partner's identity at the gateway, and issuing a different one on re-promotion would
silently break every integration built against it.

**After pulling:** rebuild and restart `backend-python`, then reload nginx — the config is a
read-only bind mount, so `docker compose exec nginx nginx -s reload` is enough, and a reload that
appears to do nothing has probably not been applied yet (check with `docker compose logs nginx`
which upstream served `/v3/api-docs`). The reference is then at
`https://admin.apigw.com/swagger-ui.html`, or `http://127.0.0.1:18090/swagger-ui.html` to bypass
the self-signed certificate. Sign in from the page itself: `POST /api/auth/captcha`, then
`/api/auth/otp/request` — where no mail server is reachable the code comes back as `devCode` — then
`/api/auth/otp/verify`, and paste the token into **Authorize**.

## 2026-10-06

### The backend port moves to Python, on its own branch

The language decision changed. Rather than overwrite the earlier work, each attempt keeps its own
branch, and the tags below are fixed points that will not move:

| Branch | Tag | Holds |
|---|---|---|
| `main` | `java-backend-v1` | Java as the whole backend, at `backend/` |
| `node-migration` | `node-port-v1` | the NestJS port: foundation, parity harness, 9 routes |
| `python-migration` | — | this work: Java plus `backend-python/` |

- **New `backend-python/`: FastAPI, SQLAlchemy 2.0 async with asyncpg, Pydantic v2, PyJWT** on port
  8090. Same database, same signing secret, same contracts as the Java service. `backend-node/` is
  not on this branch; it is preserved on its own.
- **Reached the Node port's coverage on the first pass** — `GET` on `/apis`, `/apis/{id}`,
  `/partners`, `/partners/{id}`, `/partner-groups`, `/audit`, `/usage/report`, `/usage/logs` and
  `/usage/apis/{id}/consumers`, all proven field-for-field against Java before being routed.
- **`backend-python/tools/parity.py`** is the Python counterpart of the Node harness: it mints a
  token in `TokenService`'s shape, calls both services, and prints every differing JSON path.
- The schema stays Flyway's. There are no models and no migrations in this service, and nothing in
  it issues DDL. No SQL names a schema either — the connection's `search_path` decides, so the same
  build works against `apim` or `public`.

**Two defects the parity harness found, which the Node port shares:**

- `/usage/report` was missing `proxyPath`, `successRate`, `minLatencyMs`, `maxLatencyMs` and
  `avgLatencyMs` from every entry. The earlier Node "match" was over a fifteen-minute window with no
  traffic, so an empty list hid it. The rates also need `HALF_UP` rounding, which is not what
  Python's `round()` or JavaScript's `Math.round()` do for ties.
- Traffic whose API has since been deleted is reported by Java as `"Deleted API"`; both ports
  returned `null`. The report additionally excludes events with no API at all, which neither did.

`infra/sanity.sh` now lives in the repository: 22 read-only checks across the portals, both control
planes, authentication, the gateways and TLS.

## 2026-10-03

### The Java-to-Node migration starts in earnest

The port now has a shared foundation and a way to prove each step, rather than one endpoint group
done by hand.

- **Every error leaves the Node service as the same RFC 9457 problem document Java produces** —
  `detail`, `instance`, `status`, `title`, `code`, plus `fields` on a validation failure, as
  `application/problem+json`. This was wrong before: the ported endpoints returned Nest's
  `{statusCode, message}`, which the portals cannot read, so a user would have seen "Request failed"
  instead of the real reason.
- **`backend-node/tools/parity.js` compares an endpoint between the two services** field by field on
  the same database, and prints every differing path. A route is only moved once it matches.
- **Timestamps now match to the microsecond.** PostgreSQL stores `timestamptz` to microseconds but a
  JavaScript `Date` holds milliseconds, so reading one through a `Date` silently truncated every
  timestamp. They are rendered as text in SQL and formatted the way `Instant.toString()` does —
  which prints no fraction, three digits or six, never a fixed width. The parity harness found this.
- **Shared services ported**: the error log (`error_event`, with the same `ERR-XXXXXXXX` references
  and column trimming) and the audit log (`audit_event`).
- **Routes ported and proven**: `GET /api/admin/apis`, `/apis/{id}`, `/partners`, `/partners/{id}`
  and `/partner-groups`, alongside the usage and audit endpoints from before.
- **nginx chooses the backend per method and path**, not per prefix. `/api/admin/apis` is a list on
  `GET` and a create on `POST`, and only the read side is ported; sub-resources such as
  `/partners/{id}/keys` stay on Java rather than being swallowed by a prefix match.
- nginx also resolves upstreams at request time through Docker's DNS now, so rebuilding a backend
  container no longer leaves it answering `502` from a cached address.

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
