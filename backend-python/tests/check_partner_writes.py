"""Phase 4 gate, second half: an organization registered by either service is readable by the other.

The cipher is proved separately in check_cipher.py, against rows backend-java wrote. This proves the
rest of the write path: the Client ID and code it derives, the RSA pair and its fingerprint, and —
the part that matters most — that a salt sealed by Python can be revealed by Java, and the reverse.

Everything it creates is removed, including the gateway consumers.
"""

import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cryptography.hazmat.primitives import serialization  # noqa: E402
from parity import _token, diff  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JAVA = "http://127.0.0.1:18088"
PYTHON = "http://127.0.0.1:18090"
TOKEN = _token(["ADMIN"])
infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")

failures = 0
created_partners: list[str] = []
created_groups: list[str] = []


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


try:
    print("--- a group to register into")
    code, group = call(PYTHON, "POST", "/api/admin/partner-groups",
                       {"name": "ZZ Parity Group", "description": "temporary"})
    check("python creates a partner group", code == 201 and group.get("id"), f"{code} {group}")
    created_groups.append(group["id"])

    _, groups_java = call(JAVA, "GET", "/api/admin/partner-groups")
    _, groups_python = call(PYTHON, "GET", "/api/admin/partner-groups")
    d = diff(groups_java, groups_python)
    check("group lists match", not d, "; ".join(d[:4]))

    print("--- registering an organization")
    for service, base in (("java", JAVA), ("python", PYTHON)):
        code, issued = call(base, "POST", "/api/admin/partners", {
            "name": f"ZZ Parity {service.title()} Pvt Ltd",
            "groupId": group["id"],
            "contactEmail": f"zz-{service}@parity-check.test",
        })
        if code != 201 or not issued.get("partner"):
            check(f"{service} registers an organization", False, f"{code} {issued}")
            continue
        check(f"{service} registers an organization", True)
        partner = issued["partner"]
        created_partners.append(partner["id"])

        check(f"{service}: the Client ID drops the company suffix",
              partner["clientIdSandbox"] == f"zz-parity-{service}-sbx",
              partner["clientIdSandbox"])
        check(f"{service}: the code is sequential", re.fullmatch(r"PTN-\d{5}", partner["code"]) is not None,
              partner["code"])
        check(f"{service}: starts UAT-only with no production Client ID",
              partner["accessTier"] == "UAT_ONLY" and partner["clientIdProduction"] is None)
        check(f"{service}: returns the private key once",
              issued["privateKeyPem"].startswith("-----BEGIN PRIVATE KEY-----"),
              issued["privateKeyPem"][:40])
        check(f"{service}: the private key is not stored",
              "PRIVATE" not in psql(f"select coalesce(signature_public_key,'') from partner where id='{partner['id']}';"))

        # The fingerprint must be the SHA-256 of the DER public key, as both services compute it.
        public_key = serialization.load_pem_public_key(issued["publicKeyPem"].encode())
        der = public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        expected = "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode().rstrip("=")
        check(f"{service}: the fingerprint matches the public key",
              partner["signatureFingerprint"] == expected,
              f"{partner['signatureFingerprint']} vs {expected}")
        check(f"{service}: the masked salt hides the secret",
              partner["ipvSaltMasked"].startswith("ipv_•") and
              partner["ipvSaltMasked"].endswith(issued["ipvSalt"][-4:]),
              partner["ipvSaltMasked"])

        # The decisive one: the other service must be able to open what this one sealed.
        other, other_name = (PYTHON, "python") if service == "java" else (JAVA, "java")
        code, revealed = call(other, "POST", f"/api/admin/partners/{partner['id']}/ipv-salt/reveal")
        check(f"{other_name} reveals the salt {service} sealed",
              code == 200 and revealed.get("ipvSalt") == issued["ipvSalt"],
              f"{code} {revealed}")

        _, from_java = call(JAVA, "GET", f"/api/admin/partners/{partner['id']}")
        _, from_python = call(PYTHON, "GET", f"/api/admin/partners/{partner['id']}")
        d = diff(from_java, from_python)
        check(f"{service}-registered organization reads identically on both", not d, "; ".join(d[:5]))

    print("--- editing, tier and credentials")
    if created_partners:
        target = created_partners[-1]
        code, updated = call(PYTHON, "PUT", f"/api/admin/partners/{target}",
                             {"name": "ZZ Parity Renamed", "contactEmail": "zz-renamed@parity-check.test"})
        check("python updates the organization details",
              code == 200 and updated["name"] == "ZZ Parity Renamed", f"{code} {updated}")

        code, promoted = call(PYTHON, "PUT", f"/api/admin/partners/{target}/access-tier",
                              {"accessTier": "PRODUCTION"})
        check("python grants production access and issues a production Client ID",
              code == 200 and promoted["accessTier"] == "PRODUCTION"
              and promoted["clientIdProduction"], f"{code} {promoted}")

        code, same = call(PYTHON, "PUT", f"/api/admin/partners/{target}/access-tier",
                          {"accessTier": "PRODUCTION"})
        check("granting it twice is a no-op", code == 200, f"{code} {same}")

        code, problem = call(PYTHON, "PUT", f"/api/admin/partners/{target}/access-tier",
                             {"accessTier": "UAT_ONLY"})
        check("python refuses to withdraw production access rather than half-doing it",
              code == 501 and problem.get("code") == "NOT_MIGRATED", f"{code} {problem}")
        code, problem = call(PYTHON, "PUT", f"/api/admin/partners/{target}/status",
                             {"status": "DISABLED"})
        check("python refuses to disable an organization for the same reason",
              code == 501 and problem.get("code") == "NOT_MIGRATED", f"{code} {problem}")

        before = psql(f"select signature_fingerprint from partner where id='{target}';")
        code, regenerated = call(PYTHON, "POST", f"/api/admin/partners/{target}/signature")
        after = psql(f"select signature_fingerprint from partner where id='{target}';")
        check("python recreates the signature pair",
              code == 200 and before != after
              and regenerated["privateKeyPem"].startswith("-----BEGIN PRIVATE KEY-----"),
              f"{code} {before} -> {after}")

        code, rotated = call(PYTHON, "POST", f"/api/admin/partners/{target}/ipv-salt")
        check("python rotates the IPV salt", code == 200 and rotated["ipvSalt"].startswith("ipv_"),
              f"{code} {rotated}")
        code, revealed = call(JAVA, "POST", f"/api/admin/partners/{target}/ipv-salt/reveal")
        check("java reveals the rotated salt python sealed",
              code == 200 and revealed["ipvSalt"] == rotated["ipvSalt"], f"{code} {revealed}")

        _, from_java = call(JAVA, "GET", f"/api/admin/partners/{target}")
        _, from_python = call(PYTHON, "GET", f"/api/admin/partners/{target}")
        d = diff(from_java, from_python)
        check("after every change it still reads identically", not d, "; ".join(d[:5]))

    _, list_java = call(JAVA, "GET", "/api/admin/partners")
    _, list_python = call(PYTHON, "GET", "/api/admin/partners")
    d = diff(list_java, list_python)
    check("partner lists match", not d, "; ".join(d[:5]))

finally:
    print("--- cleanup")
    for partner_id in created_partners:
        psql(f"delete from product_assignment where partner_id = '{partner_id}';")
        psql(f"delete from partner_user where partner_id = '{partner_id}';")
        psql(f"delete from security_key where partner_id = '{partner_id}';")
        psql(f"delete from partner where id = '{partner_id}';")
        print(f"  removed partner {partner_id}")
    for group_id in created_groups:
        psql(f"delete from partner_group where id = '{group_id}';")
        print(f"  removed group {group_id}")

    left = psql("select count(*) from partner where name like 'ZZ Parity%';")
    check("no test organizations left behind", left.endswith("0"), left)
    left = psql("select count(*) from partner_group where name like 'ZZ Parity%';")
    check("no test groups left behind", left.endswith("0"), left)

print()
print("FAILED" if failures else "all partner write checks passed")
sys.exit(1 if failures else 0)
