"""AES-256-GCM for the few secrets the platform must be able to read back.

Today that is the organizations' IPV salt (BRD 6.2: sensitive values are encrypted at rest, never
stored in plain text). Values nobody ever needs back — security keys — are hashed instead, and this
module is deliberately not used for them.

The stored form is `v1:base64(iv ‖ ciphertext ‖ tag)`: a 12-byte IV, then what AES-GCM produced with
its 16-byte tag appended. That is the layout backend-java writes, and this must read it byte for
byte: the data in the database was encrypted by that service, and a cipher that round-trips its own
output while failing on Java's would look healthy until a partner asked for their salt.
"""

import base64
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .settings import get_settings

log = logging.getLogger(__name__)

PREFIX = "v1:"
IV_BYTES = 12
KEY_BYTES = 32

# backend-java copies the first 32 bytes of this 34-character string into the key. Taking the whole
# string, or encoding it differently, produces a key that cannot read a single existing row.
_DEV_KEY_SOURCE = b"apigw-local-development-master-key"


class SecretCipher:
    def __init__(self, master_key: str | None = None) -> None:
        self._key = _read_key(
            master_key if master_key is not None else get_settings().crypto_master_key
        )

    def encrypt(self, plaintext: str) -> str:
        iv = os.urandom(IV_BYTES)
        sealed = AESGCM(self._key).encrypt(iv, plaintext.encode("utf-8"), None)
        return PREFIX + base64.b64encode(iv + sealed).decode("ascii")

    def decrypt(self, stored: str | None) -> str:
        if stored is None or not stored.startswith(PREFIX):
            raise ValueError(f"Stored secret is not in the expected {PREFIX} format")
        raw = base64.b64decode(stored[len(PREFIX) :])
        try:
            return AESGCM(self._key).decrypt(raw[:IV_BYTES], raw[IV_BYTES:], None).decode("utf-8")
        except InvalidTag as exc:
            raise ValueError("Unable to decrypt secret — has the master key changed?") from exc


def _read_key(configured: str | None) -> bytes:
    settings = get_settings()
    if not configured or not configured.strip():
        if settings.environment == "production":
            raise ValueError(
                "CRYPTO_MASTER_KEY must be set in production: 32 random bytes, base64-encoded"
            )
        log.warning(
            "CRYPTO_MASTER_KEY is not set — using the built-in DEVELOPMENT key. "
            "Stored secrets are not protected. Set it outside local development."
        )
        return _DEV_KEY_SOURCE[:KEY_BYTES]

    try:
        decoded = base64.b64decode(configured.strip(), validate=True)
    except Exception as exc:  # noqa: BLE001 - any decoding failure is the same misconfiguration
        raise ValueError("CRYPTO_MASTER_KEY must be base64-encoded") from exc
    if len(decoded) != KEY_BYTES:
        raise ValueError(
            f"CRYPTO_MASTER_KEY must decode to {KEY_BYTES} bytes (AES-256); got {len(decoded)}"
        )
    return decoded
