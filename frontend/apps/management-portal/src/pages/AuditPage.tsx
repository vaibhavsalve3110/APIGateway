import { useQuery } from "@tanstack/react-query";

import { Chip, ErrorBanner, formatDateTime, PageHeader, useAuth, type AuditView } from "@apigw/ui";

const ACTION_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  CREATE: "ok", GENERATE: "info", UPDATE: "info", ACCESS_TIER: "warn", DISABLE: "warn", ENABLE: "ok",
  REVOKE: "bad", DELETE: "bad", EXPIRE: "neutral",
};

/** Audit trail (BRD CP-LOG-05, CP-SEC-07). */
export function AuditPage() {
  const { api } = useAuth();
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<AuditView[]>("/api/admin/audit?limit=200"), refetchInterval: 20_000 });

  return (
    <div className="page">
      <PageHeader title="Audit log" subtitle="Every configuration and key action, with who did it and when. Automatic key expiry is recorded as “System”." />
      <ErrorBanner error={audit.error} />
      <div className="card">
        {audit.isLoading ? <div className="empty">Loading…</div> : (
          <table className="table">
            <thead><tr><th style={{ width: 160 }}>Timestamp</th><th>User</th><th>Action</th><th>Object</th><th>Detail</th></tr></thead>
            <tbody>
              {(audit.data ?? []).map((a) => (
                <tr key={a.id}>
                  <td className="mono muted" style={{ fontSize: 11.5 }}>{formatDateTime(a.occurredAt)}</td>
                  <td style={{ fontSize: 12 }}>{a.actor}{a.actorRole ? <span className="muted"> · {a.actorRole.toLowerCase()}</span> : null}</td>
                  <td><Chip tone={ACTION_TONE[a.action] ?? "neutral"}>{a.action.replace("_", " ")}</Chip></td>
                  <td style={{ fontSize: 12 }}>{a.objectType.replace("_", " ").toLowerCase()}</td>
                  <td className="muted" style={{ fontSize: 12 }}>{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
