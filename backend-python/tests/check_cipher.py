"""Phase 4 gate, first half: the cipher reads what backend-java already wrote.

This runs before any code here encrypts anything. The IPV salts in the database were sealed by the
Java service; a cipher that round-trips its own output but cannot open Java's would look perfectly
healthy until a partner asked for their salt, by which time new rows would be unreadable too.

So the order is deliberate: decrypt existing rows first, compare against what Java itself reveals,
and only then check that Java can read what this cipher writes.

Revealing a salt is an audited admin action by design, so this leaves audit rows behind. It changes
no partner data.
"""

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from app.crypto import SecretCipher  # noqa: E402
from parity import _token  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JAVA = "http://127.0.0.1:18088"
TOKEN = _token(["ADMIN"])
infra_env = (ROOT / "infra" / ".env").read_text(encoding="utf-8")

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{JAVA}{path}", data=data, method=method)
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


# The container stack leaves CRYPTO_MASTER_KEY empty, so both services use the built-in development
# key. If a real key is ever set, it must be set here too or nothing below can decrypt.
master_key = re.search(r"^CRYPTO_MASTER_KEY=(.*)$", infra_env, re.M)
cipher = SecretCipher(master_key.group(1).strip() if master_key else "")

print("--- the key itself")
check("the development key is the first 32 bytes of the Java source string",
      cipher._key == b"apigw-local-development-master-key"[:32],  # noqa: SLF001
      repr(cipher._key))  # noqa: SLF001

print("--- decrypting rows backend-java wrote")
rows = [r for r in psql(
    "select id || '|' || coalesce(ipv_salt_cipher,'') from partner"
    " where ipv_salt_cipher is not null order by code;"
).splitlines() if "|" in r]
check("there are stored salts to read", len(rows) > 0, f"{len(rows)} rows")

decrypted: dict[str, str] = {}
for row in rows:
    partner_id, stored = row.split("|", 1)
    try:
        decrypted[partner_id] = cipher.decrypt(stored)
        check(f"decrypted the salt for {partner_id[:8]}", True)
    except Exception as exc:  # noqa: BLE001
        check(f"decrypted the salt for {partner_id[:8]}", False, str(exc))

print("--- against what java itself reveals")
for partner_id, plaintext in decrypted.items():
    code, revealed = call("POST", f"/api/admin/partners/{partner_id}/ipv-salt/reveal")
    if code != 200:
        check(f"java revealed the salt for {partner_id[:8]}", False, f"{code} {revealed}")
        continue
    check(f"python read exactly what java reveals for {partner_id[:8]}",
          revealed["ipvSalt"] == plaintext,
          "the two differ")

print("--- the masked form the portals show")
masked_rows = [r for r in psql(
    "select id || '|' || coalesce(ipv_salt_masked,'') from partner"
    " where ipv_salt_cipher is not null order by code;"
).splitlines() if "|" in r]
for row in masked_rows:
    partner_id, masked = row.split("|", 1)
    plaintext = decrypted.get(partner_id)
    if plaintext is None:
        continue
    # Whatever the masking rule is, the masked form must not be the secret itself.
    check(f"the masked salt for {partner_id[:8]} is not the plaintext",
          masked != plaintext and plaintext not in masked, f"masked={masked}")

print("--- round trip, both directions")
sample = "a-salt-with-unicode-₹-and-symbols-!@#$%^&*()"
sealed = cipher.encrypt(sample)
check("the stored form carries the v1 prefix", sealed.startswith("v1:"), sealed[:16])
check("python reads back its own output", cipher.decrypt(sealed) == sample)
check("each encryption uses a fresh IV", cipher.encrypt(sample) != sealed)

# Java reading python's output is proved through the live service in check_partner_writes.py, once
# the write path exists; here the layout is asserted directly.
import base64  # noqa: E402

raw = base64.b64decode(sealed[3:])
check("the layout is iv(12) + ciphertext + tag(16)",
      len(raw) == 12 + len(sample.encode()) + 16, f"{len(raw)} bytes")

print()
print("FAILED" if failures else "all cipher checks passed")
sys.exit(1 if failures else 0)
