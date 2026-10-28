# Security scanning

How to run the two scans this platform is checked with, what the results mean, and what was found
and decided the last time they ran. Both are repeatable from a clean checkout and need nothing
installed beyond Docker.

Companion documents: [configuring the platform](configure.md),
[monitoring and error checking](monitoring-and-errors.md), and
[hosting in production](production.md).

## The two scans

**Dependency and image scanning** — what is in the images and whether any of it has a published
advisory. Two steps, because the inventory and the verdict are separate concerns: the SBOM describes
what exists and is committed to the repository, the scan compares it against a feed that changes
daily and is not.

```bash
cd sbom && ./generate.sh && ./scan.sh
```

`generate.sh` catalogues every image **as it exists locally**, so build first or it documents a build
nobody is running:

```bash
cd infra && docker compose --profile app build
```

**Platform scanning** — the running stack: response headers, TLS, exposed ports, error handling,
authentication boundaries.

```bash
cd infra && ./sanity.sh                                     # 22 checks, read-only
cd backend-python && .venv/Scripts/python tests/check_security_headers.py   # 63 assertions
```

TLS configuration is checked with testssl.sh, which needs no installation either. Give the container
a hosts entry for the name, because nginx closes the connection on a hostname it does not serve:

```bash
docker run --rm --add-host developer.apigw.com:host-gateway \
  drwetter/testssl.sh --quiet -p -s -U developer.apigw.com:443
```

## What `scan.sh`'s exit code means

Non-zero when a **fixable** High or Critical exists — one where the feed names a version that
resolves it. That is the line worth failing a build on, and it is deliberately not "any High":

- A Debian or Alpine base carries a tail of advisories with **no fixed version available**. They are
  real, most are unreachable from these services (mount helpers, terminfo tools, Perl archive
  parsing), and nothing in this repository can clear them. Failing on those means a permanently red
  gate, which is the same as no gate.
- A finding **with** a fix is a decision somebody has to make today: take the upgrade, or write down
  why not. There is no third option, and this document is where the second one goes.

When a base image's own tail grows long, the answer is a newer base rather than a wider rule. That
is why `backend-python` moved from Debian 12 to 13.

## Cadence

| When | What |
| --- | --- |
| Before a release | Both scans. A fixable High or Critical is a release decision, not a footnote |
| Monthly | `generate.sh && scan.sh`. Feeds change daily; images do not |
| After any dependency change | `tools/relock.sh`, rebuild, then both scans |
| Before a VAPT engagement | Both, plus testssl.sh, so the report contains no surprises |

The scans are not yet wired into CI. `scan.sh` is written to be the thing CI runs — one command, a
meaningful exit code — and that is the remaining step.

## What the 2026-10-28 scan found

Run against the whole stack: 12 SBOMs, the TLS configuration of all four hostnames, and the
platform's own surface.

### Fixed

**Python dependencies.** `pillow` 11.3.0 carried five critical advisories and `cryptography` 46.0.7
three high ones; `starlette` 0.48 three more. All raised: Pillow 13, cryptography 50, and — because
clearing starlette's three meant 1.3.1 or later — FastAPI 0.162 with starlette 1.10. Worth recording
that **none of the Pillow criticals was reachable**: every one is in a decoder (TIFF, FlashPix, JPEG)
or the Ghostscript shell-out, and this service only ever *draws* the sign-in CAPTCHA. The
cryptography and starlette ones were reachable — the bundled OpenSSL and the ASGI layer every
request passes through.

**The base images, which were most of the count.** Three changes, no application code:

| Image | Before | After | What did it |
| --- | --- | --- | --- |
| `backend-python` | 20 critical, 135 high | **0 critical, 55 high** | Debian 12 → 13, and curl removed |
| `nginx` | 28 critical, 103 high | **1 critical, 1 high** | `apk upgrade`, curl removed |
| Both portals | 28 critical, 103 high each | **1 critical, 1 high** each | the same |
| The two gateways | 10 critical, 98 high | **3 critical, 81 high** | `apt upgrade` on the published image |
| `valkey` | 13 high | **0** | pulling the tag again |

Two patterns are worth keeping:

- **curl was the single largest source of unfixed critical advisories** in both the Python image and
  the nginx one — present for a health check in one case and for nothing at all in the other.
  Removing it took twelve criticals out of `backend-python` and twenty out of each nginx image. The
  health check does the same job with the Python standard library.
- **Pulling a published tag again does not refresh its packages.** `nginx:1.29-alpine` freshly
  pulled still shipped curl 8.17.0-r1 against Alpine's 8.22.0-r0. The tag itself is behind, so the
  images are now *built* from it — two lines in `infra/nginx/Dockerfile`.

**TLS configuration.** `ssl_ciphers HIGH:!aNULL:!MD5` was too broad in two ways a scan finds at
once: it offered CBC suites, which is what LUCKY13 is about, and static-RSA AEAD suites, which have
no forward secrecy at all. Now six ECDHE AEAD suites for TLS 1.2 and nothing else, server preference
on, and session tickets off — a ticket key that is never rotated undoes the forward secrecy the
cipher list was chosen for. Re-scanned: LUCKY13 not vulnerable, no CBC, no suite without forward
secrecy.

