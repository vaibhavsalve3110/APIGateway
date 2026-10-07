"""Phase 5 gate: a rotation issues a working key, overlaps the old one, and tells everyone it should.

What makes this phase dangerous is that a key is only as good as the gateway's copy of its hash. A
key row written without the matching gateway credential looks perfect in the portal and fails every
call; the reverse leaves a credential the platform cannot account for. So every check here looks at
both sides.

The notices are asserted from the service log rather than from a mailbox: outbound SMTP is blocked on
this network, so the Mailer logs them instead of sending. That proves who would be told and what they
would be told, which is the part that could be wrong.

A throwaway organization is registered for this and removed afterwards, together with its keys and
gateway consumers. No existing partner's keys are touched.
"""

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token, diff  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
TOKEN = _token(["ADMIN"])
infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")


def env_value(key: str, fallback: str) -> str:
    m = re.search(rf"^{key}=(.*)$", infra_env, re.M)
    return (m.group(1).strip() or fallback) if m else fallback


APISIX = {
    "SANDBOX": ("http://127.0.0.1:9180", env_value("APISIX_SANDBOX_ADMIN_KEY", "change-me-sandbox-admin-key")),
    "PRODUCTION": ("http://127.0.0.1:9181", env_value("APISIX_PRODUCTION_ADMIN_KEY", "change-me-production-admin-key")),
}

failures = 0
partner_id = None
group_id = None


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def call(base: str, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw


def gateway_credential(environment: str, client_id: str, key_id: str):
    base, key = APISIX[environment]
    request = urllib.request.Request(
        f"{base}/apisix/admin/consumers/{client_id}/credentials/{key_id}"
    )
    request.add_header("X-API-KEY", key)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return body.get("value", body)


def psql(sql: str) -> str:
    password = re.search(r"^DB_PASSWORD=(.*)$", infra_env, re.M).group(1).strip()
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "host",
         "-e", f"PGPASSWORD={password}", "-e", "PGOPTIONS=--search_path=apim",
         "postgres:17-alpine", "psql",
         "postgresql://apigw@host.docker.internal:5432/apigw", "-Atc", sql],
        capture_output=True, text=True, timeout=180,
    )
    return (result.stdout + result.stderr).strip()


def python_log(since_marker: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "logs", "backend-python", "--tail", "400"],
        cwd=ROOT / "infra", capture_output=True, text=True, timeout=180,
    )
    out = result.stdout + result.stderr
    return out.split(since_marker)[-1] if since_marker in out else out


