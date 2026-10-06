"""Session tokens.

Accepts exactly what backend-java's ``TokenService`` mints: HS256, issuer ``apigw-platform``, the
e-mail address as both ``sub`` and ``preferred_username``, roles under ``realm_access.roles``, and a
partner's organization as ``groups: ["/partners/<CODE>"]``.

Both services must share ``AUTH_JWT_SECRET``. That is what lets one portal session work against
either backend while the migration is in progress.
"""

from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Request

from .common.problem import ApiException
from .settings import get_settings

ISSUER = "apigw-platform"
PARTNER_GROUP_PREFIX = "/partners/"


@dataclass(frozen=True)
class Principal:
    """Who is calling, in the shape the rest of the service wants it."""

    username: str
    display_name: str
    roles: list[str] = field(default_factory=list)
    #: The organization code for a partner user, or None for a platform user.
    partner_code: str | None = None

    def has_role(self, *roles: str) -> bool:
        return any(role in self.roles for role in roles)


def _decode(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            issuer=ISSUER,
            options={"require": ["exp", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ApiException(401, "TOKEN_EXPIRED", "Your session has expired — sign in again") from exc
    except jwt.InvalidTokenError as exc:
        raise ApiException(401, "UNAUTHENTICATED", "A valid session token is required") from exc


async def current_principal(request: Request) -> Principal:
    """FastAPI dependency: the signed-in caller, or 401."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiException(401, "UNAUTHENTICATED", "A valid session token is required")

    claims = _decode(token)
    groups = claims.get("groups") or []
    group = next((g for g in groups if isinstance(g, str) and g.startswith(PARTNER_GROUP_PREFIX)), None)
    subject = str(claims.get("sub", ""))
    realm = claims.get("realm_access") or {}

    principal = Principal(
        username=str(claims.get("preferred_username") or subject),
        display_name=str(claims.get("name") or subject),
        roles=[str(r) for r in (realm.get("roles") or [])],
        partner_code=group[len(PARTNER_GROUP_PREFIX) :] if group else None,
    )
    # Stashed so the exception handler can name the actor when it records a 5xx.
    request.state.principal = principal
    return principal


def requires(*roles: str):  # type: ignore[no-untyped-def]
    """Dependency factory mirroring the Java side's role checks.

    Roles are the plain names from ``realm_access.roles``: ADMIN, EDITOR, VIEWER, PARTNER.
    """

    async def guard(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has_role(*roles):
            raise ApiException(403, "FORBIDDEN", f"Requires one of: {', '.join(roles)}")
        return principal

    return guard
