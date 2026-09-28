import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import {
  Chip, ErrorBanner, formatDateTime, PageHeader, statusTone, useAuth,
  type PartnerView, type UsageLogEntry,
} from "@apigw/ui";

const WINDOWS = [
  { key: "15m", label: "Last 15 min", minutes: 15 },
  { key: "1h", label: "Last hour", minutes: 60 },
  { key: "24h", label: "Last 24 hours", minutes: 60 * 24 },
  { key: "7d", label: "Last 7 days", minutes: 60 * 24 * 7 },
  { key: "30d", label: "Last 30 days", minutes: 60 * 24 * 30 },
] as const;

const STATUSES = [
  { key: "ALL", label: "All statuses" },
  { key: "SUCCESS", label: "Success (2xx, 3xx)" },
  { key: "ERROR", label: "All errors (4xx, 5xx)" },
  { key: "CLIENT_ERROR", label: "Client errors (4xx)" },
  { key: "SERVER_ERROR", label: "Server errors (5xx)" },
] as const;

/**
 * Every call the gateways reported, newest first (BRD CP-RPT-02). Filter by time, status, API name or the
 * partner that called — the last of these is the per-partner access trail.
 */
export function ApiLogsPage() {
  const { api } = useAuth();
  const [params, setParams] = useSearchParams();
  const [windowKey, setWindowKey] = useState<(typeof WINDOWS)[number]["key"]>("1h");
  const [status, setStatus] = useState<string>(params.get("status") ?? "ALL");
  const [search, setSearch] = useState("");
  const clientId = params.get("clientId") ?? "";

  const minutes = WINDOWS.find((w) => w.key === windowKey)?.minutes ?? 60;
  // Rounded to the minute so the query key is stable and the list does not re-fetch on every render.
  const from = useMemo(() => {
    const now = Date.now();
    return new Date(Math.floor(now / 60_000) * 60_000 - minutes * 60_000).toISOString();
  }, [minutes]);

  const partners = useQuery({ queryKey: ["partners"], queryFn: () => api.get<PartnerView[]>("/api/admin/partners") });
  const logs = useQuery({
    queryKey: ["logs", from, status, search, clientId],
    queryFn: () => api.get<UsageLogEntry[]>(
      `/api/admin/usage/logs?from=${encodeURIComponent(from)}&limit=500`
      + (status === "ALL" ? "" : `&status=${status}`)
      + (search.trim() ? `&search=${encodeURIComponent(search.trim())}` : "")
      + (clientId ? `&clientId=${encodeURIComponent(clientId)}` : "")),
    refetchInterval: 20_000,
  });

  const rows = logs.data ?? [];
  const failed = rows.filter((r) => r.statusCode >= 400).length;

  const clientOptions = (partners.data ?? []).flatMap((p) => [
    { clientId: p.clientIdSandbox, label: `${p.name} · sandbox` },
    ...(p.clientIdProduction ? [{ clientId: p.clientIdProduction, label: `${p.name} · production` }] : []),
  ]);

  const setClient = (next: string) => {
    const updated = new URLSearchParams(params);
    if (next) {
      updated.set("clientId", next);
    } else {
      updated.delete("clientId");
    }
    setParams(updated);
  };

  return (
    <div className="page">
      <PageHeader
        title="API logs"
        subtitle={`${rows.length} call${rows.length === 1 ? "" : "s"}${failed > 0 ? `, ${failed} with errors` : ""} · newest first, refreshed every 20 seconds · kept for 30 days`}
      />
      <ErrorBanner error={logs.error ?? partners.error} />

      <div className="card">
        <div className="tabs" style={{ gap: 10, flexWrap: "wrap" }}>
          <select className="select" style={{ width: 160, margin: "9px 0" }} value={windowKey}
            onChange={(e) => setWindowKey(e.target.value as (typeof WINDOWS)[number]["key"])}>
            {WINDOWS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
          </select>
          <select className="select" style={{ width: 190, margin: "9px 0" }} value={status}
            onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <select className="select" style={{ width: 240, margin: "9px 0" }} value={clientId}
            onChange={(e) => setClient(e.target.value)}>
            <option value="">All partners</option>
            {clientOptions.map((c) => <option key={c.clientId} value={c.clientId}>{c.label}</option>)}
          </select>
          <div className="grow" />
          <input className="input" style={{ width: 240, margin: "9px 0" }} placeholder="Search API name or path"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>

        {logs.isLoading ? <div className="empty">Loading…</div> : rows.length === 0 ? (
          <div className="empty">
            No calls match these filters. Traffic appears here once the gateways report it; with no gateway
            running, this stays empty.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 150 }}>When</th><th>API</th><th style={{ width: 110 }}>Environment</th>
                <th style={{ width: 220 }}>Partner</th><th style={{ width: 90 }}>Status</th><th style={{ width: 90 }}>Latency</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono muted nowrap" style={{ fontSize: 11.5 }}>{formatDateTime(r.occurredAt)}</td>
                  <td>
                    <div className="cell-title">{r.apiName}</div>
                    <div className="cell-sub">{r.httpMethod ? `${r.httpMethod} ` : ""}{r.proxyPath ?? ""}</div>
                  </td>
                  <td><Chip tone={r.environment === "PRODUCTION" ? "warn" : "info"}>{r.environment}</Chip></td>
                  <td>
                    {r.partnerName ? (
                      <>
                        <div style={{ fontSize: 12.5 }}>{r.partnerName}</div>
                        <div className="cell-sub">{r.clientId}</div>
                      </>
                    ) : <span className="mono muted" style={{ fontSize: 11.5 }}>{r.clientId ?? "unknown"}</span>}
                  </td>
                  <td><Chip tone={statusTone(r.statusCode)}><span className="mono">{r.statusCode}</span></Chip></td>
                  <td className="mono muted" style={{ fontSize: 12 }}>{r.latencyMs} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="muted" style={{ fontSize: 12, maxWidth: 820, lineHeight: 1.6 }}>
        Calls are attributed to the partner's Client ID, which is what the gateway authenticates — a single
        organization's calls are not attributable to one of its portal users. For actions people took inside the
        portals, see the Audit log.
      </p>
    </div>
  );
}
