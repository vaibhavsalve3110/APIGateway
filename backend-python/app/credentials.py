"""The credentials an organization holds: an RSA signature key pair and an IPV salt.

Both are generated here and must match what backend-java produces in *form*, not in value — they are
random by nature, so parity means a key the other service can read, a PEM a partner's tooling can
load, and a fingerprint computed the same way.

The private key is returned once and never stored. Only the public key, its fingerprint and the
encrypted salt go to the database.
"""

import base64
import hashlib
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SIGNATURE_ALGORITHM = "RSA-2048/SHA-256"
KEY_SIZE = 2048

SALT_PREFIX = "ipv_"
SALT_BYTES = 32

SHOWN_ONCE = (
    "The private key is shown once and is not stored. Hand it to the organization securely; "
    "if it is lost, recreate the pair."
)


class SignatureKeyMaterial:
    """An RSA-2048 pair, PEM-encoded the way the Java side encodes it.

    Private key as PKCS#8, public key as X.509 SubjectPublicKeyInfo, and the fingerprint as
    `SHA256:` plus the unpadded base64 of the SHA-256 digest of the DER public key — the same digest
    of the same bytes, so a key issued by either service fingerprints identically.
    """

    def __init__(self, algorithm: str, private_key_pem: str, public_key_pem: str, fingerprint: str):
        self.algorithm = algorithm
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem
        self.fingerprint = fingerprint

    @staticmethod
    def generate() -> "SignatureKeyMaterial":
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        public_der = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        digest = hashlib.sha256(public_der).digest()
        fingerprint = "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
        return SignatureKeyMaterial(SIGNATURE_ALGORITHM, private_pem, public_pem, fingerprint)

    def __repr__(self) -> str:  # never let a private key into a log line
        return f"SignatureKeyMaterial[{self.algorithm} {self.fingerprint}]"


class IpvSaltMaterial:
    def __init__(self, plaintext: str, masked: str):
        self.plaintext = plaintext
        self.masked = masked

    @staticmethod
    def generate() -> "IpvSaltMaterial":
        raw = secrets.token_bytes(SALT_BYTES)
        plaintext = SALT_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return IpvSaltMaterial(plaintext, mask_salt(plaintext))

    def __repr__(self) -> str:
        return f"IpvSaltMaterial[{self.masked}]"


def mask_salt(plaintext: str) -> str:
    """What the portals show: the prefix, eight bullets, and the last four characters."""
    return SALT_PREFIX + "•" * 8 + plaintext[-4:]
