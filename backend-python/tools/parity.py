"""Compares a ported endpoint between backend-java and backend-python on the same database.

    python tools/parity.py /api/admin/apis /api/admin/partners ...

Prints every differing JSON path and exits non-zero if any endpoint differs. A route is only moved
across in nginx once it matches here.

Base URLs default to the services running on localhost; override with JAVA_URL / PYTHON_URL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
JAVA_URL = os.environ.get("JAVA_URL", "http://127.0.0.1:8088")
PYTHON_URL = os.environ.get("PYTHON_URL", "http://127.0.0.1:8090")


def _secret() -> str:
    """The shared signing secret, from whichever env file this machine has."""
    for candidate in (ROOT / "backend-python" / ".env", ROOT / "infra" / ".env"):
        if candidate.exists():
            m = re.search(r"^AUTH_JWT_SECRET=(.*)$", candidate.read_text(encoding="utf-8"), re.M)
            if m and m.group(1).strip():
                return m.group(1).strip()
    # Matches TokenService.signingKey's development fallback.
    return "apigw-local-development-jwt-signing-secret-32b"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _token(roles: list[str]) -> str:
    """A token in backend-java's TokenService shape, so both services accept it."""
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(
        json.dumps(
            {
                "iss": "apigw-platform",
                "iat": now,
                "exp": now + 3600,
                "sub": "admin@apigw.local",
                "preferred_username": "admin@apigw.local",
                "name": "Parity Check",
                "realm_access": {"roles": roles},
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(_secret().encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def fetch(base: str, path: str, token: str) -> Any:
    request = urllib.request.Request(f"{base}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed localhost URLs
        return json.loads(response.read().decode())


def diff(a: Any, b: Any, path: str = "", out: list[str] | None = None) -> list[str]:
    """Walk both trees and report every path whose value differs."""
    out = [] if out is None else out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} vs {len(b)}")
        for i in range(min(len(a), len(b))):
            diff(a[i], b[i], f"{path}[{i}]", out)
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for key in dict.fromkeys([*a, *b]):
            if key not in a:
                out.append(f"{path}.{key}: missing in JAVA")
            elif key not in b:
                out.append(f"{path}.{key}: missing in PYTHON")
            else:
                diff(a[key], b[key], f"{path}.{key}", out)
        return out
    if a != b:
        out.append(f"{path}: java={json.dumps(a)} python={json.dumps(b)}")
    return out


def main(paths: list[str]) -> int:
    token = _token(["ADMIN"])
    failed = 0
    for path in paths:
        try:
            java = fetch(JAVA_URL, path, token)
        except (urllib.error.URLError, OSError) as exc:
            print(f"  FAIL  {path} — java: {exc}")
            failed += 1
            continue
        try:
            python = fetch(PYTHON_URL, path, token)
        except (urllib.error.URLError, OSError) as exc:
            print(f"  FAIL  {path} — python: {exc}")
            failed += 1
            continue

        differences = diff(java, python)
        if not differences:
            size = f"{len(java)} items" if isinstance(java, list) else "object"
            print(f"  MATCH {path}  ({size})")
        else:
            failed += 1
            print(f"  DIFF  {path}")
            for line in differences[:12]:
                print(f"          {line}")
            if len(differences) > 12:
                print(f"          ...and {len(differences) - 12} more")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
