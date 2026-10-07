import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Chip, ErrorBanner, formatDateTime, PageHeader, useAuth, type AuditView } from "@apigw/ui";

const ACTION_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  CREATE: "ok", GENERATE: "info", UPDATE: "info", ACCESS_TIER: "warn", DISABLE: "warn", ENABLE: "ok",
  REVOKE: "bad", DELETE: "bad", EXPIRE: "neutral",
};

const WINDOWS = [
  { key: "1h", label: "Last hour", minutes: 60 },
  { key: "24h", label: "Last 24 hours", minutes: 60 * 24 },
  { key: "7d", label: "Last 7 days", minutes: 60 * 24 * 7 },
  { key: "30d", label: "Last 30 days", minutes: 60 * 24 * 30 },
  { key: "90d", label: "Last 90 days", minutes: 60 * 24 * 90 },
  { key: "all", label: "All time", minutes: 0 },
  { key: "custom", label: "Custom range…", minutes: 0 },
] as const;

type WindowKey = (typeof WINDOWS)[number]["key"];

/** Who appears in the trail, for the user filter. */
interface AuditActor {
  actor: string;
  actorRole: string | null;
  entries: number;
  lastSeen: string;
}

/**
 * `<input type="datetime-local">` reads and writes local wall-clock time with no zone, so both
 * conversions have to go through the browser's offset. Sending the raw value as if it were UTC
 * would shift every filter by the offset — five and a half hours here.
 */
function toLocalInput(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

/** Audit trail (BRD CP-LOG-05, CP-SEC-07). */
export function AuditPage() {
  const { api, user } = useAuth();
  const [windowKey, setWindowKey] = useState<WindowKey>("7d");
  const [customFrom, setCustomFrom] = useState(() => toLocalInput(new Date(Date.now() - 86_400_000)));
  const [customTo, setCustomTo] = useState(() => toLocalInput(new Date()));
  const [actor, setActor] = useState("");
  const [search, setSearch] = useState("");

  const range = useMemo(() => {
    if (windowKey === "custom") {
      return { from: fromLocalInput(customFrom), to: fromLocalInput(customTo) };
    }
    const minutes = WINDOWS.find((w) => w.key === windowKey)?.minutes ?? 0;
    if (!minutes) return { from: null, to: null };
    // Rounded to the minute so the query key is stable and the list does not refetch every render.
    const now = Math.floor(Date.now() / 60_000) * 60_000;
    return { from: new Date(now - minutes * 60_000).toISOString(), to: null };
  }, [windowKey, customFrom, customTo]);

  const invalidRange =
    windowKey === "custom" && range.from !== null && range.to !== null && range.from >= range.to;

  const actors = useQuery({
    queryKey: ["audit-actors"],
    queryFn: () => api.get<AuditActor[]>("/api/admin/audit/actors"),
  });

  const query = new URLSearchParams({ limit: "500" });
  if (range.from) query.set("from", range.from);
  if (range.to) query.set("to", range.to);
  if (actor) query.set("actor", actor);
  if (search.trim()) query.set("search", search.trim());

  const audit = useQuery({
    queryKey: ["audit", range.from, range.to, actor, search],
    queryFn: () => api.get<AuditView[]>(`/api/admin/audit?${query.toString()}`),
    refetchInterval: 20_000,
    enabled: !invalidRange,
  });

  const rows = audit.data ?? [];
  // The token's preferred_username is the e-mail address, which is what the trail records as actor.
  const signedInAs = user.username;
  const meInTrail = (actors.data ?? []).some((a) => a.actor.toLowerCase() === signedInAs.toLowerCase());

  return (
    <div className="page">
      <PageHeader
        title="Audit log"
        subtitle={
          `${rows.length} entr${rows.length === 1 ? "y" : "ies"} · every configuration and key action, `
          + "with who did it and when. Automatic key expiry is recorded as “System”."
        }
      />
      <ErrorBanner error={audit.error ?? actors.error} />

      <div className="card">
        <div className="tabs" style={{ gap: 10, flexWrap: "wrap" }}>
          <select className="select" style={{ width: 160, margin: "9px 0" }} value={windowKey}
            onChange={(e) => setWindowKey(e.target.value as WindowKey)}>
            {WINDOWS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
          </select>

          {windowKey === "custom" ? (
            <>
              <input className="input" type="datetime-local" style={{ width: 210, margin: "9px 0" }}
                value={customFrom} max={customTo} aria-label="From"
                onChange={(e) => setCustomFrom(e.target.value)} />
              <span className="muted" style={{ alignSelf: "center", fontSize: 12 }}>to</span>
              <input className="input" type="datetime-local" style={{ width: 210, margin: "9px 0" }}
                value={customTo} min={customFrom} aria-label="To"
                onChange={(e) => setCustomTo(e.target.value)} />
            </>
          ) : null}

          <select className="select" style={{ width: 260, margin: "9px 0" }} value={actor}
            onChange={(e) => setActor(e.target.value)}>
            <option value="">All users</option>
            {signedInAs && meInTrail ? <option value={signedInAs}>Me ({signedInAs})</option> : null}
            {(actors.data ?? [])
              .filter((a) => a.actor.toLowerCase() !== signedInAs.toLowerCase())
              .map((a) => (
                <option key={a.actor} value={a.actor}>
                  {a.actor}{a.actorRole ? ` · ${a.actorRole.toLowerCase()}` : ""} ({a.entries})
                </option>
              ))}
          </select>

          <div className="grow" />
          <input className="input" style={{ width: 240, margin: "9px 0" }}
            placeholder="Search detail or object"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>

        {invalidRange ? (
          <div className="empty">The “from” time has to be before the “to” time.</div>
        ) : audit.isLoading ? (
          <div className="empty">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="empty">
            Nothing matches these filters. Widen the time range, or choose “All users”.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 160 }}>Timestamp</th><th>User</th><th>Action</th>
                <th>Object</th><th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="mono muted" style={{ fontSize: 11.5 }}>{formatDateTime(a.occurredAt)}</td>
                  <td style={{ fontSize: 12 }}>
                    {a.actor}
                    {a.actorRole ? <span className="muted"> · {a.actorRole.toLowerCase()}</span> : null}
                  </td>
                  <td><Chip tone={ACTION_TONE[a.action] ?? "neutral"}>{a.action.replace("_", " ")}</Chip></td>
                  <td style={{ fontSize: 12 }}>{a.objectType.replace("_", " ").toLowerCase()}</td>
                  <td className="muted" style={{ fontSize: 12 }}>{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="muted" style={{ fontSize: 12 }}>
        This is the portal trail: who changed configuration, issued or revoked a key, or signed in.
        Gateway traffic is not here — a security key belongs to an organization rather than to a
        person, so a partner’s API calls can be attributed to their Client ID but not to one of their
        users. Those are on <strong>API logs</strong>.
      </p>
    </div>
  );
}
