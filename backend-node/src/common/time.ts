/**
 * Timestamp formatting that matches Java's `Instant.toString()`, which is what backend-java puts on
 * the wire.
 *
 * Two things make this necessary:
 *
 *  - PostgreSQL stores `timestamptz` to microsecond precision, but a JavaScript `Date` only holds
 *    milliseconds, so reading a timestamp as a Date silently drops the last three digits. The fix is
 *    to have PostgreSQL render it as text (see {@link instantColumn}) and never build a Date at all.
 *  - `Instant.toString()` prints the *fewest* fractional digits that keep the value exact: none, 3,
 *    6 or 9. So `.353514` stays six digits, `.350000` becomes `.35`… no — becomes `.350`, and an
 *    exact second prints no fraction. Emitting a fixed six digits would differ from Java on round
 *    values.
 */

/** SQL that renders a timestamptz the way {@link javaInstant} expects. */
export function instantColumn(expression: string, alias: string): string {
  return `to_char(${expression} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS ${alias}`;
}

/**
 * Normalises `2026-09-19T22:01:28.467634Z` into exactly what Java would print for that instant:
 * trailing zero groups are dropped, in groups of three, down to no fraction at all.
 */
export function javaInstant(value: string | null | undefined): string | null {
  if (!value) return null;
  const m = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d{6})Z$/.exec(value);
  if (!m) return value; // already formatted, or an unexpected shape — pass it through untouched
  const [, seconds, micros] = m;
  if (micros === '000000') return `${seconds}Z`;
  if (micros.endsWith('000')) return `${seconds}.${micros.slice(0, 3)}Z`;
  return `${seconds}.${micros}Z`;
}

/** The same formatting for a value that is already a Date (millisecond precision by definition). */
export function javaInstantFromDate(value: Date | null | undefined): string | null {
  if (!value) return null;
  // Date#toISOString always prints exactly three fractional digits; Java omits them when zero.
  return value.toISOString().replace(/\.000Z$/, 'Z');
}
