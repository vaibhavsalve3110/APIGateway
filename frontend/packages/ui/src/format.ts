const dateTime = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTime.format(new Date(iso)) : "—";
}

export function formatNumber(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString("en-IN");
}

/** Seconds left in an overlap window as mm:ss (e.g. 19:59), or "expired". */
export function formatRemaining(seconds: number): string {
  if (seconds <= 0) {
    return "expired";
  }
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Seconds from now until an ISO instant, never negative. */
export function secondsUntil(iso: string | null | undefined, now: number = Date.now()): number {
  if (!iso) {
    return 0;
  }
  return Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000));
}

export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
