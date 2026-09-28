import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Chip, CodeBlock, ErrorBanner, formatDateTime, Modal, PageHeader, useAuth, type ErrorView } from "@apigw/ui";

const SOURCES = ["ALL", "SMTP", "GATEWAY", "SCHEDULER", "API"] as const;

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

  const errors = useQuery({
    queryKey: ["errors", source],
    queryFn: () => api.get<ErrorView[]>(`/api/admin/errors?limit=200${source === "ALL" ? "" : `&source=${source}`}`),
    refetchInterval: 20_000,
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

        {errors.isLoading ? <div className="empty">Loading…</div> : rows.length === 0 ? (
          <div className="empty">Nothing has failed{source === "ALL" ? "" : ` in ${source}`} in the retained period.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 150 }}>When</th><th style={{ width: 110 }}>Source</th><th style={{ width: 170 }}>Code</th>
                <th>Message</th><th style={{ width: 130 }}>Reference</th><th style={{ width: 70 }} />
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td className="mono muted nowrap" style={{ fontSize: 11.5 }}>{formatDateTime(e.occurredAt)}</td>
                  <td><Chip tone={SOURCE_TONE[e.source] ?? "neutral"}>{e.source}</Chip></td>
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
