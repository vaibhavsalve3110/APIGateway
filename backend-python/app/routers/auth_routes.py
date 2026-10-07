"""Sign-in: a CAPTCHA, a one-time code by e-mail, and the session token both portals carry.

Three things here are easy to get subtly wrong, and each is commented where it lives:

* a failed verification must still **count** against the attempt limit. Java does that with Spring's
  `noRollbackFor`, which commits the counter even though the request ends in an exception. There is
  no equivalent in SQLAlchemy, so the attempt is committed in its own transaction before the code is
  compared.
* the token must be the one `TokenService` mints, claim for claim, or a session issued by one service
  is refused by the other.
* the CAPTCHA lives in memory. A challenge issued by one service cannot be solved by the other, so
  both sign-in routes must be served by the same one.
"""

import hashlib
import hmac
import io
import logging
import random
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Request
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..auth import ISSUER, Principal, current_principal
from ..common import audit
from ..common.problem import ApiException
from ..common.time import java_instant
from ..db import engine
from ..notifications import send
from ..routers.partner_users import EMAIL_PATTERN
from ..settings import get_settings

router = APIRouter(prefix="/api/auth")
log = logging.getLogger(__name__)

AUDIT_TYPE = "SIGN_IN"

CAPTCHA_TTL = timedelta(minutes=5)
CAPTCHA_WIDTH, CAPTCHA_HEIGHT, CAPTCHA_LENGTH = 190, 60, 5
# No I, O, S or 0/1/5/8: characters that are read wrong more often than they are typed wrong.
CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXYZ234679"

#: challengeId -> (answer, expires_at). In memory on purpose: a CAPTCHA is worthless after one use
#: and worth nothing to persist, but it does mean one process must serve both sign-in routes.
_captchas: dict[str, tuple[str, datetime]] = {}


class CodeRequest(BaseModel):
    email: str = Field(min_length=1, pattern=EMAIL_PATTERN)
    captchaId: str = Field(min_length=1)  # noqa: N815
    captchaAnswer: str = Field(min_length=1)  # noqa: N815


class VerifyRequest(BaseModel):
    email: str = Field(min_length=1, pattern=EMAIL_PATTERN)
    code: str = Field(min_length=1)


def _normalise(email: str | None) -> str:
    return (email or "").strip().lower()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


async def _audit(actor: str, roles: list[str], partner_code: str | None, action: str, detail: str) -> None:
    async with engine().begin() as conn:
        await audit.record(
            conn,
            actor=actor,
            actor_role=sorted(roles)[0] if roles else None,
            action=action,
            object_type=AUDIT_TYPE,
            object_id=None,
            detail=detail,
        )


# --------------------------------------------------------------------------- captcha


def _draw_captcha(answer: str) -> bytes:
    image = Image.new("RGB", (CAPTCHA_WIDTH, CAPTCHA_HEIGHT), (0xF4, 0xF6, 0xF9))
    draw = ImageDraw.Draw(image)
    rng = random.SystemRandom()

    # Speckles and lines, so the glyphs do not sit on a clean background.
    for _ in range(380):
        x, y = rng.randrange(CAPTCHA_WIDTH), rng.randrange(CAPTCHA_HEIGHT)
        shade = (rng.randrange(80, 240), rng.randrange(80, 240), rng.randrange(80, 240))
        draw.rectangle([x, y, x + 1, y + 1], fill=shade)
    for _ in range(4):
        shade = (rng.randrange(60, 180), rng.randrange(60, 180), rng.randrange(60, 180))
        draw.line(
            [
                rng.randrange(CAPTCHA_WIDTH), rng.randrange(CAPTCHA_HEIGHT),
                rng.randrange(CAPTCHA_WIDTH), rng.randrange(CAPTCHA_HEIGHT),
            ],
            fill=shade, width=2,
        )

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
    except OSError:
        # The slim image carries no fonts; the default bitmap font is legible enough for five glyphs.
        font = ImageFont.load_default(size=34)

    x = 18
    for character in answer:
        glyph = Image.new("RGBA", (40, 50), (0, 0, 0, 0))
        ImageDraw.Draw(glyph).text(
            (4, 2), character, font=font,
            fill=(rng.randrange(0, 90), rng.randrange(0, 90), rng.randrange(60, 140)),
        )
        # One rotation, used as both the image and its own mask, so the glyph keeps its transparency.
        rotated = glyph.rotate(rng.uniform(-22, 22), expand=False)
        image.paste(rotated, (x, 4), rotated)
        x += 33

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _purge_captchas(now: datetime) -> None:
    for key in [k for k, (_, expires) in _captchas.items() if expires <= now]:
        _captchas.pop(key, None)


