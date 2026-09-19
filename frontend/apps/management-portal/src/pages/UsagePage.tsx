import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ErrorBanner, formatDateTime, formatNumber, PageHeader, useAuth, type UsageReport } from "@apigw/ui";

const RANGES = [
  { key: "15m", label: "15 min", minutes: 15 },
  { key: "1h", label: "1 hour", minutes: 60 },
  { key: "24h", label: "24 hours", minutes: 1440 },
  { key: "7d", label: "7 days", minutes: 10080 },
  { key: "30d", label: "30 days", minutes: 43200 },
] as const;

/** API usage report (design: UsageReport.dc.html; BRD CP-RPT-01..03). Opens on the last 15 minutes. */
export function UsagePage() {
  const { api } = useAuth();
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("15m");
  const [clientId, setClientId] = useState("");
  const [applied, setApplied] = useState("");

  const minutes = RANGES.find((r) => r.key === range)!.minutes;
  const report = useQuery({
    queryKey: ["usage", range, applied],
    queryFn: () => {
      const params = new URLSearchParams({ from: new Date(Date.now() - minutes * 60_000).toISOString() });
      if (applied) {
        params.set("clientId", applied);
      }
      return api.get<UsageReport>(`/api/admin/usage/report?${params}`);
    },
    refetchInterval: 30_000,
  });

  const r = report.data;
  const total = r ? r.totalSuccess + r.totalFailed : 0;
  const successRate = r && total ? (r.totalSuccess / total) * 100 : null;

  return (
    <div className="page">
      <PageHeader title="API usage & analytics" subtitle="Success, failure and latency per API, measured at the gateway. Data is kept for 30 days." />

      <div className="card row" style={{ padding: "13px 15px", flexWrap: "wrap", alignItems: "flex-end" }}>
        <div className="field">
          <span className="label">Range</span>
          <div className="segmented">
            {RANGES.map((x) => (
              <button key={x.key} className={range === x.key ? "on" : ""} onClick={() => setRange(x.key)}>{x.label}</button>
            ))}
          </div>
        </div>
        <div className="field" style={{ width: 240 }}>
          <span className="label">Client ID</span>
          <input className="input mono" placeholder="e.g. acme-fintech-sbx" value={clientId} onChange={(e) => setClientId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && setApplied(clientId.trim())} />
        </div>
        <button className="btn btn-primary" onClick={() => setApplied(clientId.trim())}>Apply</button>
        <div className="grow" />
        {r ? <span className="muted" style={{ fontSize: 12 }}>{formatDateTime(r.from)} – {formatDateTime(r.to)}</span> : null}
      </div>
      <ErrorBanner error={report.error} />

      <div className="row" style={{ gap: 12 }}>
        <Stat label="Total calls" value={formatNumber(total)} />
        <Stat label="Successful" value={formatNumber(r?.totalSuccess)} />
        <Stat label="Failed" value={formatNumber(r?.totalFailed)} tone={r && r.totalFailed > 0 ? "var(--bad)" : undefined} />
        <Stat label="Success rate" value={successRate == null ? "—" : `${successRate.toFixed(2)} %`} />
      </div>

      <div className="card">
        <div className="card-head"><div className="card-title grow">API-wise report</div></div>
        {report.isLoading ? <div className="empty">Loading…</div> : !r || r.apis.length === 0 ? (
          <div className="empty">No calls in this window. Widen the range, or check that the gateway's usage logger is reaching the backend.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>API</th><th className="num">Success</th><th className="num">Failed</th><th className="num">Success %</th>
                <th className="num">Min ms</th><th className="num">Max ms</th><th className="num">Avg ms</th>
              </tr>
            </thead>
            <tbody>
              {r.apis.map((a) => (
                <tr key={a.apiId}>
                  <td><div className="cell-title">{a.apiName}</div><div className="cell-sub">{a.proxyPath}</div></td>
                  <td className="num">{formatNumber(a.success)}</td>
                  <td className="num" style={{ color: a.successRate < 97 ? "var(--bad)" : undefined }}>{formatNumber(a.failed)}</td>
                  <td className="num">{a.successRate.toFixed(2)}</td>
                  <td className="num">{formatNumber(a.minLatencyMs)}</td>
                  <td className="num">{formatNumber(a.maxLatencyMs)}</td>
                  <td className="num">{formatNumber(a.avgLatencyMs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="stat-value" style={{ color: tone }}>{value}</div>
    </div>
  );
}