**BREACH.** `gzip off` on both `/api/` locations. The exposure was already weak here — authentication
is a bearer token rather than a cookie, so a cross-origin request carries no credentials and the
attack's precondition is missing — but these responses carry key reveals and IPV salts, and under the
production profile they are encrypted envelopes that do not compress anyway. It costs nothing.
Static assets are still compressed.

**Ports bound to every interface.** This was the most serious finding, and it came from reading
`docker compose ps` rather than from either scanner:

| Service | Was | Now | Why it mattered |
| --- | --- | --- | --- |
| `valkey` | `0.0.0.0:6379` | `127.0.0.1:6379` | A Redis-compatible store answering `PING` **with no password**, to anything on the same network. A well-worn route to code execution |
| Both gateways' Admin API | `0.0.0.0:9180/9181` | `127.0.0.1:…` | Creates routes on the data plane; guarded only by an admin key that defaults to `change-me-…` |
| `keycloak` | `0.0.0.0:8180` | `127.0.0.1:8180` | Admin password defaults to `admin`, and nothing connects to it |
| Both mock upstreams | `0.0.0.0:8091/8092` | `127.0.0.1:…` | Test servers, no reason to be on the network |

Only nginx is published on all interfaces now, which is the whole point of having it. The two
control planes were already on loopback.

**E-mail in the request path.** Not from a scanner either — it surfaced as a gate timing out. Key
issuance sent its four notices **sequentially**, each a fresh SMTP connection taking 6–13 seconds
against a real provider, so one rotation held a request for 30–50 seconds and exceeded a client's
30-second timeout. They now go out concurrently. See the open items below for what is left of this.

### Clean

No finding, and each was checked rather than assumed: `TRACE` and `TRACK` refused (405/400); no
cookies set anywhere, so no cookie-flag or CSRF-via-cookie surface; no directory listing and no file
exposure — `/.env`, `/.git/config` and the like return the SPA's `index.html`, not a file; error
bodies are RFC 9457 problem documents with no stack trace or internal detail; request bodies capped
and enforced (413 at 5 MB on the developer portal); the sign-in code endpoint is behind a CAPTCHA
before any rate limit applies; `/internal/usage/batch` is not routed by nginx at all; etcd publishes
no port. SSLv2, SSLv3, TLS 1.0 and TLS 1.1 are all not offered, and Heartbleed, CCS, Ticketbleed,
ROBOT, CRIME, POODLE, SWEET32, FREAK, DROWN, LOGJAM, BEAST and Winshock all came back not
vulnerable. `npm audit` is clean, including the build-time tree. `bandit` finds no high-severity
issue — its 22 "possible SQL injection" hits were each checked and every interpolation is a
module-level constant or a literal, never request data.

### Open, with the reason

- **`backend-java` carries four critical advisories** (`tomcat-embed-core` 11.0.24 → 11.0.25, plus
  Guava and Jackson). Nothing routes to it and it does not start with the stack, so this is not
  live exposure — but it is why `scan.sh` currently exits non-zero. **Deleting the service closes it
  outright**, at the cost of the 95 cross-check assertions in twelve gates. That decision is open.
- **etcd**, nine criticals in the Go standard library and `golang.org/x/net`, fixable only by a newer
  image: v3.5.33 is the last of the 3.5 line, so this means **etcd 3.6**, which is a datastore
  version change with migration consequences. It publishes no port and is reachable only from the
  gateways on the compose network.
- **The gateways' remaining 3 critical / 81 high** have no fixed version at this APISIX patch level.
  Clearing them means a newer APISIX on a newer base — a platform decision, deliberately not taken
  as part of a patch pass.
- **`postgres:17-alpine`**, three criticals in Go binaries inside the image. The platform points at
  the host's PostgreSQL; this image only runs under the `bundled-db` profile.
- **Valkey has no password.** Loopback binding is the right fix for a developer stack; production
  needs `requirepass` *and* a private network, and the gateways' `limit-count` configuration has to
  carry the password.
- **Notices are still sent inside the request.** Concurrent now, so a rotation costs one round trip
  instead of four, but a hanging mail server still holds the request for up to its 20-second timeout
  and a notice is lost if it fails. The proper fix is an outbox table drained by the existing job
  runner, which already has advisory locking — a feature, not a patch.
- **`'unsafe-inline'` in `style-src`, and Google Fonts.** Both carried over from the header work;
  see [production.md](production.md) for what removing each would take.
- **Neither scan runs in CI.**

## Traps

- **`scan.sh` must never report clean because it read nothing.** Two earlier versions did exactly
  that: on Windows the Docker bind mount resolved inside the Docker VM, and the summary was built
  from an empty directory. It now exits 2 if there are no results, and converts paths with
  `cygpath -m`. Treat a clean report with no table rows as a broken scanner, not a clean stack.
- **Run the gates with `backend-python/.venv/Scripts/python`.** The system interpreter has neither
  FastAPI nor cryptography, and a gate that dies on `ModuleNotFoundError` prints no `FAIL` line — so
  a loop that greps the output reads a crash as a pass. Check the exit code.
- **Twelve gates need `backend-java` running** and they **fail**, loudly but confusingly, when it is
  not — connection refused, not a skip. `docker compose --profile app --profile java up -d` first.
- `MSYS_NO_PATHCONV=1` is needed for `tools/parity.py` and breaks `infra/sanity.sh`. Set it per
  command, never for the shell.
