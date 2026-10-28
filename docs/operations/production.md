# Hosting in production

The platform runs today under a demo profile with development fallbacks for every secret. This
document is what has to change, in the order it has to change, and the gaps that are still open.

Companion documents: [configuring the platform](configure.md), and
[monitoring and error checking](monitoring-and-errors.md).

## What has to change

**Set both profile switches or neither.** They decide the same things — whether a missing secret is
fatal, and whether payload encryption is enforced — but they are separate settings on separate
services, so setting one leaves the platform half in production.

| Setting | Developer | Production | What it changes |
| --- | --- | --- | --- |
| `SPRING_PROFILES_ACTIVE` | `demo` | `prod` | backend-java: secrets become mandatory, payload encryption enforced |
| `ENVIRONMENT` | `demo` | `production` | backend-python: the same, for that service |
| `AUTH_JWT_SECRET` | empty | 48 random bytes, base64 | Empty falls back to a key published in this repository |
| `CRYPTO_MASTER_KEY` | empty | 32 random bytes, base64 | The same, for stored secrets |
| `PAYLOAD_PRIVATE_KEY` | empty | RSA-2048 PEM, newlines as `\n` | The same, for portal payloads |
| `PAYLOAD_ENCRYPTION_ENFORCED` | `false` | `true` (implied by the profile) | Unencrypted `/api` calls refused |
| `DB_HOST` | `host.docker.internal` | your database host | |
| `SMTP_HOST` | often empty | your mail host | Empty means sign-in codes are never sent |
| `APISIX_*_ADMIN_KEY` | `change-me-...` | generated | Admin access to the gateways |
| `USAGE_INGEST_TOKEN` | `change-me-...` | generated | Lets anything post fabricated usage data |
| `PUBLIC_SANDBOX_URL` | the local name | your sandbox URL | Shown to partners as the base URL to call |
| `TRY_IT_MODE` | `GATEWAY` | `GATEWAY` | `SIMULATE` answers from documentation instead of really calling |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | generated, or drop the service | Nothing connects to Keycloak today |

Under the production profile a missing `AUTH_JWT_SECRET`, `CRYPTO_MASTER_KEY` or
`PAYLOAD_PRIVATE_KEY` **stops the service starting**. That is deliberate: the alternative is running
on a keypair committed to a public repository, and a platform that will not start is a better
failure than one that appears to work.

## Hardware and shape

1,000 requests a minute is about 17 a second, which is small for APISIX. The sizing below is driven
by resilience and by the regulator's expectations, not by that throughput.

| Tier | Per node | Nodes | Note |
| --- | --- | --- | --- |
| APISIX gateways | 2 vCPU, 4 GB | 2 per environment | Sandbox and production stay **separate deployments**, so a sandbox credential can never reach production |
| etcd | 2 vCPU, 4 GB | 3 | Gateway configuration. Three for quorum, not for load |
| Control planes | 2 vCPU, 4 GB | 2 each | Both services, behind the same nginx |
| nginx | 2 vCPU, 4 GB | 2 | TLS termination and the route map |
| Valkey | 2 vCPU, 4 GB | 2 | Rate-limit counters, shared across gateway nodes |
| PostgreSQL | 4 vCPU, 16 GB | 1 + standby | Managed service preferred; it holds everything |

Two availability zones in the primary region, and a DR region if CSCRF requires it. The data
constraint is residency — India — and a MeitY-empanelled provider, rather than capacity.

**What to watch as load grows**: rate-limit counters are in Valkey, so that is the first shared
bottleneck; usage events are written in batches from the gateways and accumulate in PostgreSQL,
where the retention is 30 days; and the control planes are stateless, so they scale horizontally
without coordination.

The compose file in `infra/` is a **developer and demo arrangement**, not a production deployment.
It runs one of everything on one host, publishes the backends on the loopback interface for the test
harness, and includes two mock upstreams and a Keycloak that nothing uses. For production, take the
images and the environment contract from it and deploy them with whatever you run elsewhere.

## TLS, DNS and the network

Four names, and they stay four: nginx serves a different site per name and closes the connection on
anything it does not recognise. A partner's traffic and an administrator's never share an origin.

| Name | Serves | Reachable from |
| --- | --- | --- |
| `admin.apigw.com` | Management portal and the admin API | Your corporate network only |
| `developer.apigw.com` | Developer Portal | Partners, over the internet |
| `sandbox-api.apigw.com` | Sandbox gateway | Partners |
| `api.apigw.com` | Production gateway | Partners |

**Replace the certificate.** `infra/nginx/make-certs.sh` produces a self-signed CA for local work.
Production takes a certificate from your usual authority, covering all four names, installed at
`infra/docker/certs/server.crt` and `server.key` or wherever your deployment mounts them.

**The management portal should not be on the public internet.** Nothing in the platform enforces
that — it is a network decision, and the one with the largest effect on this platform's exposure.

What must be reachable outbound, from the control planes:

- The database.
- The APISIX admin APIs, on both gateway deployments.
- SMTP, or an HTTPS mail provider. Note that **outbound SMTP is blocked on the current network**
  while 443 is open, which is why an HTTPS provider is the safer assumption.
- The partner backends the gateways forward to.

What must not be reachable: **the control planes' own ports**. In the compose arrangement they are
published on `127.0.0.1` for the test harness. If port 8088 is reachable in production, the approval
workflow can be bypassed — see the gaps below.

