"""Hybrid encryption for portal request and response payloads (VAPT: payload confidentiality).

This sits **on top of** TLS, it does not replace it. What it buys is that a payload is unreadable in
an intercepting proxy, which is how these findings are raised and reproduced, and that bodies are not
sitting in plaintext in proxy logs, browser devtools or a TLS-terminating load balancer's buffers.
What it does not buy is confidentiality against someone who controls the browser: the public key is
public, so anyone can encrypt, and the page itself can always read its own cleartext. It is
defence-in-depth, and the honest way to describe it to an auditor.

## The envelope

Per request, the client makes a fresh AES-256 key, wraps it with the server's RSA public key, and
sends it in a header. Bodies and responses are AES-256-GCM under that key.

    X-Encrypted:     v1
    X-Encrypt-Kid:   <which public key was used>
    X-Encrypt-Key:   base64( RSA-OAEP-SHA256( 32-byte AES key ) )

    body (when there is one), and every response:
    {"iv": "<base64 12 bytes>", "data": "<base64 ciphertext||16-byte tag>"}

The key travels in a header rather than in the body so that one code path covers every method: a GET
has no body to carry it, but its *response* still has to be encrypted.

The response reuses the request's AES key with a **freshly generated IV**. Reusing a key is safe for
GCM only while no IV ever repeats under it, which is why the IV is random per message and never
derived from anything. One key per request bounds the exposure: it is discarded afterwards and never
stored.

RSA-OAEP with SHA-256 (not PKCS#1 v1.5, which is padding-oracle-prone) and AES-256-GCM (authenticated,
so a tampered body fails to decrypt rather than decoding into something attacker-chosen).

## One keypair, both services

nginx routes portal traffic between backend-java and backend-python per method and path, so a request
the portal encrypted with one public key may land on either service. **Both must therefore hold the
same private key** — which is why it is configured rather than generated at startup. Outside
production it falls back to the development keypair below, exactly as AUTH_JWT_SECRET and the crypto
master key already do, so a developer machine needs no setup and the two services still agree.

Query strings are deliberately *not* encrypted: see the note in `middleware.py`.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..settings import get_settings

VERSION = "v1"
HEADER_VERSION = "X-Encrypted"
HEADER_KEY = "X-Encrypt-Key"
HEADER_KID = "X-Encrypt-Kid"

AES_KEY_BYTES = 32  # AES-256
IV_BYTES = 12  # 96 bits, the size GCM is defined for


class PayloadCryptoError(Exception):
    """A payload could not be unwrapped, decrypted or authenticated."""


# A 2048-bit development keypair, shared by backend-java and backend-python so that either can read
# what the portal encrypted on a developer machine. It is in the repository on purpose and is
# worthless: anything encrypted to it can be read by anyone who has this file. Production must set
# PAYLOAD_PRIVATE_KEY, and the services refuse to start under that profile without it.
DEV_PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDI5tZwMEQvwJKY
D73Y7DBAoNnhiIrfHpw5k64Ysp/sRggCd+w6RC8o7HP2hmhTgP9lYKbmEWiRVvP4
r96AdetLxcoJK289EfEMLooR0qw1PRf483zgdmtG7U+pBIUnOlw44ffQq4W6x2B7
Km14ckn3Vr6PEWJHyQBe8cupqJmWmMV0MvubkaYmS+R5mWTYvwAJFfuV2XMC6jL3
e7eewkUVgPtbmfsVyTy2f4/zXycOYihzWnz510udrarMjcibUo5wCNYkfDufJwFw
N1Ze714/jZLIE9u1SFXbvvUluOHmWVuJNKYuy/0FIlvZ9ft3gk/u7OYAotzcmJy9
pB/88HVzAgMBAAECggEAHDoStwCRFASClErh6bCFtw7ijgWZPXAXkx9kvqOaRKAy
T+Z5klYyKhXO1TxdPB5Lw/qoeHrJrmIBNVfAc1weCy9nC5LGtlXnAEcprwdimrhS
ve+4A/GfcP+2yZCRBMn2WyekofT3fR62N5fmeZ3VNqNBcuiGXn+nRa/DZbsCmV3t
iR5X3g3Cj3wIrv3zqKrR+whsrq2t9qNfdrHNj7/Nxvan0rnu2JfXBkLQhCZhgtCZ
VIwW4HsMiDP4zSlnZcoBR/B4DUYrKEgNXAB8JfkO8/gUz7VGcaMWiQP8DmHoGVft
lf0WETDSc5toxlHH/LbnL55mDZZcBe7JFdQ41lTzgQKBgQD8TrspbcZlra44lL8u
NuEFP1JRWb2ADK4BmsQk28uuu1Bsmn8SeMzBqhnPar1Gy0ItfzZyXq7i1UGA2GhJ
N0u3AE+s+VhBA30FdjGA2b/kqrAgjoyu3LHhw/2M52YeOYAi1HUO2mTikpkxeFw/
x+Nf+LCxA+thAdEZdd+1IYDQaQKBgQDL14PN1KvfzA+LHWJCA4y5dS38xpu1dIek
9e0Omo6Q04FT/44TeBoSkOfmJpPty9oG0i7YNpKVntEczLe4WfqicpDnZXZ7pur+
wV3oBgqjs1zeUww7HGG8fHCHicdaKPSbvSA6oWOqcwpEWxRUv+NVM7BfW5C9IBhG
4KQ0S19bewKBgQCXRqVVO6pewHnbFuRh0ymrucGjYQkLw455C9BawSYoh8q6sw9J
hgBOhayf/kGqNqhhGwsMG9UD0BVMKXStoWfWO2uKLJ5LrMnDApC/zs8NTYH4oz+a
gFxvHtHhL8S8joFTYMsmsq8WYgtT6/RzkWe03SkjmVQBf9NdTp1ovsO7MQKBgE2j
EudVZfUCIrVohqD/+xwzvkU1W97buEIjDJvwT/ZnKC3W+sT9jGif2kM1VEhQyQSq
Dv94oZHtAFZIvnyvgJ9YpUoMwfjMlVpcSajyjCDXUrq2xMTKxYrllnJ5Dn2PdcLP
YLQT/gLQeAua6P5ya2JrInTfShxOWhC8xK3KO1J7AoGATdRejtygOrjQ+QXA/CWY
OYsw/u+8gcDhNgP5mE9EMmVZAcSzQgKEt95mZvjzF3500ITMBEnYJgembwzzGvgy
wqQ8YKhQT+8SGE3j19soRhfp4+mNjedxfZcPyXH/PlEfNhX08/BCVoGY0HXdL9d1
ErK2Jl64GuR24BtdZGg+iyU=
-----END PRIVATE KEY-----"""


