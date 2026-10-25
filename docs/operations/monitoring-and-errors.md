# Monitoring and error checking

Everything the platform knows about a failure is in one of four places, and a complaint can be taken
to the row that explains it in about two queries. This document is the path from one to the other.

Companion documents: [configuring the platform](configure.md), and
[hosting in production](production.md).

## What to watch daily

Four screens in the management portal, in the order worth opening them.

| Screen | What you are looking for | A normal day |
| --- | --- | --- |
| **Dashboard** | The last hour: calls, success rate, average latency, the busiest APIs and partners | Success rate steady, no API suddenly absent from the list |
| **System errors** | Anything the platform could not do. Filter by date range and by partner | Empty, or a handful of 4xx-class entries from partners getting their integration right |
| **Approvals** | Change requests waiting. A request sitting here means an API is not live that somebody expects to be | Nothing older than a working day |
| **API logs** | Individual calls, newest first, with status and latency | Used when a partner reports a specific failure, not browsed |

The audit trail is a different thing from the error log and answers a different question: **who did
this**, rather than **what broke**. Both a developer and an administrator can read all of it.

Two numbers are worth checking weekly rather than daily: how many security keys are inside their
expiry overlap, and whether any partner has been promoted to production access without a mapping to
match.

## Where failures are recorded

| Table | Holds | Written when |
| --- | --- | --- |
| `apim.error_event` | **The cause of a failure**: source, code, message, stack trace, the actor, the request path, and a short `reference` | Any 5xx, and every failed e-mail, gateway sync or scheduled job |
| `apim.audit_event` | Who did what, to which object, with detail | Every configuration change, sign-in, approval and mapping |
| `apim.usage_event` | One row per partner call: API, environment, client, status, latency | Shipped by the gateways in batches |
| `apim.otp_challenge` | One row per sign-in code issued; only its hash | A code is requested |

`error_event.source` tells you which part failed, and is the fastest way to narrow a search:

- `API` — a request to a control plane failed. The commonest real entries.
- `SMTP` — a message could not be sent. **This is where "I never got my code" is answered.**
- `GATEWAY` — publishing a route to APISIX failed, so what the portal shows and what the gateway
  serves have diverged.
- `SCHEDULER` — a background job failed, today only key expiry.

**The `reference` is the thread to pull.** A user who hits a 500 is shown something like
`ERR-31A20572` and nothing else; that string is the row's primary identifier, so a support report
becomes a single query.

The container logs hold the same failures plus startup detail. They are the right place for "did
Flyway run" and "is the service listening", and the wrong place for "why did this request fail" —
the database is indexed and the logs are not.

```bash
cd infra && docker compose logs backend-python --tail 200
cd infra && docker compose logs backend-java --tail 200
```

## Finding the cause

Every query below is in [`infra/postgres/diagnostics.sql`](../../infra/postgres/diagnostics.sql),
sixteen of them, each run against the live schema before it was committed. Connect as the
application role:

```bash
psql "postgresql://apigw@localhost:5432/apigw"
```

**Start from the reference, when there is one.** A user quoting `ERR-31A20572` gives you the answer
in one query, stack trace included:

```sql
SELECT * FROM apim.error_event WHERE reference = 'ERR-31A20572';
```

**Nobody received a sign-in code.** Two queries, and the order matters. First, did the request
arrive at all — a row here means a code was issued, so the problem is delivery rather than the
portal:

```sql
SELECT created_at, email, client_ip FROM apim.otp_challenge ORDER BY created_at DESC LIMIT 20;
```

Then why it did not leave. `timed out` means outbound SMTP is blocked, `Connection refused` means
nothing is listening on that port, and an authentication error means the credentials or the app
password are wrong:

```sql
SELECT occurred_at, code, message FROM apim.error_event
 WHERE source = 'SMTP' ORDER BY occurred_at DESC LIMIT 20;
```

**A partner says an API is failing.** What is actually being returned, over the last hour:

```sql
SELECT coalesce(a.proxy_path, '(deleted API)') AS proxy_path, u.status_code, count(*) AS n
  FROM apim.usage_event u
  LEFT JOIN apim.api_definition a ON a.id = u.api_id
 WHERE u.occurred_at > now() - interval '1 hour' AND u.status_code >= 400
 GROUP BY 1, u.status_code ORDER BY n DESC;
```

