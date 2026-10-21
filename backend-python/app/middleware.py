"""Payload encryption, as ASGI middleware.

Decrypts an encrypted request body before anything else sees it, and encrypts the response on the way
out, so every router, handler and exception handler goes on dealing in ordinary JSON. Nothing in this
service knows whether the client encrypted or not, which is the point: there is one code path to be
correct about, and it is this file.

Written against the raw ASGI interface rather than as a `BaseHTTPMiddleware`. That class cannot
replace the request body — it hands the handler the original `receive` — and this has to, because the
body the handler must parse is the *decrypted* one.

## What is and is not encrypted

Request bodies and **every** response, in both directions. Query strings are not: they name the route
and its filters, and encrypting them would mean turning every filtered GET into a POST, losing REST
semantics and caching along the way. The decision was taken deliberately — so nothing sensitive
belongs in a query string, and nothing currently does: the filters are dates, a status, a partner id
and a free-text search. Credentials, keys, salts and personal data all travel in bodies and
responses, which are covered.

## Exclusions

The public-key endpoint (the client cannot encrypt before it has the key), the health probe (a
plaintext probe is the point), gateway usage ingest (not portal traffic, and it authenticates with a
shared token), and the documentation and local-console routes, which are not API calls at all.
"""

from __future__ import annotations

import json
import logging

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .common import payload_crypto as pc
from .common.payload_crypto import PayloadCryptoError
from .settings import get_settings

log = logging.getLogger(__name__)

# Prefixes that never carry an encrypted payload. Matched against the path, longest-first semantics
# are not needed because none of these is a prefix of another.
EXEMPT_PREFIXES = (
    "/api/crypto/",  # chicken and egg: this is where the public key comes from
    "/actuator/",  # a probe that needs a key is not a probe
    "/internal/",  # gateway ingest, authenticated by its own shared token
    "/v3/api-docs",
    "/swagger-ui",
    "/docs/",
    "/redoc",
    "/ui",
)


def _exempt(path: str) -> bool:
    return path.startswith(EXEMPT_PREFIXES)


def _problem(status: int, code: str, detail: str, instance: str) -> bytes:
    """An RFC 9457 document built by hand.

    The app's own handlers are not reachable from here: a request rejected by this middleware never
    gets as far as a route, and a failure on the way out happens after they have run.
    """
    return json.dumps(
        {
            "type": "about:blank",
            "title": "Bad Request" if status == 400 else "Internal Server Error",
            "status": status,
            "detail": detail,
            "code": code,
            "instance": instance,
        }
    ).encode()


class PayloadEncryptionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        headers = Headers(scope=scope)
        settings = get_settings()

        # A CORS preflight carries no body and no key, by definition — the browser sends it before
        # the real request. Refusing it for being unencrypted would block the request it is asking
        # permission for, so it goes straight through to the CORS middleware beneath.
        if _exempt(path) or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        declared = headers.get(pc.HEADER_VERSION)
        wrapped_key = headers.get(pc.HEADER_KEY)

        if not declared and not wrapped_key:
            # Plaintext. Allowed on a developer machine, refused where it matters.
            if settings.payload_encryption_required and path.startswith("/api/"):
                await self._reject(
                    send,
                    400,
                    "ENCRYPTION_REQUIRED",
                    "This endpoint accepts encrypted payloads only. Wrap the request as described at "
                    "GET /api/crypto/public-key.",
                    path,
                )
                return
            await self.app(scope, receive, send)
            return

        if declared and declared != pc.VERSION:
            await self._reject(
                send,
                400,
                "ENCRYPTION_VERSION",
                f"Unsupported payload encryption version '{declared}'; this service speaks "
                f"'{pc.VERSION}'.",
                path,
            )
            return

        if not wrapped_key:
            await self._reject(
                send,
                400,
                "ENCRYPTION_KEY_MISSING",
                f"{pc.HEADER_VERSION} was sent without {pc.HEADER_KEY}, so there is no key to "
                "decrypt the payload with.",
                path,
            )
            return

        try:
            aes_key = pc.unwrap_key(wrapped_key)
        except PayloadCryptoError as exc:
            presented = headers.get(pc.HEADER_KID)
            hint = ""
            if presented and presented != pc.key_id():
                # By far the most common cause, and invisible otherwise: the page was loaded before
                # a key rotation and is still encrypting to the old public key.
                hint = (
                    f" The key you used ({presented}) is not the current one ({pc.key_id()});"
                    " reload the portal."
                )
            await self._reject(send, 400, "ENCRYPTION_KEY_INVALID", f"{exc}.{hint}", path)
            return

        body = await self._decrypt_body(scope, receive, aes_key, path, send)
        if body is None:
            return  # already rejected

        await self.app(scope, self._replay(body), self._encrypting_send(send, aes_key))

    # ---------------------------------------------------------------- request

    async def _decrypt_body(
        self,
        scope: Scope,
        receive: Receive,
        aes_key: bytes,
        path: str,
        send: Send,
    ) -> bytes | None:
        """Read the whole encrypted body and return its plaintext, or None having rejected it."""
        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        raw = b"".join(chunks)

        if not raw:
            return b""  # a GET or DELETE: nothing to decrypt, but the response still is

        try:
            envelope = json.loads(raw)
            iv, data = envelope["iv"], envelope["data"]
        except (json.JSONDecodeError, KeyError, TypeError):
            await self._reject(
                send,
                400,
                "ENCRYPTION_ENVELOPE_INVALID",
                'An encrypted request body must be {"iv": "...", "data": "..."} with both base64.',
                path,
            )
            return None

        try:
            return pc.decrypt(aes_key, iv, data)
        except PayloadCryptoError as exc:
            await self._reject(send, 400, "ENCRYPTION_PAYLOAD_INVALID", f"{exc}.", path)
            return None

    @staticmethod
    def _replay(body: bytes) -> Receive:
        """A receive channel that serves the decrypted body once, then reports disconnect.

        Content-Length in the scope headers is now wrong — it describes the ciphertext — but nothing
        downstream reads it: Starlette's `Request.body()` consumes this channel until `more_body` is
        false. Rewriting the header would mean editing the scope's raw header list for no gain.
        """
        served = False

        async def receive() -> Message:
            nonlocal served
            if served:
                return {"type": "http.disconnect"}
            served = True
            return {"type": "http.request", "body": body, "more_body": False}

        return receive

    # ---------------------------------------------------------------- response

    def _encrypting_send(self, send: Send, aes_key: bytes) -> Send:
        """Buffer the response, then send it as one encrypted envelope.

        Buffered rather than streamed because GCM authenticates the whole message: a per-chunk
        envelope would either need its own IV and tag per chunk, which the client would have to
        reassemble in order, or a tag that only arrives at the end, which defeats streaming anyway.
        Every response here is a small JSON document, so there is nothing to stream.
        """
        start: Message | None = None
        chunks: list[bytes] = []

        async def encrypting_send(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] != "http.response.body":
                await send(message)
                return

            chunks.append(message.get("body", b""))
            if message.get("more_body", False):
                return

            assert start is not None
            plaintext = b"".join(chunks)
            headers = MutableHeaders(scope=start)

            if not plaintext:
                # A 204, or a response that genuinely has no body: nothing to encrypt, and an
                # envelope around nothing would just be a lie with a tag on it.
                await send(start)
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return

            content_type = headers.get("content-type", "")
            if "json" not in content_type:
                # Static files and anything else non-JSON pass through. Nothing under /api/ answers
                # this way, and encrypting a stylesheet would only break it.
                await send(start)
                await send({"type": "http.response.body", "body": plaintext, "more_body": False})
                return

            try:
                envelope = json.dumps(pc.encrypt(aes_key, plaintext)).encode()
            except Exception:  # noqa: BLE001 - must not leak the plaintext it failed to encrypt
                log.exception("Could not encrypt a response body")
                failure = _problem(
                    500,
                    "ENCRYPTION_FAILED",
                    "The response could not be encrypted.",
                    "",
                )
                headers["content-type"] = "application/problem+json"
                headers["content-length"] = str(len(failure))
                start["status"] = 500
                await send(start)
                await send({"type": "http.response.body", "body": failure, "more_body": False})
                return

            # The envelope is JSON whatever the original was, so problem+json becomes json here.
            # The status is left alone: a 404 stays a 404, with its body encrypted.
            headers["content-type"] = "application/json"
            headers["content-length"] = str(len(envelope))
            headers[pc.HEADER_VERSION] = pc.VERSION
            headers[pc.HEADER_KID] = pc.key_id()
            # The body is ciphertext; nothing between here and the browser should hold on to it.
            headers["cache-control"] = "no-store"
            await send(start)
            await send({"type": "http.response.body", "body": envelope, "more_body": False})

        return encrypting_send

    # ---------------------------------------------------------------- rejection

    async def _reject(self, send: Send, status: int, code: str, detail: str, path: str) -> None:
        """Answer in plaintext.

        A client that got the envelope wrong cannot be assumed able to decrypt the explanation, and
        an unreadable error about encryption is how an afternoon disappears. These carry no data
        beyond the fact that encryption failed.
        """
        body = _problem(status, code, detail, path)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