## The cutover

The order is forced by what depends on what.

1. **Database first.** Create the role, database and schema with `infra/postgres/local-setup.sql`.
   Confirm you can connect as `apigw` from where the control planes will run.
2. **Secrets.** Generate the three, put them in whatever holds secrets for you, and confirm **both**
   services will receive identical values.
3. **etcd, then the gateways.** APISIX will not start without etcd. Two deployments, sandbox and
   production, with different admin keys.
4. **backend-java.** It runs Flyway, so the schema exists only after this has started once. Watch
   for `Successfully applied` in its log, then check `/actuator/health`.
5. **backend-python.** Confirm `/actuator/health`, then that both services serve the **same** payload
   key id — if these differ, every portal call fails for whichever service did not get the right
   key:

    ```bash
    curl -s http://<java>:8088/api/crypto/public-key   | grep -o '"kid":"[^"]*"'
    curl -s http://<python>:8090/api/crypto/public-key | grep -o '"kid":"[^"]*"'
    ```

6. **nginx**, with the real certificate and the four names resolving.
7. **Verify** with `infra/sanity.sh`, pointed at the real host. 22 checks, read-only.
8. **The first two administrators**, by insert, then everything else through the portal.
9. **One end-to-end test with a real partner** before any traffic: onboard an API, publish it
   through the approval, register an organization, issue a sandbox key, and have them call it.

Rolling back is undramatic for the services — they hold no state, so redeploy the previous image.
**Flyway migrations do not roll back.** `V8` renamed a role and `V9` added a NOT NULL column;
reverting the code without reverting the schema leaves the old code reading a column it does not
know, which is survivable, while reverting the schema under new code is not. Take a database
snapshot before a release that carries a migration.

## Backup, restore and rotation

One database holds everything: APIs, partners, key hashes, products, mappings, the audit trail and
the error log. The services hold no state. So the backup policy is the database's, plus the secrets.

**Back up**: PostgreSQL, at whatever RPO the regulator expects, and the three secrets, wherever you
keep secrets. A database restored without its `CRYPTO_MASTER_KEY` has unreadable IPV salts, and one
restored without `AUTH_JWT_SECRET` simply signs everyone out — the first is data loss, the second is
an inconvenience.

**Test the restore.** A backup of this database is only useful if the key that decrypts its secrets
is restorable with it.

What each rotation actually costs:

| Secret | To rotate | Effect |
| --- | --- | --- |
| `AUTH_JWT_SECRET` | New value on both services, restart both | Everyone is signed out once. No data effect |
| `PAYLOAD_PRIVATE_KEY` | New keypair on both, restart both | Open portal pages fail once and recover on reload — they are told the key id has changed |
| `CRYPTO_MASTER_KEY` | **Decrypt and re-encrypt the stored values first** | Not a restart. Skip the re-encryption and every partner's IPV salt is unreadable, permanently |
| `USAGE_INGEST_TOKEN` | New value on the control planes and both gateways | Usage stops being recorded until all four agree |
| APISIX admin keys | New value on the gateways and both control planes | Publishing an API fails until they agree |

Partner security keys are a different matter and rotate themselves: issuing a new one keeps the
previous valid for a 20-minute overlap, so an integration can cut over without downtime. Only a hash
is ever stored, so a key cannot be recovered — only replaced.

## Open gaps

These are known and unresolved. None is hidden in the code; all of them are cheaper to decide now
than to discover later.

- [x] ~~The approval can be bypassed on the Java port~~ — closed. `backend-java` no longer starts
      with the stack, so there is no second port to reach. It sits on its own compose profile and is
      brought up only to run the parity gates: `docker compose --profile app --profile java up -d`.
- [x] ~~All three scheduled jobs are Java's~~ — ported. Key expiry, sign-in code cleanup and
      error-log retention run in `backend-python`, each tick taking an advisory lock so two
      instances cannot double-run them. Java never had that guard.
- [x] ~~Flyway lives in backend-java~~ — ported. `backend-python` applies the same files from
      `backend-python/migrations/` against the same ledger.
- [ ] **Mail.** Outbound SMTP is blocked on the current network. Decide between an HTTPS mail
      provider and a network change — without one, nobody can sign in, because a production
      deployment will not return the code in the response.
- [ ] **Two administrators minimum**, or nothing can ever be published.
- [x] ~~Two endpoints are unported~~ — ported. The Swagger/Postman importer and Try it live both
      run in `backend-python`, each proven against Java by feeding both the same input and
      comparing. The demo seeder moved too.
- [ ] **Query strings are not encrypted.** A deliberate decision: payload encryption covers bodies
      and responses. Nothing sensitive travels in a query string today — dates, a status, a partner
      id, a search term — but a VAPT tester will ask, and the answer is "by design, and here is what
      is in them".
- [ ] **No metrics endpoint, no log shipping.** Monitoring is the database and the health probes.
- [ ] **Keycloak runs and nothing connects to it.** Either drop the service or give it a purpose; an
      unused identity provider with a default password is a finding waiting to happen.
- [ ] **Vulnerability scanning is not scheduled.** The SBOM in `sbom/` lists what ships; nothing yet
      checks it against a feed. `grype` reads those files directly.

Two of these are one-line decisions — dropping Keycloak, and choosing a mail provider. The first two
are architectural and worth settling before a VAPT engagement rather than during one.
