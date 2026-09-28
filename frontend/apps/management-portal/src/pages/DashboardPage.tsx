import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Chip, ErrorBanner, PageHeader, useAuth, type DashboardSummary } from "@apigw/ui";

/** Landing page: what is configured, and what the gateways did in the last hour (BRD CP-RPT-01). */
export function DashboardPage() {
  const { api } = useAuth();
  const data = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardSummary>("/api/admin/dashboard"),
    refetchInterval: 30_000,
  });

  const d = data.data;
  const lastHour = d?.lastHour;
  const total = (lastHour?.success ?? 0) + (lastHour?.failed ?? 0);

  return (
    <div className="page">
      <PageHeader
        title="Dashboard"
        subtitle="Traffic figures cover the last hour and refresh every 30 seconds."
      />
      <ErrorBanner error={data.error} />

      {data.isLoading || !d ? <div className="empty">Loading…</div> : (
        <>
          <div className="row" style={{ gap: 14, flexWrap: "wrap", alignItems: "stretch" }}>
            <Stat label="APIs" value={d.counts.apis} sub={`${d.counts.activeApis} active · ${d.counts.draftApis} draft · ${d.counts.disabledApis} disabled`} to="/apis" />
            <Stat label="Partners" value={d.counts.partners} sub={`${d.counts.activePartners} active · ${d.counts.productionPartners} with Production`} to="/partners" />
            <Stat label="Partner users" value={d.counts.partnerUsers} sub="Developer Portal logins" to="/partner-users" />
            <Stat label="Calls (1 h)" value={total} sub={total === 0 ? "no traffic yet" : `${d.lastHour.successRate}% success`} to="/logs" />
            <Stat label="Errors (1 h)" value={d.lastHour.failed} tone={d.lastHour.failed > 0 ? "bad" : undefined}
              sub={d.lastHour.avgLatencyMs == null ? "no traffic yet" : `avg ${d.lastHour.avgLatencyMs} ms`} to="/logs?status=ERROR" />
          </div>

          <div className="row" style={{ gap: 16, alignItems: "stretch", flexWrap: "wrap" }}>
            <div className="card grow" style={{ minWidth: 380 }}>
              <div className="card-head">
                <div className="grow">
                  <div className="card-title">Busiest APIs (last hour)</div>
                  <div className="card-sub">Success and failure counts per API.</div>
                </div>
                <Link className="btn btn-sm" to="/usage">Full report</Link>
              </div>
              {d.topApis.length === 0 ? <div className="empty">No calls in the last hour.</div> : (
                <table className="table">
                  <thead><tr><th>API</th><th style={{ width: 80 }}>Success</th><th style={{ width: 80 }}>Errors</th><th style={{ width: 90 }}>Avg latency</th></tr></thead>
                  <tbody>
                    {d.topApis.map((a) => (
                      <tr key={a.apiId}>
                        <td><div className="cell-title">{a.apiName}</div><div className="cell-sub">{a.proxyPath}</div></td>
                        <td className="mono" style={{ fontSize: 12 }}>{a.success.toLocaleString("en-IN")}</td>
                        <td className="mono" style={{ fontSize: 12, color: a.failed > 0 ? "var(--bad)" : undefined }}>
                          {a.failed.toLocaleString("en-IN")}
                        </td>
                        <td className="mono muted" style={{ fontSize: 12 }}>{a.avgLatencyMs == null ? "—" : `${a.avgLatencyMs} ms`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="card grow" style={{ minWidth: 380 }}>
              <div className="card-head">
                <div className="grow">
                  <div className="card-title">Busiest partners (last hour)</div>
                  <div className="card-sub">Calls are counted per Client ID, as the gateway sees them.</div>
                </div>
              </div>
              {d.topPartners.length === 0 ? <div className="empty">No calls in the last hour.</div> : (
                <table className="table">
                  <thead><tr><th>Partner</th><th style={{ width: 80 }}>Success</th><th style={{ width: 80 }}>Errors</th><th style={{ width: 90 }}>Avg latency</th></tr></thead>
                  <tbody>
                    {d.topPartners.map((p) => (
                      <tr key={p.clientId}>
                        <td>
                          <div className="cell-title">{p.partnerName ?? "Unknown Client ID"}</div>
                          <div className="cell-sub">{p.clientId}</div>
                        </td>
                        <td className="mono" style={{ fontSize: 12 }}>{p.success.toLocaleString("en-IN")}</td>
                        <td className="mono" style={{ fontSize: 12, color: p.failed > 0 ? "var(--bad)" : undefined }}>
                          {p.failed.toLocaleString("en-IN")}
                        </td>
                        <td className="mono muted" style={{ fontSize: 12 }}>{p.avgLatencyMs == null ? "—" : `${p.avgLatencyMs} ms`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, sub, to, tone }: {
  label: string;
  value: number;
  sub: string;
  to: string;
  tone?: "bad";
}) {
  return (
    <Link className="card stat" to={to} style={{ minWidth: 190, textDecoration: "none", color: "inherit" }}>
      <div className="row" style={{ gap: 8 }}>
        <span className="label grow">{label}</span>
        {tone === "bad" && value > 0 ? <Chip tone="bad">attention</Chip> : null}
      </div>
      <div className="stat-value" style={{ color: tone === "bad" && value > 0 ? "var(--bad)" : undefined }}>
        {value.toLocaleString("en-IN")}
      </div>
      <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>{sub}</div>
    </Link>
  );
}
