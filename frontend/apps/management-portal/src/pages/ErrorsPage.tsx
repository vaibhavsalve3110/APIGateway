import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  Chip, CodeBlock, ErrorBanner, formatDateTime, Modal, PageHeader, useAuth,
  type ErrorView, type PartnerView,
} from "@apigw/ui";

const SOURCES = ["ALL", "SMTP", "GATEWAY", "SCHEDULER", "API"] as const;

const WINDOWS = [
  { key: "1h", label: "Last hour", minutes: 60 },
  { key: "24h", label: "Last 24 hours", minutes: 60 * 24 },
  { key: "7d", label: "Last 7 days", minutes: 60 * 24 * 7 },
  { key: "30d", label: "Last 30 days", minutes: 60 * 24 * 30 },
  { key: "all", label: "All retained", minutes: 0 },
  { key: "custom", label: "Custom range…", minutes: 0 },
] as const;

type WindowKey = (typeof WINDOWS)[number]["key"];

/**
 * `<input type="datetime-local">` reads and writes local wall-clock time with no zone, so both
 * conversions go through the browser's offset. Treating the raw value as UTC would shift every
 * filter by that offset.
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

const SOURCE_TONE: Record<string, "bad" | "warn" | "info" | "neutral"> = {
  SMTP: "warn", GATEWAY: "bad", SCHEDULER: "info", API: "bad",
};

const SOURCE_HELP: Record<string, string> = {
  SMTP: "Sign-in codes that could not be e-mailed.",
  GATEWAY: "Calls to a gateway's admin API that were rejected or unanswered.",
  SCHEDULER: "Background jobs that threw — key expiry, retention purges.",
  API: "Requests that failed unexpectedly; each one is a defect worth reading.",
};

/** System errors (CP-LOG-05). Operational failures, as opposed to the audit log's record of what people did. */
export function ErrorsPage() {
  const { api } = useAuth();
  const [source, setSource] = useState<(typeof SOURCES)[number]>("ALL");
  const [detail, setDetail] = useState<ErrorView | null>(null);
  const [windowKey, setWindowKey] = useState<WindowKey>("7d");
  const [customFrom, setCustomFrom] = useState(() => toLocalInput(new Date(Date.now() - 86_400_000)));
  const [customTo, setCustomTo] = useState(() => toLocalInput(new Date()));
  const [partnerId, setPartnerId] = useState("");
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

  const partners = useQuery({
    queryKey: ["partners"],
    queryFn: () => api.get<PartnerView[]>("/api/admin/partners"),
  });

  const query = new URLSearchParams({ limit: "200" });
  if (source !== "ALL") query.set("source", source);
  if (range.from) query.set("from", range.from);
  if (range.to) query.set("to", range.to);
  if (partnerId) query.set("partnerId", partnerId);
  if (search.trim()) query.set("search", search.trim());

  const errors = useQuery({
    queryKey: ["errors", source, range.from, range.to, partnerId, search],
    queryFn: () => api.get<ErrorView[]>(`/api/admin/errors?${query.toString()}`),
    refetchInterval: 20_000,
    enabled: !invalidRange,
  });

  const rows = errors.data ?? [];

  return (
    <div className="page">
      <PageHeader
        title="System errors"
        subtitle="What failed, rather than who did what. Kept for 30 days, then purged; the audit log is never purged."
      />
      <ErrorBanner error={errors.error} />

      <div className="card">
        <div className="tabs">
          {SOURCES.map((s) => (
            <button key={s} className={`tab${source === s ? " tab-active" : ""}`} onClick={() => setSource(s)}>
              {s === "ALL" ? "All sources" : s}
            </button>
          ))}
        </div>

        {source !== "ALL" ? (
          <p className="muted" style={{ fontSize: 12, padding: "10px 16px 0" }}>{SOURCE_HELP[source]}</p>
        ) : null}

        <div className="tabs" style={{ gap: 10, flexWrap: "wrap", borderTop: "1px solid var(--line)" }}>
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

          <select className="select" style={{ width: 260, margin: "9px 0" }} value={partnerId}
            onChange={(e) => setPartnerId(e.target.value)}>
            <option value="">Any origin</option>
            <option value="none">Platform only (no partner)</option>
            {(partners.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>{p.name} · {p.code}</option>
            ))}
          </select>

          <div className="grow" />
          <input className="input" style={{ width: 240, margin: "9px 0" }}
            placeholder="Search message, code or reference"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>

        {partnerId && partnerId !== "none" ? (
          <p className="muted" style={{ fontSize: 12, padding: "10px 16px 0" }}>
            Failures where one of this organization’s portal users was signed in, or where the request
            names them. A failure with nobody signed in cannot be traced to anyone, so it appears under
            “Platform only” instead.
          </p>
        ) : partnerId === "none" ? (
          <p className="muted" style={{ fontSize: 12, padding: "10px 16px 0" }}>
            Failures that belong to no organization — the platform’s own: background jobs, mail, gateway
            admin calls, and anything that failed with nobody signed in.
          </p>
        ) : null}

        {invalidRange ? (
          <div className="empty">The “from” time has to be before the “to” time.</div>
        ) : errors.isLoading ? <div className="empty">Loading…</div> : rows.length === 0 ? (
          <div className="empty">Nothing has failed{source === "ALL" ? "" : ` in ${source}`} that matches these filters.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 150 }}>When</th><th style={{ width: 110 }}>Source</th>
                <th style={{ width: 170 }}>Partner</th><th style={{ width: 170 }}>Code</th>
                <th>Message</th><th style={{ width: 130 }}>Reference</th><th style={{ width: 70 }} />
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td className="mono muted nowrap" style={{ fontSize: 11.5 }}>{formatDateTime(e.occurredAt)}</td>
                  <td><Chip tone={SOURCE_TONE[e.source] ?? "neutral"}>{e.source}</Chip></td>
                  <td style={{ fontSize: 12 }}>
                    {e.partnerName ? (
                      <>
                        {e.partnerName}
                        <div className="cell-sub mono">{e.partnerCode}</div>
                      </>
                    ) : (
                      <span className="muted">Platform</span>
                    )}
                  </td>
                  <td className="mono" style={{ fontSize: 11.5 }}>{e.code}</td>
                  <td style={{ fontSize: 12.5 }}>
                    {e.message}
                    {e.actor || e.request ? (
                      <div className="cell-sub">{[e.request, e.actor, e.clientIp].filter(Boolean).join(" · ")}</div>
                    ) : null}
                  </td>
                  <td className="mono muted" style={{ fontSize: 11 }}>{e.reference}</td>
                  <td>
                    <button className="btn btn-sm" disabled={!e.detail} onClick={() => setDetail(e)}>Trace</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {detail ? (
        <Modal
          title={`${detail.code} · ${detail.reference}`}
          width={860}
          onClose={() => setDetail(null)}
          footer={<button className="btn btn-primary" onClick={() => setDetail(null)}>Close</button>}
        >
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <Chip tone={SOURCE_TONE[detail.source] ?? "neutral"}>{detail.source}</Chip>
            <span className="muted" style={{ fontSize: 12 }}>{formatDateTime(detail.occurredAt)}</span>
            {detail.request ? <span className="mono muted" style={{ fontSize: 11.5 }}>{detail.request}</span> : null}
            {detail.actor ? <span className="muted" style={{ fontSize: 12 }}>{detail.actor}</span> : null}
          </div>
          <p style={{ fontSize: 13, lineHeight: 1.6 }}>{detail.message}</p>
          {detail.detail ? <CodeBlock code={detail.detail} maxHeight={420} /> : null}
        </Modal>
      ) : null}
    </div>
  );
}
