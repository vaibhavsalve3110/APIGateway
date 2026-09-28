import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  Chip, ErrorBanner, formatDateTime, statusTone, useAuth,
  type ApiUsage, type UsageLogEntry,
} from "@apigw/ui";

const WINDOWS = [
  { key: "PT1H", label: "Last hour" },
  { key: "PT24H", label: "Last 24 hours" },
  { key: "P7D", label: "Last 7 days" },
  { key: "P30D", label: "Last 30 days" },
] as const;

interface PartnerDashboard {
  partnerName: string;
  partnerCode: string;
  counts: { apisAvailable: number; products: number; activeKeys: number; productionAvailable: boolean };
  window: { from: string; success: number; failed: number; successRate: number; avgLatencyMs: number | null };
  apis: ApiUsage[];
  recentCalls: UsageLogEntry[];
}

/** The partner's own usage history (BRD DP-02): what they called, when, and how it went. */
export function DashboardPage() {
  const { api } = useAuth();
  const [window, setWindow] = useState<(typeof WINDOWS)[number]["key"]>("PT24H");

  const data = useQuery({
    queryKey: ["partner-dashboard", window],
    queryFn: () => api.get<PartnerDashboard>(`/api/partner/dashboard?window=${window}`),
    refetchInterval: 30_000,
  });

  const d = data.data;
  // Zeroes, never blanks: a quiet account is a fact, not a missing value.
  const totals = d?.window ?? { success: 0, failed: 0, successRate: 0, avgLatencyMs: null, from: "" };
  const calls = totals.success + totals.failed;
  const windowLabel = WINDOWS.find((w) => w.key === window)?.label.toLowerCase() ?? "";

  return (
    <div className="page" style={{ padding: "28px 30px 34px" }}>
      <div className="page-head">
        <div className="grow">
          <h1 style={{ fontSize: 26 }}>Your API usage</h1>
          <p className="page-sub" style={{ fontSize: 13.5, maxWidth: 660 }}>
            Every call your organisation made through the gateway, {windowLabel}. Figures refresh every 30 seconds
            and are kept for 30 days.
          </p>
        </div>
        <select className="select" style={{ width: 170 }} value={window}
          onChange={(e) => setWindow(e.target.value as (typeof WINDOWS)[number]["key"])}>
          {WINDOWS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
        </select>
      </div>
      <ErrorBanner error={data.error} />

      <div className="row" style={{ gap: 14, flexWrap: "wrap", alignItems: "stretch" }}>
        <Stat label="Calls" value={calls} sub={calls === 0 ? "no calls yet" : `${totals.successRate}% success`} />
        <Stat label="Errors" value={totals.failed} tone={totals.failed > 0 ? "bad" : undefined}
          sub={totals.failed === 0 ? "nothing failed" : "4xx and 5xx responses"} />
        <Stat label="Average latency" value={totals.avgLatencyMs ?? 0} unit="ms"
          sub={totals.avgLatencyMs == null ? "no calls yet" : "gateway to backend and back"} />
        <Stat label="APIs available" value={d?.counts.apisAvailable ?? 0} sub="in your catalogue" />
        <Stat label="Products" value={d?.counts.products ?? 0} sub="journeys assigned to you" />
        <Stat label="Active keys" value={d?.counts.activeKeys ?? 0}
          sub={d?.counts.productionAvailable ? "sandbox and production" : "sandbox only"} />
      </div>

      <div className="card">
        <div className="card-head">
          <div className="grow">
            <div className="card-title">By API</div>
            <div className="card-sub">Where your calls went, busiest first.</div>
          </div>
        </div>
        {data.isLoading ? <div className="empty">Loading…</div> : (d?.apis.length ?? 0) === 0 ? (
          <div className="empty">
            No calls in this period. Once your integration starts calling the gateway, usage appears here —
            you can try an API from <Link to="/apis">your catalogue</Link>.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr><th>API</th><th style={{ width: 90 }}>Success</th><th style={{ width: 90 }}>Errors</th>
                <th style={{ width: 100 }}>Success rate</th><th style={{ width: 110 }}>Avg latency</th></tr>
            </thead>
            <tbody>
              {(d?.apis ?? []).map((a) => (
                <tr key={a.apiId}>
                  <td><div className="cell-title">{a.apiName}</div><div className="cell-sub">{a.proxyPath}</div></td>
                  <td className="mono" style={{ fontSize: 12 }}>{a.success.toLocaleString("en-IN")}</td>
                  <td className="mono" style={{ fontSize: 12, color: a.failed > 0 ? "var(--bad)" : undefined }}>
                    {a.failed.toLocaleString("en-IN")}
                  </td>
                  <td className="mono" style={{ fontSize: 12 }}>{a.successRate}%</td>
                  <td className="mono muted" style={{ fontSize: 12 }}>{a.avgLatencyMs == null ? "—" : `${a.avgLatencyMs} ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <div className="grow">
            <div className="card-title">Recent calls</div>
            <div className="card-sub">The last 25 requests the gateway recorded for your Client IDs.</div>
          </div>
        </div>
        {(d?.recentCalls.length ?? 0) === 0 ? (
          <div className="empty">No calls recorded in this period.</div>
        ) : (
          <table className="table">
            <thead>
              <tr><th style={{ width: 160 }}>When</th><th>API</th><th style={{ width: 120 }}>Environment</th>
                <th style={{ width: 90 }}>Status</th><th style={{ width: 90 }}>Latency</th></tr>
            </thead>
            <tbody>
              {(d?.recentCalls ?? []).map((c) => (
                <tr key={c.id}>
                  <td className="mono muted nowrap" style={{ fontSize: 11.5 }}>{formatDateTime(c.occurredAt)}</td>
                  <td>
                    <div className="cell-title">{c.apiName}</div>
                    <div className="cell-sub">{c.httpMethod ? `${c.httpMethod} ` : ""}{c.proxyPath ?? ""}</div>
                  </td>
                  <td><Chip tone={c.environment === "PRODUCTION" ? "warn" : "info"}>{c.environment}</Chip></td>
                  <td><Chip tone={statusTone(c.statusCode)}><span className="mono">{c.statusCode}</span></Chip></td>
                  <td className="mono muted" style={{ fontSize: 12 }}>{c.latencyMs} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, sub, unit, tone }: {
  label: string;
  value: number;
  sub: string;
  unit?: string;
  tone?: "bad";
}) {
  return (
    <div className="card stat" style={{ minWidth: 175 }}>
      <span className="label">{label}</span>
      <div className="stat-value" style={{ color: tone === "bad" && value > 0 ? "var(--bad)" : undefined }}>
        {value.toLocaleString("en-IN")}{unit ? <span style={{ fontSize: 14, marginLeft: 3 }}>{unit}</span> : null}
      </div>
      <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>{sub}</div>
    </div>
  );
}