try:
    print("--- a throwaway organization")
    _, group = call(PYTHON, "POST", "/api/admin/partner-groups", {"name": "ZZ Keys Group"})
    group_id = group["id"]
    _, issued = call(PYTHON, "POST", "/api/admin/partners",
                     {"name": "ZZ Keys Fintech", "groupId": group_id,
                      "contactEmail": "zz-keys@parity-check.test"})
    partner = issued["partner"]
    partner_id = partner["id"]
    check("registered", bool(partner_id))

    # Two users, because the notices differ by role: the key itself goes only to Partner Admins,
    # the change notice to everyone. With no users at all nobody is told and nothing is asserted.
    for full_name, email, role in (
        ("ZZ Keys Admin", "zz-keys-admin@parity-check.test", "PARTNER_ADMIN"),
        ("ZZ Keys Dev", "zz-keys-dev@parity-check.test", "PARTNER_DEVELOPER"),
    ):
        code, _ = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/users",
                       {"fullName": full_name, "email": email, "role": role})
        check(f"added {role}", code == 200, str(code))

    print("--- the first key")
    code, first = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/keys/SANDBOX")
    check("python issues a sandbox key", code == 201 and first.get("plaintext"), f"{code} {first}")
    check("the key is prefixed for its environment",
          first["plaintext"].startswith("agw_sbx_"), first["plaintext"][:12])
    check("nothing but a hash is stored",
          psql(f"select count(*) from security_key where key_hash = '{first['plaintext']}';").endswith("0"))
    check("the masked form hides it",
          first["key"]["maskedKey"].endswith(first["plaintext"][-4:])
          and "•" in first["key"]["maskedKey"], first["key"]["maskedKey"])
    check("there is no previous key to expire", first["previousKeyExpiresAt"] is None)

    credential = gateway_credential("SANDBOX", first["clientId"], first["key"]["id"])
    check("the gateway holds a credential for it", credential is not None)
    if credential:
        import hashlib
        expected = hashlib.sha256(first["plaintext"].encode()).hexdigest()
        check("the gateway holds the hash, never the key",
              credential["plugins"]["key-auth"]["key"] == expected,
              credential["plugins"]["key-auth"]["key"][:16])

    print("--- rotating, and the overlap")
    marker = "ROTATION-MARKER-1"
    code, second = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/keys/SANDBOX")
    check("python rotates", code == 201 and second["plaintext"] != first["plaintext"], f"{code}")
    check("the previous key is given an expiry", second["previousKeyExpiresAt"] is not None)

    _, keys_python = call(PYTHON, "GET", f"/api/admin/partners/{partner_id}/keys")
    _, keys_java = call(JAVA, "GET", f"/api/admin/partners/{partner_id}/keys")
    d = [x for x in diff(keys_java, keys_python) if not x.endswith("secondsRemaining")]
    check("both services read the key list identically", not d, "; ".join(d[:5]))

    statuses = {k["id"]: k["status"] for k in keys_python}
    check("the new key is active and the old one expiring",
          statuses[second["key"]["id"]] == "ACTIVE" and statuses[first["key"]["id"]] == "EXPIRING",
          json.dumps(statuses))
    check("the old key still has a gateway credential during the overlap",
          gateway_credential("SANDBOX", first["clientId"], first["key"]["id"]) is not None)

    code, problem = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/keys/SANDBOX")
    check("a second rotation inside the window is refused",
          code == 409 and problem.get("code") == "ROTATION_WINDOW_OPEN", f"{code} {problem}")
    code, problem = call(JAVA, "POST", f"/api/admin/partners/{partner_id}/keys/SANDBOX")
    check("java refuses it the same way",
          code == 409 and problem.get("code") == "ROTATION_WINDOW_OPEN", f"{code} {problem}")

    print("--- who was told")
    log = python_log(marker)
    check("the Partner Admins would get the key itself",
          "Your new sandbox security key" in log, "notice not found in the log")
    check("everyone in the organisation would be told it changed",
          "Security key changed for ZZ Keys Fintech" in log, "notice not found")
    check("the APIM Admin team would be told which organisation rotated",
          "Key rotation: ZZ Keys Fintech" in log, "notice not found")
    change_notice = log.split("Security key changed for")[-1][:1200] if "Security key changed for" in log else ""
    check("the broadcast carries no key",
          second["plaintext"] not in change_notice, "the key appeared in the broadcast")
    check("the broadcast says who to contact",
          "contact the APIM Admin team immediately" in change_notice, "wording missing")

    print("--- undoing a rotation")
    code, revoked = call(PYTHON, "POST", f"/api/admin/keys/{second['key']['id']}/revoke")
    check("python revokes the new key inside the window",
          code == 200 and revoked["status"] == "REVOKED", f"{code} {revoked}")
    _, keys_now = call(PYTHON, "GET", f"/api/admin/partners/{partner_id}/keys")
    statuses = {k["id"]: k["status"] for k in keys_now}
    check("the previous key is reinstated as active",
          statuses[first["key"]["id"]] == "ACTIVE", json.dumps(statuses))
    check("the revoked key's gateway credential is gone",
          gateway_credential("SANDBOX", first["clientId"], second["key"]["id"]) is None)
    code, problem = call(PYTHON, "POST", f"/api/admin/keys/{second['key']['id']}/revoke")
    check("revoking again is refused",
          code == 409 and problem.get("code") == "REVOKE_WINDOW_CLOSED", f"{code} {problem}")

    print("--- production keys follow the access tier")
    code, problem = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/keys/PRODUCTION")
    check("a UAT-only organization cannot have a production key",
          code == 403 and problem.get("code") == "PRODUCTION_NOT_PROVISIONED", f"{code} {problem}")
    code, promoted = call(PYTHON, "PUT", f"/api/admin/partners/{partner_id}/access-tier",
                          {"accessTier": "PRODUCTION"})
    check("granted production access", code == 200, f"{code}")
    code, prod_key = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/keys/PRODUCTION")
    check("python issues a production key", code == 201 and prod_key["plaintext"].startswith("agw_prd_"),
          f"{code}")

    print("--- withdrawing access revokes the keys it covers")
    code, demoted = call(PYTHON, "PUT", f"/api/admin/partners/{partner_id}/access-tier",
                         {"accessTier": "UAT_ONLY"})
    check("python withdraws production access", code == 200 and demoted["accessTier"] == "UAT_ONLY",
          f"{code} {demoted}")
    _, keys_now = call(PYTHON, "GET", f"/api/admin/partners/{partner_id}/keys")
    statuses = {k["id"]: k["status"] for k in keys_now}
    check("the production key is revoked", statuses[prod_key["key"]["id"]] == "REVOKED",
          json.dumps(statuses))
    check("the sandbox key is untouched", statuses[first["key"]["id"]] == "ACTIVE",
          json.dumps(statuses))
    check("its gateway credential is gone",
          gateway_credential("PRODUCTION", prod_key["clientId"], prod_key["key"]["id"]) is None)

    print("--- disabling revokes everything")
    code, disabled = call(PYTHON, "PUT", f"/api/admin/partners/{partner_id}/status",
                          {"status": "DISABLED"})
    check("python disables the organization", code == 200 and disabled["status"] == "DISABLED",
          f"{code} {disabled}")
    _, keys_now = call(PYTHON, "GET", f"/api/admin/partners/{partner_id}/keys")
    check("no key is left live", all(k["status"] not in ("ACTIVE", "EXPIRING") for k in keys_now),
          json.dumps({k["id"][:8]: k["status"] for k in keys_now}))
    code, problem = call(PYTHON, "POST", f"/api/admin/partners/{partner_id}/keys/SANDBOX")
    check("a disabled organization cannot be issued a key",
          code == 409 and problem.get("code") == "PARTNER_DISABLED", f"{code} {problem}")

