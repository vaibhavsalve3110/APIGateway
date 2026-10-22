-- Diagnostic queries for the API Gateway platform.
--
-- Read-only: nothing here changes a row. Run a section at a time rather than the whole file.
--
--   psql "postgresql://apigw@localhost:5432/apigw"              -- host PostgreSQL
--   docker compose exec backend-python ...                      -- not needed; this is pure SQL
--
-- Everything lives in schema apim. The queries name it explicitly so they work whatever the
-- connection's search_path happens to be.
--
-- A note on timestamps: these columns are timestamptz, so psql renders them in your session's time
-- zone. The API renders the same values as UTC instants. If a time here looks 5h30m off what the
-- portal showed, that is why, not a bug.


-- ===========================================================================
-- Sign-in and one-time codes: "I did not get the OTP"
-- ===========================================================================

-- 1. Did the request reach the backend at all? One row per code issued.
--    No row means the request never arrived — look at nginx and the portal, not at mail.
--    Note only the hash is stored; the code itself is never persisted, by design.
SELECT created_at, email, attempts, client_ip,
       CASE WHEN consumed_at IS NOT NULL THEN 'used'
            WHEN expires_at < now()      THEN 'expired'
            ELSE 'still valid' END AS state
  FROM apim.otp_challenge
 ORDER BY created_at DESC
 LIMIT 20;

-- 2. What the platform *thinks* happened. Since 2026-10-22 this says COULD NOT BE E-MAILED when
--    the send failed; before that it always claimed "e-mailed", even on a timeout.
SELECT occurred_at, actor, action, detail
  FROM apim.audit_event
 WHERE action IN ('SIGN_IN_CODE_SENT', 'SIGN_IN', 'SIGN_IN_FAILED')
 ORDER BY occurred_at DESC
 LIMIT 20;

-- 3. **The answer, usually.** Why a message did not leave: a timeout means outbound SMTP is
--    blocked, "Connection refused" means nothing is listening on that port, and an
--    SMTPAuthenticationError means the credentials or the App Password are wrong.
SELECT occurred_at, code, message, reference
  FROM apim.error_event
 WHERE source = 'SMTP'
 ORDER BY occurred_at DESC
 LIMIT 20;

-- 4. One line per sign-in attempt, joining what was issued to what was delivered. Use this when
--    several people report the same thing and you want to see whether it is everyone or one inbox.
SELECT c.created_at, c.email,
       CASE WHEN e.id IS NULL THEN 'sent' ELSE 'NOT SENT: ' || e.message END AS delivery
  FROM apim.otp_challenge c
  LEFT JOIN apim.error_event e
         ON e.source = 'SMTP'
        AND e.message LIKE '%' || c.email || '%'
        -- Same request: the failure is recorded within a second or two of the challenge.
        AND e.occurred_at BETWEEN c.created_at AND c.created_at + interval '2 minutes'
 ORDER BY c.created_at DESC
 LIMIT 20;

-- 5. Is the address allowed to sign in at all? An address that is in neither table gets no code,
--    and an address in both would be ambiguous (the platform refuses to create that).
SELECT 'APIM user' AS kind, email, role, status FROM apim.platform_user WHERE lower(email) = lower('someone@example.com')
UNION ALL
SELECT 'Portal user', email, role, status FROM apim.partner_user WHERE lower(email) = lower('someone@example.com');

-- 6. Rate limiting: too many codes for one address inside the window are refused. Default is 5 per
--    15 minutes, so a burst of testing can lock an address out for a while.
SELECT email, count(*) AS codes_in_last_15_min
  FROM apim.otp_challenge
 WHERE created_at > now() - interval '15 minutes'
 GROUP BY email
 ORDER BY codes_in_last_15_min DESC;


-- ===========================================================================
-- Everything else that went wrong
-- ===========================================================================

-- 7. Recent failures of every kind. `reference` is what a user is shown on a 500 — searching for it
--    here is how you get from "quote ERR-31A20572 to your administrator" to the cause.
SELECT occurred_at, source, code, left(message, 160) AS message, reference, actor, request
  FROM apim.error_event
 ORDER BY occurred_at DESC
 LIMIT 30;

-- 8. One reference, in full, with its stack trace.
SELECT * FROM apim.error_event WHERE reference = 'ERR-XXXXXXXX';

-- 9. What has been failing most, over the last day. Tells you whether something is broken or
--    somebody simply mistyped once.
SELECT source, code, count(*) AS n, max(occurred_at) AS last_seen
  FROM apim.error_event
 WHERE occurred_at > now() - interval '1 day'
 GROUP BY source, code
 ORDER BY n DESC;


-- ===========================================================================
-- Who did what (audit trail)
-- ===========================================================================

-- 10. Everything one person did.
SELECT occurred_at, action, object_type, object_id, detail
  FROM apim.audit_event
 WHERE actor = 'someone@example.com'
 ORDER BY occurred_at DESC
 LIMIT 50;

-- 11. Everything that happened to one API, including who asked and who approved.
SELECT occurred_at, actor, actor_role, action, detail
  FROM apim.audit_event
 WHERE object_type IN ('API', 'CHANGE_REQUEST')
   AND object_id = 'PUT-THE-API-UUID-HERE'
 ORDER BY occurred_at;


-- ===========================================================================
-- Approvals (change requests)
-- ===========================================================================

-- 12. What is waiting, and who raised it. Remember an approval has to come from a *different*
--     administrator, so a request sitting here with only one active admin cannot be approved at all.
SELECT r.requested_at, r.action, a.name AS api, r.summary, r.requested_by
  FROM apim.change_request r
  LEFT JOIN apim.api_definition a ON a.id = r.object_id
 WHERE r.status = 'PENDING'
 ORDER BY r.requested_at DESC;

-- 13. How many administrators can approve. One (or none) is why nothing can be published.
SELECT count(*) AS active_admins
  FROM apim.platform_user
 WHERE role = 'ADMIN' AND status = 'ACTIVE';

-- 14. A decided request, with both names on it.
SELECT requested_at, action, summary, requested_by, status, decided_by, decided_at, decision_note
  FROM apim.change_request
 ORDER BY requested_at DESC
 LIMIT 20;


-- ===========================================================================
-- Gateway traffic
-- ===========================================================================

-- 15. The most recent calls partners actually made, newest first. usage_event stores only api_id,
--     so the method and path come from the API; a deleted API leaves them null.
SELECT u.occurred_at, a.http_method, a.proxy_path, u.environment, u.status_code, u.latency_ms,
       p.name AS partner
  FROM apim.usage_event u
  LEFT JOIN apim.api_definition a ON a.id = u.api_id
  LEFT JOIN apim.partner p ON p.client_id_sandbox = u.client_id
                           OR p.client_id_production = u.client_id
 ORDER BY u.occurred_at DESC
 LIMIT 30;

-- 16. Failures by API over the last hour — the first thing to look at when a partner says
--     "your API is down".
SELECT coalesce(a.proxy_path, '(deleted API)') AS proxy_path, u.status_code, count(*) AS n
  FROM apim.usage_event u
  LEFT JOIN apim.api_definition a ON a.id = u.api_id
 WHERE u.occurred_at > now() - interval '1 hour'
   AND u.status_code >= 400
 GROUP BY 1, u.status_code
 ORDER BY n DESC;