A wall of 401s from one partner is usually a key they have not rotated to; 429s are the rate limit
doing its job; 5xx means the backend behind the gateway, not the gateway.

**"Who changed this API, and who allowed it?"** The trail answers both, because a change is recorded
against the person who asked for it and the approver gets their own row:

```sql
SELECT occurred_at, actor, actor_role, action, detail FROM apim.audit_event
 WHERE object_type IN ('API', 'CHANGE_REQUEST') AND object_id = '<the API uuid>'
 ORDER BY occurred_at;
```

**"Why can nothing be published?"** Almost always this one — an approval has to come from a second
administrator:

```sql
SELECT count(*) AS active_admins FROM apim.platform_user
 WHERE role = 'ADMIN' AND status = 'ACTIVE';
```

## Faults seen in practice

Every one of these has happened on this platform during its build.

| Symptom | Cause | Fix |
| --- | --- | --- |
| No sign-in code arrives; `error_event` shows `SMTP` / `timed out` | Outbound SMTP blocked on the network — ports 25, 465 and 587 all closed, while 443 is open | Move to an HTTPS mail provider, or have the network opened. Until then clear `SMTP_HOST` and the code is shown on the sign-in screen |
| A portal screen shows stale data after a container rebuild; `502` from nginx | nginx had cached the old container's IP | Already fixed — every upstream resolves per request. If it recurs, `docker compose exec nginx nginx -s reload`, then check the logs to confirm the reload applied: one that appears to do nothing often has not |
| An API is live in the portal but returns 404 at the gateway | The gateway sync failed after the database write. They are deliberately not in one transaction, because APISIX cannot roll back | Look for `source = 'GATEWAY'` in `error_event`, then re-save the API to retry the sync |
| A published product shows a partner an empty journey | Its steps are APIs that are still drafts; a partner sees only live steps | Publish the APIs. The Products list flags this before a partner sees it |
| Nothing can be published; the queue only grows | One active administrator, so no one can approve another's request | Create a second administrator |
| Sign-in works, then the next request is 401 | The two control planes hold different `AUTH_JWT_SECRET` values | Make them the same and restart both |
| Every portal call fails after a key change | `PAYLOAD_PRIVATE_KEY` differs between the services, or the page was loaded before a rotation | The error names the key id it was given against the current one. Reload the portal; if it persists, the two services disagree |
| Docker Desktop will not start: `remove ...dockerInference: The file cannot be accessed` | Orphaned sockets from a previous crash, which cannot be deleted and are invisible to a normal existence check | Stop every Docker process, rename `%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` aside, then start once. Each failed start orphans another, so clean both before retrying |

## Health checks and alerts

Both control planes expose the same probe, at the same path and in the same shape, so a load
balancer does not care which answers:

```
GET /actuator/health  →  {"status":"UP","components":{"db":{"status":"UP"}}}
```

It reports `DOWN` rather than refusing to start when the database is unreachable — the service comes
up and says so, which lets an orchestrator restart it instead of crash-looping while PostgreSQL
starts.

What is worth alerting on, and why each one is actionable:

| Alert | Condition | Why |
| --- | --- | --- |
| Service down | `/actuator/health` not `UP` on either backend for 2 minutes | Either the service or its database |
| Mail failing | Any new `error_event` with `source = 'SMTP'` | Nobody can sign in, and the platform will not tell them |
| Gateway drift | Any new `error_event` with `source = 'GATEWAY'` | The portal and the gateway now disagree about what is published |
| Errors rising | `error_event` rows in 15 minutes above your normal | The generic catch-all |
| Approvals stalling | A `change_request` `PENDING` for more than a working day | Something is meant to be live and is not |
| No usage | Zero `usage_event` rows in an hour during business hours | The gateways have stopped shipping, so every report silently reads as zero traffic |
| Single administrator | `count(*) < 2` active admins | Nothing can be approved |

The last two matter more than they look. An empty traffic report is indistinguishable from a quiet
day unless something checks, and a platform that cannot approve anything fails silently — requests
simply queue.

There is no metrics endpoint and no log shipping configured. For anything beyond these checks, the
database is the source: it is indexed, it is already backed up, and it holds the same facts the
screens show.