finally:
    print("--- cleanup")
    if partner_id:
        rows = psql(
            "select environment || '|' || id || '|' || "
            "(select coalesce(client_id_sandbox,'') from partner where id = security_key.partner_id) || '|' || "
            "(select coalesce(client_id_production,'') from partner where id = security_key.partner_id) "
            f"from security_key where partner_id = '{partner_id}';"
        )
        for row in rows.splitlines():
            if row.count("|") != 3:
                continue
            environment, key_id, sandbox_client, production_client = row.split("|")
            client = production_client if environment == "PRODUCTION" else sandbox_client
            if not client:
                continue
            base, key = APISIX[environment]
            request = urllib.request.Request(
                f"{base}/apisix/admin/consumers/{client}/credentials/{key_id}", method="DELETE"
            )
            request.add_header("X-API-KEY", key)
            try:
                urllib.request.urlopen(request, timeout=15)  # noqa: S310
            except urllib.error.HTTPError:
                pass
        psql(f"delete from partner_user where partner_id = '{partner_id}';")
        psql(f"delete from security_key where partner_id = '{partner_id}';")
        psql(f"delete from partner where id = '{partner_id}';")
        print(f"  removed partner {partner_id} and its keys")
    if group_id:
        psql(f"delete from partner_group where id = '{group_id}';")

    left = psql("select count(*) from partner where name like 'ZZ Keys%';")
    check("no test organization left behind", left.endswith("0"), left)

print()
print("FAILED" if failures else "all key lifecycle checks passed")
sys.exit(1 if failures else 0)