@router.post("/captcha")
async def issue_captcha() -> dict[str, Any]:
    now = datetime.now(UTC)
    _purge_captchas(now)
    answer = "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(CAPTCHA_LENGTH))
    challenge_id = str(uuid.uuid4())
    _captchas[challenge_id] = (answer, now + CAPTCHA_TTL)
    import base64

    return {
        "challengeId": challenge_id,
        "image": "data:image/png;base64," + base64.b64encode(_draw_captcha(answer)).decode(),
        "expiresInSeconds": int(CAPTCHA_TTL.total_seconds()),
    }


def _solve_captcha(challenge_id: str | None, answer: str | None) -> bool:
    if not challenge_id or not answer:
        return False
    entry = _captchas.pop(challenge_id, None)  # single use, solved or not
    if entry is None:
        return False
    expected, expires_at = entry
    return datetime.now(UTC) < expires_at and expected.casefold() == answer.strip().casefold()


# --------------------------------------------------------------------------- identity


async def _find_identity(email: str) -> dict[str, Any] | None:
    """A platform user first, then a partner user whose organization is also active."""
    if not email:
        return None
    async with engine().connect() as conn:
        internal = (
            await conn.execute(
                text(
                    "SELECT email, full_name, role FROM platform_user"
                    " WHERE email = :email AND status = 'ACTIVE'"
                ),
                {"email": email},
            )
        ).first()
        if internal is not None:
            return {
                "email": internal.email,
                "displayName": internal.full_name,
                "roles": [internal.role],
                "partnerCode": None,
            }
        partner_user = (
            await conn.execute(
                text(
                    "SELECT u.email, u.full_name, p.code, p.status AS partner_status"
                    "  FROM partner_user u JOIN partner p ON p.id = u.partner_id"
                    " WHERE u.email = :email AND u.status = 'ACTIVE'"
                ),
                {"email": email},
            )
        ).first()
        if partner_user is not None and partner_user.partner_status == "ACTIVE":
            return {
                "email": partner_user.email,
                "displayName": partner_user.full_name,
                "roles": ["PARTNER"],
                "partnerCode": partner_user.code,
            }
    return None


def _issue_token(identity: dict[str, Any]) -> tuple[str, datetime]:
    """Exactly what TokenService mints, so a session works against either control plane."""
    settings = get_settings()
    now = int(time.time())
    expires_at = now + int(timedelta(hours=settings.token_ttl_hours).total_seconds())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "iat": now,
        "exp": expires_at,
        "sub": identity["email"],
        "preferred_username": identity["email"],
        "name": identity["displayName"],
        "realm_access": {"roles": list(identity["roles"])},
    }
    if identity["partnerCode"]:
        claims["groups"] = [f"/partners/{identity['partnerCode']}"]
    token = jwt.encode(claims, settings.auth_jwt_secret, algorithm="HS256")
    return token, datetime.fromtimestamp(expires_at, tz=UTC)


# --------------------------------------------------------------------------- one-time codes


