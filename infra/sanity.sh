#!/usr/bin/env bash
# End-to-end sanity check of the running stack, through nginx over TLS.
# Read-only: it never creates, changes or deletes anything.
set -uo pipefail

# Resolved before the cd: BASH_SOURCE is relative to where the script was invoked from, so reading it
# afterwards silently yields the wrong directory and every authenticated check fails.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1

CA="docker/certs/apigw-local-ca.crt"
TOOLS="$HERE/tools"
ADMIN_T=$(node "$TOOLS/mint-token.js" admin@apigw.local ADMIN)

pass=0; fail=0
check() {  # check <label> <expected-status> <curl args...>
  local label="$1" expect="$2"; shift 2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --ssl-no-revoke --cacert "$CA" "$@")
  if [ "$code" = "$expect" ]; then
    printf "  ok    %-52s %s\n" "$label" "$code"; pass=$((pass+1))
  else
    printf "  FAIL  %-52s got %s, wanted %s\n" "$label" "$code" "$expect"; fail=$((fail+1))
  fi
}

A=(--resolve admin.apigw.com:443:127.0.0.1 -H "Authorization: Bearer $ADMIN_T")
D=(--resolve developer.apigw.com:443:127.0.0.1)

echo "--- portals (TLS, served by nginx)"
check "management portal"            200 --resolve admin.apigw.com:443:127.0.0.1 https://admin.apigw.com/
check "developer portal"             200 "${D[@]}" https://developer.apigw.com/
check "SPA deep link survives refresh" 200 --resolve admin.apigw.com:443:127.0.0.1 https://admin.apigw.com/partners/abc
check "http redirects to https"      301 --resolve admin.apigw.com:80:127.0.0.1 http://admin.apigw.com/

echo "--- admin API, reads now served by PYTHON"
check "GET /apis"                    200 "${A[@]}" https://admin.apigw.com/api/admin/apis
check "GET /partners"                200 "${A[@]}" https://admin.apigw.com/api/admin/partners
check "GET /partner-groups"          200 "${A[@]}" https://admin.apigw.com/api/admin/partner-groups
check "GET /audit"                   200 "${A[@]}" https://admin.apigw.com/api/admin/audit
check "GET /usage/report"            200 "${A[@]}" https://admin.apigw.com/api/admin/usage/report
check "GET /usage/logs"              200 "${A[@]}" https://admin.apigw.com/api/admin/usage/logs

echo "--- admin API, still served by JAVA"
check "GET /dashboard"               200 "${A[@]}" https://admin.apigw.com/api/admin/dashboard
check "GET /errors"                  200 "${A[@]}" https://admin.apigw.com/api/admin/errors
check "GET /partner-users"           200 "${A[@]}" https://admin.apigw.com/api/admin/partner-users
check "GET /products"                200 "${A[@]}" https://admin.apigw.com/api/admin/products
check "GET /pages"                   200 "${A[@]}" https://admin.apigw.com/api/admin/pages

echo "--- authentication and authorisation"
check "no token is rejected"         401 --resolve admin.apigw.com:443:127.0.0.1 https://admin.apigw.com/api/admin/apis
check "partner token cannot read audit" 403 --resolve admin.apigw.com:443:127.0.0.1 \
      -H "Authorization: Bearer $(node "$TOOLS/mint-token.js" someone@partner.in PARTNER)" \
      https://admin.apigw.com/api/admin/audit
check "unknown id gives 404"         404 "${A[@]}" https://admin.apigw.com/api/admin/partners/00000000-0000-0000-0000-000000000000

echo "--- sign-in surface (developer portal)"
check "captcha is issued"            200 "${D[@]}" -X POST https://developer.apigw.com/api/auth/captcha

echo "--- gateways (401 = route live, key required)"
check "sandbox gateway"              401 --resolve sandbox-api.apigw.com:443:127.0.0.1 https://sandbox-api.apigw.com/v1/accounts/balance
check "production gateway"           401 --resolve api.apigw.com:443:127.0.0.1 https://api.apigw.com/v1/accounts/balance

echo "--- unknown host is refused outright"
code=$(curl -s -o /dev/null -w "%{http_code}" --ssl-no-revoke -k --resolve nope.apigw.com:443:127.0.0.1 https://nope.apigw.com/ 2>/dev/null)
if [ "$code" = "000" ]; then printf "  ok    %-52s connection closed\n" "unknown hostname"; pass=$((pass+1));
else printf "  FAIL  %-52s got %s\n" "unknown hostname" "$code"; fail=$((fail+1)); fi

echo
echo "passed $pass, failed $fail"
exit $((fail > 0 ? 1 : 0))