def _load_private_key(pem: str) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise PayloadCryptoError("PAYLOAD_PRIVATE_KEY is not an RSA private key")
    if key.key_size < 2048:
        raise PayloadCryptoError(f"PAYLOAD_PRIVATE_KEY is {key.key_size}-bit; 2048 is the minimum")
    return key


@lru_cache(maxsize=1)
def private_key() -> rsa.RSAPrivateKey:
    settings = get_settings()
    pem = settings.payload_private_key.strip()
    if not pem:
        if settings.environment == "production":
            # Falling back to a published keypair in production would make the whole mechanism
            # theatre, so this is fatal rather than a warning nobody reads.
            raise PayloadCryptoError(
                "PAYLOAD_PRIVATE_KEY must be set in production: it decrypts every portal payload"
            )
        pem = DEV_PRIVATE_KEY_PEM
    # A PEM in an environment variable usually arrives with its newlines escaped.
    return _load_private_key(pem.replace("\\n", "\n"))


@lru_cache(maxsize=1)
def public_key_pem() -> str:
    return (
        private_key()
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


@lru_cache(maxsize=1)
def key_id() -> str:
    """A short, stable name for the current public key, so a rotation is detectable.

    Same construction as the partner signature fingerprints: SHA-256 over the DER public key. The
    client echoes it back in X-Encrypt-Kid, which turns "decryption failed" into "you used the
    previous key" — the difference between a five-minute fix and an afternoon.
    """
    der = (
        private_key()
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return "sha256-" + base64.urlsafe_b64encode(hashlib.sha256(der).digest()).decode().rstrip("=")[:16]


def unwrap_key(wrapped_b64: str) -> bytes:
    """Recover the request's AES key from the RSA-wrapped value in X-Encrypt-Key."""
    try:
        wrapped = base64.b64decode(wrapped_b64, validate=True)
    except Exception as exc:
        raise PayloadCryptoError("X-Encrypt-Key is not valid base64") from exc
    try:
        key = private_key().decrypt(
            wrapped,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    except Exception as exc:
        # Deliberately not reporting *why*: distinguishing bad padding from a wrong key is what a
        # padding oracle is built out of. The client gets one message for every failure here.
        raise PayloadCryptoError("the encrypted key could not be unwrapped") from exc
    if len(key) != AES_KEY_BYTES:
        raise PayloadCryptoError(f"the unwrapped key is {len(key)} bytes; expected {AES_KEY_BYTES}")
    return key


def decrypt(aes_key: bytes, iv_b64: str, data_b64: str) -> bytes:
    try:
        iv = base64.b64decode(iv_b64, validate=True)
        data = base64.b64decode(data_b64, validate=True)
    except Exception as exc:
        raise PayloadCryptoError("iv or data is not valid base64") from exc
    if len(iv) != IV_BYTES:
        raise PayloadCryptoError(f"iv is {len(iv)} bytes; expected {IV_BYTES}")
    try:
        return AESGCM(aes_key).decrypt(iv, data, None)
    except Exception as exc:
        # GCM authenticates, so this also fires when the body was altered in transit.
        raise PayloadCryptoError("the payload failed to decrypt or its tag did not verify") from exc


def encrypt(aes_key: bytes, plaintext: bytes) -> dict[str, str]:
    """Encrypt a response under the request's key, with an IV that has never been used with it."""
    iv = os.urandom(IV_BYTES)
    data = AESGCM(aes_key).encrypt(iv, plaintext, None)
    return {
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(data).decode(),
    }