@router.post("/otp/request")
async def request_code(request: CodeRequest, http: Request) -> dict[str, Any]:
    settings = get_settings()
    client_ip = _client_ip(http)

    if not _solve_captcha(request.captchaId, request.captchaAnswer):
        raise ApiException.bad_request(
            "CAPTCHA_FAILED", "That does not match the image. Try the new one."
        )

    email = _normalise(request.email)
    now = datetime.now(UTC)
    window_start = now - timedelta(minutes=settings.otp_request_window_minutes)

    async with engine().connect() as conn:
        recent = list(
            await conn.execute(
                text(
                    "SELECT created_at FROM otp_challenge"
                    " WHERE email = :email AND created_at > :since ORDER BY created_at DESC"
                ),
                {"email": email, "since": window_start},
            )
        )

    if len(recent) >= settings.otp_max_requests_per_window:
        await _audit(email, ["SYSTEM"], None, "SIGN_IN_THROTTLED",
                     f"Too many sign-in codes requested for {email} from {client_ip}")
        raise ApiException(
            429, "TOO_MANY_REQUESTS",
            f"Too many codes requested. Wait {settings.otp_request_window_minutes} minutes and try again.",
        )
    if recent:
        waited = int((now - recent[0].created_at).total_seconds())
        if waited < settings.otp_resend_cooldown_seconds:
            raise ApiException(
                429, "RESEND_TOO_SOON",
                "A code was just sent. You can ask for another in "
                f"{settings.otp_resend_cooldown_seconds - waited} seconds.",
            )

    identity = await _find_identity(email)
    if identity is None:
        log.info("Sign-in code requested for unknown address %s from %s", email, client_ip)
        await _audit(email, ["SYSTEM"], None, "SIGN_IN_UNKNOWN_EMAIL",
                     f"Sign-in attempted with an address that is not registered: {email} from {client_ip}")
        if settings.reveal_unknown_email:
            raise ApiException(
                404, "USER_NOT_REGISTERED",
                "This e-mail address is not registered. Ask your administrator to create an account for you.",
            )
        # Otherwise the same answer as for a known address, so nobody can discover who holds an account.
        return {
            "expiresInSeconds": settings.otp_ttl_minutes * 60,
            "resendInSeconds": settings.otp_resend_cooldown_seconds,
            "devCode": None,
        }

    code = "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))
    async with engine().begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO otp_challenge (id, email, code_hash, created_at, expires_at, attempts, client_ip)
                VALUES (:id, :email, :code_hash, :now, :expires, 0, :client_ip)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "email": email,
                "code_hash": hashlib.sha256(code.encode()).hexdigest(),
                "now": now,
                "expires": now + timedelta(minutes=settings.otp_ttl_minutes),
                "client_ip": client_ip,
            },
        )

    delivered = bool(settings.smtp_host)
    await send(
        [email],
        "Your sign-in code",
        f"""Your one-time code is {code}.

It is valid for {settings.otp_ttl_minutes} minutes and can be used once.

If you did not ask to sign in, ignore this message and tell your administrator.
""",
    )
    await _audit(email, ["SYSTEM"], None, "SIGN_IN_CODE_SENT",
                 f"One-time code {'e-mailed to ' if delivered else 'issued for (not e-mailed) '}{email}"
                 f" from {client_ip}")

    # Shown in the portal only when it could not be e-mailed, and never in production.
    return {
        "expiresInSeconds": settings.otp_ttl_minutes * 60,
        "resendInSeconds": settings.otp_resend_cooldown_seconds,
        "devCode": None if delivered else code,
    }


@router.post("/otp/verify")
async def verify_code(request: VerifyRequest, http: Request) -> dict[str, Any]:
    settings = get_settings()
    client_ip = _client_ip(http)
    email = _normalise(request.email)
    now = datetime.now(UTC)

    async def reject(reason: str) -> ApiException:
        await _audit(email, ["SYSTEM"], None, "SIGN_IN_FAILED",
                     f"Failed sign-in for {email} from {client_ip} ({reason})")
        return ApiException(
            401, "INVALID_CODE", "That code is not valid or has expired. Ask for a new one."
        )

    async with engine().connect() as conn:
        challenge = (
            await conn.execute(
                text(
                    "SELECT id, code_hash, attempts, expires_at, consumed_at FROM otp_challenge"
                    " WHERE email = :email ORDER BY created_at DESC LIMIT 1"
                ),
                {"email": email},
            )
        ).first()

    usable = (
        challenge is not None
        and challenge.consumed_at is None
        and challenge.attempts < settings.otp_max_attempts
        and now < challenge.expires_at
    )
    if not usable:
        raise await reject("no usable code")

    # Committed on its own, before the code is compared. Spring does this with noRollbackFor: without
    # it a wrong guess rolls back with the rejection and costs the attacker nothing.
    async with engine().begin() as conn:
        await conn.execute(
            text("UPDATE otp_challenge SET attempts = attempts + 1 WHERE id = :id"),
            {"id": str(challenge.id)},
        )

    presented = hashlib.sha256((request.code or "").strip().encode()).hexdigest()
    if not hmac.compare_digest(challenge.code_hash, presented):
        raise await reject(f"wrong code, attempt {challenge.attempts + 1}")

    identity = await _find_identity(email)
    if identity is None:
        raise await reject("account no longer active")

    async with engine().begin() as conn:
        await conn.execute(
            text("UPDATE otp_challenge SET consumed_at = :now WHERE id = :id"),
            {"id": str(challenge.id), "now": now},
        )
        if not identity["partnerCode"]:
            await conn.execute(
                text("UPDATE platform_user SET last_login_at = :now WHERE email = :email"),
                {"email": email, "now": now},
            )

    token, expires_at = _issue_token(identity)
    await _audit(identity["email"], identity["roles"], identity["partnerCode"], "SIGN_IN",
                 f"Signed in from {client_ip}")
    return {
        "token": token,
        "expiresAt": java_instant(expires_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"),
        "email": identity["email"],
        "displayName": identity["displayName"],
        "roles": list(identity["roles"]),
        "partnerCode": identity["partnerCode"],
    }


@router.get("/me")
async def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {
        "username": principal.username,
        "roles": sorted(principal.roles),
        "partnerCode": principal.partner_code,
    }
