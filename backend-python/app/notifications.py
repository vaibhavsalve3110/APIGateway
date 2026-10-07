"""Who hears about a key rotation, and how notices are sent.

A key change is never silent (BRD CP-SEC-04/05, and the operator's rule):

* the organization's **Partner Admins** get the new key, since they are the ones who install it;
* **every** active user of that organization, admins included, is told the key changed and what to do
  if it was not them — without the key itself;
* the **APIM Admin team** is told which organization rotated, so an unexpected rotation is noticed by
  somebody other than the partner.

The same notices go out whether the partner rotated their own key or an APIM Admin did it for them;
only the wording says who. They are sent after the key exists and the gateway has accepted it, so
nobody is told about a rotation that failed.

With no SMTP host configured the notices are logged instead, which is how a developer machine — and
right now this network, where outbound SMTP is blocked — behaves.
"""

import asyncio
import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy import text

from .common import errors
from .common.time import java_instant
from .db import engine
from .settings import get_settings

log = logging.getLogger(__name__)


async def send(recipients: list[str], subject: str, body: str) -> None:
    """One message per distinct, non-blank recipient — as the Java Mailer does."""
    seen: list[str] = []
    for recipient in recipients:
        if recipient and recipient.strip() and recipient not in seen:
            seen.append(recipient)
    for recipient in seen:
        await _send_one(recipient, subject, body)


async def _send_one(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        log.info("NOTICE (no SMTP) to %s: %s\n%s", to, subject, body)
        return

    message = EmailMessage()
    message["To"] = to
    message["From"] = settings.mail_from
    message["Subject"] = subject
    message.set_content(body)

    def deliver() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_starttls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)

    try:
        # smtplib blocks; running it on the event loop would stall every other request.
        await asyncio.to_thread(deliver)
        log.info("Notification '%s' sent to %s", subject, to)
    except Exception as exc:  # noqa: BLE001 - a failed notice must not fail the rotation
        await errors.record(
            errors.SMTP,
            "NOTIFICATION_NOT_SENT",
            f"Could not send '{subject}' to {to}: {exc}",
            detail=repr(exc),
        )


def _instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    return java_instant(value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z")


def _overlap_sentence(previous_expires_at: datetime | None) -> str:
    """Spelled out, because "the old key still works for a while" is the part people get wrong."""
    if previous_expires_at is None:
        return "There was no previous key for this environment, so nothing stops working."
    minutes = get_settings().key_overlap_minutes
    return (
        f"The previous key keeps working for {minutes} more minutes, until "
        f"{_instant(previous_expires_at)}, and then stops."
    )


async def notify_key_generated(
    *,
    partner_id: str,
    partner_code: str,
    partner_name: str,
    environment: str,
    masked_key: str,
    plaintext: str,
    client_id: str,
    previous_expires_at: datetime | None,
    actor_username: str,
    by_partner: bool,
) -> None:
    settings = get_settings()
    who = (
        f"by {actor_username} in the Developer Portal"
        if by_partner
        else f"by the APIM Admin team ({actor_username})"
    )
    env = environment.lower()
    overlap = _overlap_sentence(previous_expires_at)

    async with engine().connect() as conn:
        users = list(
            await conn.execute(
                text(
                    "SELECT email, role FROM partner_user"
                    " WHERE partner_id = :id AND status = 'ACTIVE' ORDER BY full_name ASC"
                ),
                {"id": partner_id},
            )
        )
        platform_admins = [
            r.email
            for r in await conn.execute(
                text(
                    "SELECT email FROM platform_user"
                    " WHERE status = 'ACTIVE' AND role = 'ADMIN' ORDER BY full_name ASC"
                )
            )
        ]

    partner_admins = [u.email for u in users if u.role == "PARTNER_ADMIN"]
    everyone = [u.email for u in users]

    if partner_admins and settings.email_key_to_admin:
        await send(
            partner_admins,
            f"Your new {env} security key — {partner_name}",
            f"""A new {env} security key has been generated for {partner_name} ({partner_code}) {who}.

Client ID : {client_id}
New key   : {plaintext}

Install it now. {overlap}

This key is shown in this message and in the portal at the moment it was created, and nowhere
else — the platform keeps only a one-way hash of it and cannot tell you the value again.

If you did not expect this change, contact the APIM Admin team immediately.
""",
        )

    if everyone:
        await send(
            everyone,
            f"Security key changed for {partner_name}",
            f"""The {env} security key for {partner_name} ({partner_code}) was changed {who}.

{overlap}

You are receiving this because you have a Developer Portal account with {partner_name}. The key
itself is sent only to your Partner Admins; ask them for it if you need it.

If this change was not made by your organisation, contact the APIM Admin team immediately —
someone may have access to your portal account.
""",
        )

    if platform_admins:
        previous = (
            "none — this is their first key for this environment"
            if previous_expires_at is None
            else f"stops working at {_instant(previous_expires_at)}"
        )
        await send(
            platform_admins,
            f"Key rotation: {partner_name} ({partner_code}) — {env}",
            f"""{partner_name} ({partner_code}) now has a new {env} security key, generated {who}.

Client ID    : {client_id}
Key          : {masked_key}
Previous key : {previous}

Every active user of that organisation has been told. If this rotation was not expected,
check the audit log and contact the partner.
""",
        )
