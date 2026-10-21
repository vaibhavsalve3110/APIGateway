"""Where the portals get the public key they encrypt to.

Unauthenticated and exempt from encryption itself, necessarily: a client cannot encrypt its first
request until it has this, and it has no session yet either. Nothing here is a secret — a public key
is public, and publishing it is what lets a browser use it.
"""

from typing import Any

from fastapi import APIRouter

from ..common import payload_crypto as pc

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


@router.get("/public-key")
async def public_key() -> dict[str, Any]:
    """The RSA public key for payload encryption, and how to use it.

    `kid` names this key. Send it back in `X-Encrypt-Kid` and a decryption failure can be reported as
    "you used the previous key" rather than a flat refusal, which is the difference between a reload
    and an afternoon of debugging.

    backend-java serves the same key: nginx may route an encrypted request to either service, so both
    hold the same keypair.
    """
    return {
        "kid": pc.key_id(),
        "algorithm": "RSA-OAEP-256",
        "publicKeyPem": pc.public_key_pem(),
        "payload": {
            "cipher": "AES-256-GCM",
            "ivBytes": pc.IV_BYTES,
            "keyBytes": pc.AES_KEY_BYTES,
            "envelope": {"iv": "base64(iv)", "data": "base64(ciphertext||tag)"},
            "headers": {
                pc.HEADER_VERSION: pc.VERSION,
                pc.HEADER_KID: "the kid above",
                pc.HEADER_KEY: "base64(RSA-OAEP-SHA256(32-byte AES key))",
            },
        },
    }
