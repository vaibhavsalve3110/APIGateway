"""Timestamp formatting that matches Java's ``Instant.toString()``.

Two things make this necessary, and the Node port found both the hard way:

* PostgreSQL stores ``timestamptz`` to microsecond precision. Reading one into a Python ``datetime``
  keeps the microseconds, but formatting it with ``isoformat()`` produces ``+00:00`` and a fixed six
  digits, neither of which matches. The timestamp is rendered as text in SQL instead.
* ``Instant.toString()`` prints the *fewest* fractional digits that keep the value exact: none, three
  or six. A fixed width would differ from backend-java on round values.
"""

import re

_MICROS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d{6})Z$")


def instant_column(expression: str, alias: str) -> str:
    """SQL rendering a timestamptz in the shape :func:`java_instant` expects."""
    return f"to_char({expression} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') AS {alias}"


def java_instant(value: str | None) -> str | None:
    """Normalise ``2026-09-19T22:01:28.467634Z`` into exactly what Java would print.

    Trailing zero groups are dropped in threes, down to no fraction at all.
    """
    if not value:
        return None
    match = _MICROS.match(value)
    if not match:
        return value  # already formatted, or an unexpected shape — pass through untouched
    seconds, micros = match.groups()
    if micros == "000000":
        return f"{seconds}Z"
    if micros.endswith("000"):
        return f"{seconds}.{micros[:3]}Z"
    return f"{seconds}.{micros}Z"
