"""Gate: hybrid payload encryption, end to end against the running service.

Acts as the portal does — fetch the public key, wrap a fresh AES-256 key with it, send the body as
AES-256-GCM, decrypt the reply — and then tries the things a VAPT tester tries.

What matters here, in order of how badly it would hurt to get it wrong:

* an encrypted request must produce an encrypted reply that decrypts to the same JSON an
  unencrypted call returns. If the two differ, the encryption changed the contract.
* **a tampered payload must be refused.** GCM authenticates; if a flipped byte decrypts anyway, the
  mode is wrong and the whole thing is decoration.
* **every IV must be unique.** Reusing one under the same key loses GCM's confidentiality outright.
* **error bodies must be encrypted too.** A 403 or a validation failure that answers in plaintext
  leaks exactly the field names and detail the exercise was meant to cover.
* a wrong or stale key, a bad envelope and an unsupported version must each fail in a way that says
  which, in plaintext — a client that got the envelope wrong cannot read an encrypted explanation.

Needs the stack up. Run:  python tests/check_payload_crypto.py
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from parity import _token  # noqa: E402

PYTHON = "http://127.0.0.1:18090"
JAVA = "http://127.0.0.1:18088"
TOKEN = _token(["ADMIN"])

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  ok    {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" : {detail}" if detail else ""))


def raw(base: str, method: str, path: str, headers: dict[str, str], body: bytes | None = None):
    """Returns (status, headers, body).

    The headers come back as the HTTPMessage itself rather than a dict, because ASGI requires a
    server to emit header names in lower case and a plain dict lookup for "X-Encrypted" would then
    miss "x-encrypted" — which looks exactly like the server having failed to set it.
    """
    request = urllib.request.Request(base + path, data=body, method=method)
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


# --------------------------------------------------------------------------- the client's half

print("--- the public key")
status, _, body = raw(PYTHON, "GET", "/api/crypto/public-key", {})
check("the public key is served without a session", status == 200, str(status))
descriptor = json.loads(body)
check("it names a kid", bool(descriptor.get("kid")), str(descriptor.get("kid")))
check("it declares RSA-OAEP-256", descriptor.get("algorithm") == "RSA-OAEP-256")
public_key = serialization.load_pem_public_key(descriptor["publicKeyPem"].encode())
check("the key is 2048-bit or stronger", public_key.key_size >= 2048, f"{public_key.key_size}-bit")
KID = descriptor["kid"]


def wrap(aes_key: bytes, key: object = None) -> str:
    target = key or public_key
    return base64.b64encode(
        target.encrypt(  # type: ignore[attr-defined]
            aes_key,
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
    ).decode()


def seal(payload: dict | None) -> tuple[bytes, dict[str, str], bytes | None]:
    """A fresh key per request, as the portal does. Returns (aes_key, headers, body)."""
    aes_key = os.urandom(32)
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "X-Encrypted": "v1",
        "X-Encrypt-Kid": KID,
        "X-Encrypt-Key": wrap(aes_key),
    }
    body = None
    if payload is not None:
        iv = os.urandom(12)
        data = AESGCM(aes_key).encrypt(iv, json.dumps(payload).encode(), None)
        envelope = {
            "iv": base64.b64encode(iv).decode(),
            "data": base64.b64encode(data).decode(),
        }
        body = json.dumps(envelope).encode()
        headers["Content-Type"] = "application/json"
    return aes_key, headers, body


def open_envelope(aes_key: bytes, body: bytes) -> object:
    envelope = json.loads(body)
    plaintext = AESGCM(aes_key).decrypt(
        base64.b64decode(envelope["iv"]), base64.b64decode(envelope["data"]), None
    )
    return json.loads(plaintext)


# --------------------------------------------------------------------------- the round trip

print()
print("--- an encrypted GET")
aes_key, headers, _ = seal(None)
status, response_headers, body = raw(PYTHON, "GET", "/api/admin/apis", headers)
check("answered 200", status == 200, str(status))
check("the reply says it is encrypted", response_headers.get("X-Encrypted") == "v1")
check("the reply is not readable as JSON on the wire", b'"proxyPath"' not in body)
check("it is not cached", response_headers.get("Cache-Control") == "no-store",
      str(response_headers.get("Cache-Control")))
decrypted = open_envelope(aes_key, body)
check("it decrypts to a list of APIs", isinstance(decrypted, list) and bool(decrypted),
      str(type(decrypted)))

# The decisive one: encryption must not change what the endpoint returns.
status, _, plain = raw(PYTHON, "GET", "/api/admin/apis",
                       {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
check("the decrypted body is identical to the unencrypted one",
      json.loads(plain) == decrypted,
      "they differ — encryption changed the contract")

print()
print("--- unique IVs")
ivs = set()
for _ in range(6):
    k, h, _ = seal(None)
    _, _, b = raw(PYTHON, "GET", "/api/admin/partner-groups", h)
    ivs.add(json.loads(b)["iv"])
check("every response IV is distinct over 6 calls", len(ivs) == 6, f"{len(ivs)} distinct of 6")

print()
print("--- an encrypted write, and its errors")
# A deliberately invalid group: the validation failure must come back encrypted, fields and all.
aes_key, headers, body = seal({"name": "", "description": "x"})
status, response_headers, body = raw(PYTHON, "POST", "/api/admin/partner-groups", headers, body)
check("a validation failure is still a 400", status == 400, str(status))
check("the error body is encrypted, not plaintext", response_headers.get("X-Encrypted") == "v1",
      "an error answered in the clear leaks field names and detail")
problem = open_envelope(aes_key, body)
check("it decrypts to a problem document with a code",
      isinstance(problem, dict) and "code" in problem, str(problem)[:120])

print()
print("--- what a tester tries")

# Tampering. GCM must refuse this; if it does not, the mode is not authenticated.
aes_key, headers, body = seal({"name": "ZZ Crypto Probe"})
envelope = json.loads(body)
data = bytearray(base64.b64decode(envelope["data"]))
data[0] ^= 0x01  # one flipped bit
envelope["data"] = base64.b64encode(bytes(data)).decode()
status, _, body = raw(PYTHON, "POST", "/api/admin/partner-groups", headers,
                      json.dumps(envelope).encode())
check("a tampered payload is refused", status == 400, str(status))
check("and refused for the right reason",
      b"ENCRYPTION_PAYLOAD_INVALID" in body, body[:160].decode(errors="replace"))

# A key this service cannot unwrap.
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
aes_key, headers, _ = seal(None)
headers["X-Encrypt-Key"] = wrap(aes_key, stranger.public_key())
status, _, body = raw(PYTHON, "GET", "/api/admin/apis", headers)
check("a key wrapped to the wrong public key is refused", status == 400, str(status))
check("the refusal is readable, not itself encrypted", b"ENCRYPTION_KEY_INVALID" in body,
      body[:160].decode(errors="replace"))

# A stale kid should be named, because that is the common real failure.
aes_key, headers, _ = seal(None)
headers["X-Encrypt-Key"] = wrap(aes_key, stranger.public_key())
headers["X-Encrypt-Kid"] = "sha256-somethingelse"
_, _, body = raw(PYTHON, "GET", "/api/admin/apis", headers)
check("a stale kid is called out by name", b"not the current one" in body,
      body[:200].decode(errors="replace"))

# Envelope shape.
aes_key, headers, _ = seal(None)
headers["Content-Type"] = "application/json"
status, _, body = raw(PYTHON, "POST", "/api/admin/partner-groups", headers, b'{"nope": 1}')
check("a malformed envelope is refused", status == 400 and b"ENCRYPTION_ENVELOPE_INVALID" in body,
      f"{status} {body[:120].decode(errors='replace')}")

# Version.
aes_key, headers, _ = seal(None)
headers["X-Encrypted"] = "v9"
status, _, body = raw(PYTHON, "GET", "/api/admin/apis", headers)
check("an unknown version is refused", status == 400 and b"ENCRYPTION_VERSION" in body,
      f"{status} {body[:120].decode(errors='replace')}")

# The header without a key.
headers = {"Authorization": f"Bearer {TOKEN}", "X-Encrypted": "v1"}
status, _, body = raw(PYTHON, "GET", "/api/admin/apis", headers)
check("the version header without a key is refused",
      status == 400 and b"ENCRYPTION_KEY_MISSING" in body,
      f"{status} {body[:120].decode(errors='replace')}")

print()
print("--- the exemptions still work")
for path, why in (
    ("/actuator/health", "the health probe"),
    ("/api/crypto/public-key", "the public key itself"),
):
    status, _, _ = raw(PYTHON, "GET", path, {})
    check(f"{why} answers unencrypted", status == 200, str(status))

status, _, _ = raw(PYTHON, "GET", "/v3/api-docs", {})
check("the OpenAPI document answers unencrypted", status == 200, str(status))

print()
print("--- both services share one keypair")
# nginx routes portal traffic to either service, so a payload encrypted once must open on both.
status, _, java_body = raw(JAVA, "GET", "/api/crypto/public-key", {})
if status == 200:
    java_descriptor = json.loads(java_body)
    check("backend-java serves the same kid", java_descriptor.get("kid") == KID,
          f"java={java_descriptor.get('kid')} python={KID}")
    aes_key, headers, _ = seal(None)
    status, response_headers, body = raw(JAVA, "GET", "/api/admin/apis", headers)
    check("backend-java decrypts a payload sealed for python", status == 200, str(status))
    if status == 200 and response_headers.get("X-Encrypted") == "v1":
        check("and its reply decrypts with the same key",
              isinstance(open_envelope(aes_key, body), list))
else:
    print(f"  TODO  backend-java does not serve /api/crypto/public-key yet ({status})")
    print("        portal routes it still owns will answer in plaintext until it does")

print()
print("FAILED" if failures else "all payload encryption checks passed")
sys.exit(1 if failures else 0)
